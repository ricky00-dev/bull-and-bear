from types import SimpleNamespace as NS
import json
import pytest

from bullbear.llm import Conversation, LLM, LLMError, LLMRequestBlocked
from bullbear.llm import anthropic_schema
from bullbear.schemas import STATEMENT_SCHEMA


class Stream:
    def __init__(self, model):
        self.model = model

    def __enter__(self):
        return self

    def __exit__(self, *args):
        pass

    def __iter__(self):
        return iter([])

    def get_final_message(self):
        return NS(model=self.model, stop_reason='end_turn', content=[NS(type='text', text='{}')],
                  usage=NS(input_tokens=10, output_tokens=5, cache_read_input_tokens=3, cache_creation_input_tokens=2))


def test_provider_schema_adaptation_preserves_original_validation_and_property_names():
    converted = anthropic_schema(STATEMENT_SCHEMA)
    evidence = converted['properties']['evidence']
    assert 'maxItems' not in evidence and evidence['minItems'] == 1
    assert '3' in evidence['description']
    assert STATEMENT_SCHEMA['properties']['evidence']['maxItems'] == 3
    nested = {'type': 'object', 'properties': {'maximum': {'type': 'number', 'minimum': 0}},
              '$defs': {'items': {'type': 'array', 'minItems': 2, 'maxItems': 4}}}
    result = anthropic_schema(nested)
    assert 'maximum' in result['properties'] and 'minimum' not in result['properties']['maximum']
    assert result['$defs']['items']['minItems'] == 1


def test_usage_tracks_actual_model_and_cache_writes_without_haiku_fallback():
    calls = []
    models = iter(['claude-haiku-5-5-20261001', 'claude-haiku-5-5-20261002', 'claude-haiku-5-5-20261001'])
    def stream(**kwargs):
        calls.append(kwargs)
        return Stream(next(models))
    llm = LLM('claude-haiku-5-5', client=NS(beta=NS(messages=NS(stream=stream))))
    for _ in range(3):
        llm.structured(Conversation('system'), schema={}, effort='medium')
    assert all('fallbacks' not in c and 'betas' not in c for c in calls)
    usage = {c['model']: c for c in llm.usage_payload()['calls']}
    assert usage['claude-haiku-5-5-20261001']['input_tokens'] == 20
    assert usage['claude-haiku-5-5-20261001']['cache_creation_input_tokens'] == 4
    assert usage['claude-haiku-5-5-20261002']['output_tokens'] == 5


@pytest.mark.parametrize('model', ['claude-opus-5-5', 'gpt-5-mini', '', 'claude-haiku-opus'])
def test_disallowed_models_are_rejected_before_client_creation(monkeypatch, model):
    monkeypatch.setattr('bullbear.llm.anthropic.Anthropic', lambda: pytest.fail('client created'))
    with pytest.raises(ValueError, match='Haiku or Sonnet'):
        LLM(model)


def test_sonnet_cannot_enable_unrestricted_server_fallback():
    with pytest.raises(ValueError, match='fallbacks are disabled'):
        LLM('claude-sonnet-5-5', allow_fallbacks=True)
    calls = []
    def stream(**kwargs):
        calls.append(kwargs)
        return Stream('claude-sonnet-5-5')
    llm = LLM('claude-sonnet-5-5', client=NS(beta=NS(messages=NS(stream=stream))))
    llm.structured(Conversation('system'), schema=STATEMENT_SCHEMA, effort='medium')
    request, = calls
    assert 'fallbacks' not in request and 'betas' not in request
    assert 'maxItems' not in request['output_config']['format']['schema']['properties']['evidence']


def test_unexpected_response_family_stops_and_preserves_incurred_usage():
    calls = []
    def stream(**kwargs):
        calls.append(kwargs)
        return Stream('claude-opus-5-5')
    llm = LLM('claude-sonnet-5-5', client=NS(beta=NS(messages=NS(stream=stream))))
    with pytest.raises(LLMError, match='disallowed model family'):
        llm.structured(Conversation('system'), schema={}, effort='medium')
    assert len(calls) == 1
    assert llm.usage_payload()['calls'][0]['input_tokens'] == 10


@pytest.mark.parametrize('model', ['claude-sonnet-5', 'claude-sonnet-4-6', 'claude-haiku-4-5'])
def test_snapshot_prompt_rejects_unsupported_model_before_dispatch(model):
    llm = LLM(model, client=NS())
    conv = Conversation.from_snapshot('role', {'facts': {}}, {'task': 'analyze'})
    with pytest.raises(LLMRequestBlocked, match='5.5'):
        llm.structured(conv, schema={}, effort='medium')
    assert llm.requests_attempted == 0


