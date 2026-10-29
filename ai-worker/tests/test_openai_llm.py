import json

import httpx
import pytest
from openai import OpenAI

from bullbear.llm import Conversation, LLMError
from bullbear.openai_llm import OpenAILLM
from bullbear.tools import TOOL_DEFINITIONS


def response(output, *, status="completed"):
    return {"id": "resp_test", "object": "response", "created_at": 1, "model": "actual-model",
            "status": status, "output": output, "parallel_tool_calls": True,
            "tool_choice": "auto", "tools": [],
            "usage": {"input_tokens": 100, "input_tokens_details": {"cached_tokens": 30},
                      "output_tokens": 20, "output_tokens_details": {"reasoning_tokens": 5}, "total_tokens": 120}}


def message(text='{"ok":true}', kind="output_text"):
    content = {"type": kind, "text": text, "annotations": []} if kind == "output_text" else {"type": "refusal", "refusal": "no"}
    return {"id": "msg_test", "type": "message", "role": "assistant", "status": "completed", "content": [content]}


def client_for(payloads, requests):
    pending = iter(payloads)
    def handle(request):
        requests.append(json.loads(request.content))
        return httpx.Response(200, json=next(pending))
    return OpenAI(api_key="test-only", http_client=httpx.Client(transport=httpx.MockTransport(handle)))


def test_tools_reasoning_feedback_and_cache_accounting():
    requests = []
    reasoning = {"id": "rs_test", "type": "reasoning", "summary": [], "encrypted_content": "opaque"}
    call = {"id": "fc_test", "type": "function_call", "name": "get_price_metrics", "call_id": "call_test", "arguments": "{}"}
    client = client_for([response([reasoning, call]), response([message()]), response([message()])], requests)
    llm = OpenAILLM("gpt-5-mini", client=client)
    conv = Conversation("system", [{"role": "user", "content": "debate"}])
    events = []
    assert llm.structured(conv, schema={"type": "object"}, effort="medium", tools=TOOL_DEFINITIONS,
                          tool_handler=lambda name, args: '{"close":399}',
                          on_event=lambda *args: events.append(args)) == {"ok": True}
    assert requests[1]["input"][1]["encrypted_content"] == "opaque"
    assert requests[1]["input"][-1] == {"type": "function_call_output", "call_id": "call_test", "output": '{"close":399}'}
    assert requests[0]["tools"][0]["parameters"] == TOOL_DEFINITIONS[0]["input_schema"]
    assert requests[0]["store"] is False
    assert events == [("tool_call", {"name": "get_price_metrics"})]
    conv.messages.append({"role": "user", "content": "fix evidence"})
    llm.structured(conv, schema={}, effort="medium")
    assert requests[2]["input"][-1]["content"] == "fix evidence"
    assert llm.usage.input_tokens == 210
    assert llm.usage.cache_read_input_tokens == 90
    assert llm.usage.output_tokens == 60
    assert llm.usage_payload()["calls"][0]["model"] == "actual-model"
    client.close()


@pytest.mark.parametrize("payload", [response([message(kind="refusal")]), response([], status="incomplete"), response([message("broken")])])
def test_invalid_or_refused_outputs_fail_closed(payload):
    client = client_for([payload], [])
    with pytest.raises(LLMError):
        OpenAILLM("gpt-5-mini", client=client).structured(Conversation("system"), schema={}, effort="medium")
    client.close()
