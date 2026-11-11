"""Claude 호출 공통부: 스트리밍 + 도구 루프 + 구조화 출력.

- 로컬 도구는 호출자가 넘긴 핸들러가 실행하고, 서버 도구는 Anthropic이 실행한다.
- 대화 기록은 덧붙이기만 한다. 응답 content를 그대로 다시 보내야 thinking 블록이 유지된다.
- Haiku·Sonnet만 허용하며 서버 측 자동 모델 대체는 사용하지 않는다.
"""

from __future__ import annotations

import json
from copy import deepcopy
import re
from collections.abc import Callable
from dataclasses import dataclass, field
from typing import Any

import anthropic


def anthropic_schema(schema: dict) -> dict:
    """Adapt API grammar constraints; callers still validate the original schema.

    https://platform.claude.com/docs/en/build-with-claude/structured-outputs
    Bounds are retained as model guidance, not silently discarded.
    """
    result = deepcopy(schema)
    constraints = ('minimum', 'maximum', 'exclusiveMinimum', 'exclusiveMaximum',
                   'multipleOf', 'minLength', 'maxLength', 'maxItems', 'uniqueItems')

    def visit(node):
        if not isinstance(node, dict):
            return
        removed = {key: node.pop(key) for key in constraints if key in node}
        if node.get('minItems', 0) > 1:
            removed['minItems'] = node['minItems']
            node['minItems'] = 1
        if removed:
            node['description'] = (node.get('description', '') + ' Constraints: ' +
                                   json.dumps(removed, ensure_ascii=False)).strip()
        for key in ('properties', '$defs', 'definitions', 'patternProperties'):
            for child in node.get(key, {}).values():
                visit(child)
        for key in ('items', 'additionalProperties', 'not'):
            visit(node.get(key))
        for key in ('anyOf', 'allOf', 'oneOf', 'prefixItems'):
            for child in node.get(key, []):
                visit(child)

    visit(result)
    return result

def validate_model(model: str) -> None:
    # Accept both family-first and older version-first Anthropic model IDs.
    # Availability is checked separately against the account's model catalogue.
    if not re.fullmatch(r"claude-(?:(?:haiku|sonnet)-[0-9][a-z0-9-]*|[0-9][0-9-]*-(?:haiku|sonnet)(?:-[a-z0-9]+)*)", model):
        raise ValueError("Only Claude Haiku or Sonnet models are allowed")

ToolHandler = Callable[[str, dict], str]
EventHook = Callable[[str, dict], None]


class LLMError(RuntimeError):
    pass


class LLMRequestBlocked(LLMError):
    """A local guard rejected the request before transport began."""
    pass


def validate_snapshot_model(model: str) -> None:
    # Only families documented to support system messages inside ``messages``.
    if not re.fullmatch(r'claude-(?:haiku|sonnet)-5-5(?:-\d{8})?', model):
        raise LLMRequestBlocked('Snapshot-first prompts require Claude Haiku 5.5 or Sonnet 5.5')


@dataclass
class Usage:
    input_tokens: int = 0
    output_tokens: int = 0
    cache_read_input_tokens: int = 0
    cache_creation_input_tokens: int = 0
    requests: int = 0

    def add(self, usage: Any) -> None:
        self.input_tokens += usage.input_tokens or 0
        self.output_tokens += usage.output_tokens or 0
        self.cache_read_input_tokens += getattr(usage, "cache_read_input_tokens", 0) or 0
        self.cache_creation_input_tokens += getattr(usage, "cache_creation_input_tokens", 0) or 0
        self.requests += 1


@dataclass
class Conversation:
    """한 에이전트의 한 차례 발언 대화. 검증 반려 시 같은 대화에 피드백을 덧붙여 재생성한다."""

    system: str
    messages: list[dict] = field(default_factory=list)
    system_in_messages: bool = False
    context_ids: Any = None  # Worker-only codec; never serialized to the provider.

    @classmethod
    def from_snapshot(cls, system: str, snapshot_context: dict, request_context: dict,
                      *, images: list[dict] | None = None) -> Conversation:
        """Cache frozen data before request-specific instructions and the role.

        Keep the system message in its original position on tool calls and retries;
        moving it again would change the prefix and the meaning of past turns.
        ``system`` also remains available to audit consumers as the role text.
        """
        messages = [
            {'role': 'user', 'content': [{
                'type': 'text',
                'text': json.dumps(snapshot_context, ensure_ascii=False, sort_keys=True, separators=(',', ':')),
                'cache_control': {'type': 'ephemeral', 'ttl': '5m'},
            }]},
            {'role': 'user', 'content': json.dumps(request_context, ensure_ascii=False, separators=(',', ':'))},
        ]
        if images:
            messages.append({'role': 'user', 'content': deepcopy(images)})
        messages.append({'role': 'system', 'content': system})
        return cls(system, messages, system_in_messages=True)


