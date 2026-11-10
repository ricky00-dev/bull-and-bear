from types import SimpleNamespace as NS
import pytest

from bullbear.llm import Conversation, LLM, LLMError
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
