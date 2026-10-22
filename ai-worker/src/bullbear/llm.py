"""Claude 호출 공통부: 스트리밍 + 도구 루프 + 구조화 출력.

- 도구 실행은 호출자가 넘긴 핸들러가 한다. 이 모듈은 스냅샷을 모른다.
- 대화 기록은 덧붙이기만 한다. 응답 content를 그대로 다시 보내야 thinking 블록이 유지된다.
- 거절(refusal) 시 서버 측 폴백 모델로 자동 재시도한다 (fallbacks="default").
"""

from __future__ import annotations

import json
from collections.abc import Callable
from dataclasses import dataclass, field
from typing import Any

import anthropic

FALLBACK_BETA = "server-side-fallback-2026-07-01"

ToolHandler = Callable[[str, dict], str]
EventHook = Callable[[str, dict], None]


class LLMError(RuntimeError):
    pass


@dataclass
class Usage:
    input_tokens: int = 0
    output_tokens: int = 0
    cache_read_input_tokens: int = 0
    requests: int = 0

    def add(self, usage: Any) -> None:
        self.input_tokens += usage.input_tokens or 0
        self.output_tokens += usage.output_tokens or 0
        self.cache_read_input_tokens += getattr(usage, "cache_read_input_tokens", 0) or 0
        self.requests += 1


@dataclass
class Conversation:
    """한 에이전트의 한 차례 발언 대화. 검증 반려 시 같은 대화에 피드백을 덧붙여 재생성한다."""

    system: str
    messages: list[dict] = field(default_factory=list)


class LLM:
    def __init__(self, model: str, client: anthropic.Anthropic | None = None, max_tool_turns: int = 8):
        self.model = model
        self.client = client or anthropic.Anthropic()
        self.max_tool_turns = max_tool_turns
        self.usage = Usage()

    def structured(
        self,
        conv: Conversation,
        *,
        schema: dict,
        effort: str,
        tools: list[dict] | None = None,
        tool_handler: ToolHandler | None = None,
        on_event: EventHook | None = None,
    ) -> dict:
        """도구를 쓰게 한 뒤 schema에 맞는 JSON 하나를 받아 dict로 돌려준다."""
        on_event = on_event or (lambda *_: None)
        tools = [{**t, "strict": True, "eager_input_streaming": True} for t in tools or []]
        json_retries = 0

        for _ in range(self.max_tool_turns):
            try:
                with self.client.beta.messages.stream(
                    model=self.model,
                    max_tokens=16000,
                    system=conv.system,
                    messages=conv.messages,
                    tools=tools or anthropic.omit,
                    output_config={"effort": effort, "format": {"type": "json_schema", "schema": schema}},
                    betas=[FALLBACK_BETA],
                    fallbacks="default",
                ) as stream:
                    for event in stream:
                        if event.type == "text":
                            on_event("token", {"text": event.text})
                    msg = stream.get_final_message()
                json_retries = 0
            except ValueError:
                # 도구 입력 JSON을 SDK가 아예 파싱하지 못한 경우. 같은 요청을 다시 보낸다.
                json_retries += 1
                if json_retries > 2:
                    raise
                continue

            self.usage.add(msg.usage)
            if msg.stop_reason == "refusal":
                raise LLMError(f"모델이 응답을 거절했습니다: {msg.stop_details}")
            if msg.stop_reason == "max_tokens":
                raise LLMError("max_tokens에 도달해 응답이 잘렸습니다")

            conv.messages.append({"role": "assistant", "content": msg.content})
            tool_uses = [b for b in msg.content if b.type == "tool_use"]
            if not tool_uses:
                text = "".join(b.text for b in msg.content if b.type == "text")
                try:
                    return json.loads(text)
                except json.JSONDecodeError as e:
                    raise LLMError(f"구조화 출력 파싱 실패: {text[:300]}") from e

            results = []
            for block in tool_uses:
                on_event("tool_call", {"name": block.name})
                try:
                    content = tool_handler(block.name, block.input if isinstance(block.input, dict) else {})
                    results.append({"type": "tool_result", "tool_use_id": block.id, "content": content})
                except Exception as e:  # 도구 실패는 모델에게 알리고 계속
                    results.append({"type": "tool_result", "tool_use_id": block.id, "content": str(e), "is_error": True})
            conv.messages.append({"role": "user", "content": results})

        raise LLMError(f"도구 호출이 {self.max_tool_turns}회를 넘었습니다")