class LLM:
    def __init__(self, model: str, client: anthropic.Anthropic | None = None, max_tool_turns: int = 8,
                 *, allow_fallbacks: bool = False, max_output_tokens: int = 16000,
                 budget=None, budget_scope: str = 'worker'):
        validate_model(model)
        if allow_fallbacks:
            raise ValueError("Automatic model fallbacks are disabled")
        self.model = model
        self.client = client or (anthropic.Anthropic(max_retries=0, timeout=180.0) if budget is not None
                                 else anthropic.Anthropic())
        if budget is not None and getattr(self.client, 'max_retries', 0) != 0:
            raise ValueError('Budgeted clients must disable hidden SDK retries')
        self.budget, self.budget_scope = budget, budget_scope
        self.max_tool_turns = max_tool_turns
        self.allow_fallbacks = allow_fallbacks
        self.max_output_tokens = max_output_tokens
        self.usage = Usage()
        self.usage_by_model: dict[str, Usage] = {}
        self.usage_complete = True
        self.requests_attempted = 0
        self.request_observer = None

    def usage_payload(self) -> dict:
        return {"calls": [{"model": model, "input_tokens": u.input_tokens,
                           "output_tokens": u.output_tokens, "cache_read_input_tokens": u.cache_read_input_tokens,
                           "cache_creation_input_tokens": u.cache_creation_input_tokens}
                          for model, u in self.usage_by_model.items()]}

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
        if conv.system_in_messages:
            validate_snapshot_model(self.model)
        on_event = on_event or (lambda *_: None)
        tools = [{**t, "input_schema": anthropic_schema(t["input_schema"]),
                  "strict": True, "eager_input_streaming": True}
                 if t.get("type", "custom") == "custom" else t for t in tools or []]
        json_retries = 0

        for _ in range(self.max_tool_turns):
            parameters = dict(model=self.model, max_tokens=self.max_output_tokens,
                system=anthropic.omit if conv.system_in_messages else conv.system,
                messages=conv.messages, tools=tools or anthropic.omit,
                output_config={"effort": effort, "format": {"type": "json_schema", "schema": anthropic_schema(schema)}})
            reservation = None
            if self.budget is not None:
                parameters.update(service_tier='standard_only', inference_geo='global')
                reservation = self.budget.reserve(parameters, scope=self.budget_scope)
            self.requests_attempted += 1
            request = {'request_id': self.requests_attempted, 'status': 'running'}
            if self.request_observer:
                # Persist the attempt before starting a potentially billable request.
                try:
                    self.request_observer(request)
                except BaseException:
                    if reservation is not None:
                        self.budget.cancel_before_dispatch(reservation)
                    raise
            try:
                with self.client.beta.messages.stream(**parameters) as stream:
                    for event in stream:
                        if event.type == "text":
                            on_event("token", {"text": event.text})
                    msg = stream.get_final_message()
                # Read counters before changing the cumulative totals.
                observed = Usage()
                observed.add(msg.usage)
                if reservation is not None:
                    self.budget.settle(reservation, msg)
            except LLMRequestBlocked:
                if reservation is not None:
                    self.budget.cancel_before_dispatch(reservation)
                if self.request_observer:
                    self.request_observer({**request, 'status': 'not_dispatched'})
                raise
            except BaseException as exc:
                if reservation is not None:
                    self.budget.unknown(reservation, type(exc).__name__)
                self.usage_complete = False  # Sticky across retries and later calls.
                if self.request_observer:
                    self.request_observer({**request, 'status': 'unknown', 'error_type': type(exc).__name__})
                if isinstance(exc, ValueError):
                    json_retries += 1
                    if json_retries <= 2:
                        continue
                raise

            json_retries = 0
            self.usage.add(msg.usage)
            self.usage_by_model.setdefault(msg.model, Usage()).add(msg.usage)
            if self.request_observer:
                self.request_observer({**request, 'status': 'received', 'usage': {'calls': [{
                    'model': msg.model, 'input_tokens': observed.input_tokens,
                    'output_tokens': observed.output_tokens,
                    'cache_read_input_tokens': observed.cache_read_input_tokens,
                    'cache_creation_input_tokens': observed.cache_creation_input_tokens}]}})
            try:
                validate_model(msg.model)
            except ValueError:
                # Keep incurred usage, but never continue with an unexpected family.
                raise LLMError("Provider returned a disallowed model family") from None
            if msg.stop_reason == "refusal":
                raise LLMError(f"모델이 응답을 거절했습니다: {msg.stop_details}")
            if msg.stop_reason == "max_tokens":
                raise LLMError("max_tokens에 도달해 응답이 잘렸습니다")

            conv.messages.append({"role": "assistant", "content": msg.content})
            for block in msg.content:
                if block.type in {"server_tool_use", "web_fetch_tool_result"}:
                    on_event(block.type, block.model_dump(mode="json"))
            if msg.stop_reason == "pause_turn":
                continue
            tool_uses = [b for b in msg.content if b.type == "tool_use"]
            if not tool_uses:
                # Server tool turns can include an explanation before the fetch.
                last_fetch = max((i for i, b in enumerate(msg.content) if b.type == "web_fetch_tool_result"), default=-1)
                text = "".join(b.text for b in msg.content[last_fetch + 1:] if b.type == "text")
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
