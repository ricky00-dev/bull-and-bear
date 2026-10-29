from types import SimpleNamespace as NS

from bullbear.llm import Conversation, LLM


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


def test_usage_tracks_actual_model_and_cache_writes_without_haiku_fallback():
    calls = []
    models = iter(['actual-model-a', 'actual-model-b', 'actual-model-a'])
    def stream(**kwargs):
        calls.append(kwargs)
        return Stream(next(models))
    llm = LLM('claude-haiku-5-5', client=NS(beta=NS(messages=NS(stream=stream))))
    for _ in range(3):
        llm.structured(Conversation('system'), schema={}, effort='medium')
    assert all('fallbacks' not in c and 'betas' not in c for c in calls)
    usage = {c['model']: c for c in llm.usage_payload()['calls']}
    assert usage['actual-model-a']['input_tokens'] == 20
    assert usage['actual-model-a']['cache_creation_input_tokens'] == 4
    assert usage['actual-model-b']['output_tokens'] == 5
