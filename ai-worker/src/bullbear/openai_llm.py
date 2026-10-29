"""OpenAI Responses adapter for local debate experiments."""
from __future__ import annotations

import json

from openai import OpenAI

from .llm import LLM, LLMError, Usage


class OpenAILLM(LLM):
    def __init__(self, model, client=None, max_tool_turns=8):
        self.model = model
        self.client = client or OpenAI(timeout=180.0, max_retries=1)
        self.max_tool_turns = max_tool_turns
        self.usage = Usage()
        self.usage_by_model = {}

    def structured(self, conv, *, schema, effort, tools=None, tool_handler=None, on_event=None):
        on_event = on_event or (lambda *_: None)
        functions = [{"type": "function", "name": t["name"], "description": t["description"],
                      "parameters": t["input_schema"], "strict": True} for t in tools or []]
        allowed = {t["name"] for t in functions}
        for _ in range(self.max_tool_turns):
            response = self.client.responses.create(
                model=self.model, instructions=conv.system, input=conv.messages,
                tools=functions, reasoning={"effort": effort},
                text={"format": {"type": "json_schema", "name": "debate_output",
                                  "schema": schema, "strict": True}},
                max_output_tokens=16000, store=False, include=["reasoning.encrypted_content"],
            )
            if response.usage is not None:
                cached = getattr(response.usage.input_tokens_details, "cached_tokens", 0) or 0
                for usage in (self.usage, self.usage_by_model.setdefault(response.model, Usage())):
                    usage.input_tokens += response.usage.input_tokens - cached
                    usage.cache_read_input_tokens += cached
                    usage.output_tokens += response.usage.output_tokens
                    usage.requests += 1
            if response.status != "completed":
                raise LLMError("OpenAI response did not complete")
            # Keep reasoning items and function calls alongside their outputs on every retry.
            conv.messages.extend(item.model_dump(exclude_none=True) for item in response.output)
            calls = [item for item in response.output if item.type == "function_call"]
            if any(part.type == "refusal" for item in response.output if item.type == "message"
                   for part in item.content):
                raise LLMError("OpenAI refused the response")
            if not calls:
                try:
                    value = json.loads(response.output_text)
                except json.JSONDecodeError as exc:
                    raise LLMError("OpenAI structured output could not be parsed") from exc
                if not isinstance(value, dict):
                    raise LLMError("OpenAI structured output must be an object")
                return value
            for call in calls:
                on_event("tool_call", {"name": call.name})
                try:
                    arguments = json.loads(call.arguments)
                    if call.name not in allowed or tool_handler is None or not isinstance(arguments, dict):
                        raise ValueError("Invalid tool call")
                    output = tool_handler(call.name, arguments)
                except Exception:
                    output = '{"error":"Snapshot tool failed or received invalid arguments"}'
                conv.messages.append({"type": "function_call_output", "call_id": call.call_id, "output": output})
        raise LLMError(f"Tool loop exceeded {self.max_tool_turns} requests")