def test_sdk_snapshot_prefix_survives_tool_turns_retries_and_role_changes(tmp_path):
    """Exercise actual SDK serialization/stream parsing and durable settlement, offline."""
    import anthropic
    import httpx2
    from bullbear.anthropic_budget import WorkerSpendLedger

    captured = []

    def handle(request):
        captured.append(json.loads(request.content))
        tool_turn = len(captured) == 1
        write, read = (512, 0) if tool_turn else (0, 512)
        block = ({'type': 'tool_use', 'id': 'tool_local', 'name': 'read_fact', 'input': {}}
                 if tool_turn else {'type': 'text', 'text': ''})
        delta = ({'type': 'input_json_delta', 'partial_json': '{}'}
                 if tool_turn else {'type': 'text_delta', 'text': '{}'})
        events = [
            {'type': 'message_start', 'message': {
                'id': 'msg_local', 'type': 'message', 'role': 'assistant', 'model': 'claude-sonnet-5-5',
                'content': [], 'stop_reason': None, 'stop_sequence': None,
                'usage': {'input_tokens': 10, 'output_tokens': 0,
                          'cache_creation_input_tokens': write, 'cache_read_input_tokens': read,
                          'cache_creation': {'ephemeral_5m_input_tokens': write, 'ephemeral_1h_input_tokens': 0}},
            }},
            {'type': 'content_block_start', 'index': 0, 'content_block': block},
            {'type': 'content_block_delta', 'index': 0, 'delta': delta},
            {'type': 'content_block_stop', 'index': 0},
            {'type': 'message_delta', 'delta': {
                'stop_reason': 'tool_use' if tool_turn else 'end_turn', 'stop_sequence': None,
            }, 'usage': {'output_tokens': 2}},
            {'type': 'message_stop'},
        ]
        body = ''.join(f"event: {event['type']}\ndata: {json.dumps(event)}\n\n" for event in events)
        return httpx2.Response(200, headers={'content-type': 'text/event-stream'}, content=body)

    ledger = WorkerSpendLedger(tmp_path / 'cache.sqlite3', 'offline-test', '3')
    definitions = [{'name': 'read_fact', 'description': 'Read the frozen fact',
                    'input_schema': {'type': 'object', 'properties': {}, 'additionalProperties': False}}]
    with httpx2.Client(transport=httpx2.MockTransport(handle)) as http:
        client = anthropic.Anthropic(api_key='local-test', base_url='https://example.test',
                                     http_client=http, max_retries=0)
        llm = LLM('claude-sonnet-5-5', client=client, budget=ledger)
        conv = Conversation.from_snapshot('bull persona', {'ticker': '000000', 'facts': {'PX.CLOSE': 399}},
                                          {'round': 'opening', 'assigned_outlook': 'BUY'})
        assert llm.structured(conv, schema={}, effort='medium', tools=definitions,
                              tool_handler=lambda *_: '{"value":399}') == {}
        conv.messages.append({'role': 'user', 'content': 'Please revise the explanation.'})
        assert llm.structured(conv, schema={}, effort='medium', tools=definitions) == {}
        # Different dictionary insertion order must not change the serialized prefix.
        bear = Conversation.from_snapshot('bear persona', {'facts': {'PX.CLOSE': 399}, 'ticker': '000000'},
                                          {'round': 'closing', 'assigned_outlook': 'SELL'})
        assert llm.structured(bear, schema={}, effort='medium', tools=definitions) == {}

    first = captured[0]
    assert len(captured) == 4 and all('system' not in request for request in captured)
    assert [message['role'] for message in first['messages']] == ['user', 'user', 'system']
    prefix = first['messages'][0]
    assert prefix['content'][0]['cache_control'] == {'type': 'ephemeral', 'ttl': '5m'}
    assert all(request['messages'][0] == prefix for request in captured)
    assert all(request['messages'][:3] == first['messages'] for request in captured[:3])
    assert captured[1]['messages'][3]['content'][0]['type'] == 'tool_use'
    assert captured[1]['messages'][4]['content'][0]['type'] == 'tool_result'
    assert captured[2]['messages'][-1]['content'] == 'Please revise the explanation.'
    assert captured[3]['messages'][-1] == {'role': 'system', 'content': 'bear persona'}
    assert all(sum(message['role'] == 'system' for message in request['messages']) == 1 for request in captured)
    assert ledger.summary()['known_cost_usd'] == pytest.approx(.0015936)
    assert not ledger.summary()['halted'] and ledger.summary()['unconfirmed_requests'] == 0
    assert llm.usage.cache_creation_input_tokens == 512 and llm.usage.cache_read_input_tokens == 1536
