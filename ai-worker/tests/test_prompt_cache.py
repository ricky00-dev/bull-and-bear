"""The prompt cache only pays off when later requests repeat the same prefix."""
import json
import time
from types import SimpleNamespace as NS

from bullbear.events import EventLog
from bullbear.graph_runtime import GraphRuntime
from bullbear.llm import LLM, Conversation
from bullbear.snapshot import build_snapshot
from .fakes import NOW, FakeSource
from .graph_fakes import GraphLLM


class Stream:
    def __init__(self, text):
        self.text = text

    def __enter__(self):
        return self

    def __exit__(self, *args):
        pass

    def __iter__(self):
        return iter([])

    def get_final_message(self):
        return NS(model='claude-sonnet-5-5', stop_reason='end_turn', content=[NS(type='text', text=self.text)],
                  usage=NS(input_tokens=1, output_tokens=1, cache_read_input_tokens=0, cache_creation_input_tokens=0))


def run_debate(tmp_path, before_send=lambda role, sent: None):
    """Run the real request assembly and return every (role, request) sent."""
    snapshot = build_snapshot(FakeSource(), '000000', '가짜전자', now=NOW)
    sent = []

    def llm(role):
        fake = GraphLLM(snapshot)

        def stream(**params):
            before_send(role, sent)
            sent.append((role, params))
            system = next(m['content'] for m in params['messages'] if m['role'] == 'system')
            raw = fake.structured(Conversation(system, params['messages'], system_in_messages=True),
                                  schema=params['output_config']['format']['schema'])
            return Stream(json.dumps(raw, ensure_ascii=False))

        return LLM('claude-sonnet-5-5', client=NS(beta=NS(messages=NS(stream=stream))))

    GraphRuntime(snapshot, debate_id='cache', bull=llm('bull'), bear=llm('bear'), moderator=llm('moderator'),
                 log=EventLog(tmp_path / 'cache.jsonl')).run()
    return sent


def test_every_debater_request_shares_one_cacheable_prefix(tmp_path):
    """Tools, the output schema and the snapshot block come first in every request.

    If any of them differs between rounds, each turn writes a new cache entry
    instead of reading the one the opening wrote.
    """
    sent = run_debate(tmp_path)
    debaters = [params for role, params in sent if role in ('bull', 'bear')]
    assert [role for role, _ in sent].count('moderator') == 1 and len(debaters) == 6
    first = debaters[0]
    cache = {'type': 'ephemeral', 'ttl': '5m'}
    # Shared debater rules: cached separately so other snapshots' debates reuse them too.
    assert [block['cache_control'] for block in first['system']] == [cache]
    assert first['messages'][0]['content'][0]['cache_control'] == cache
    assert len(first['messages'][-1]['content']) < 100  # Only the one-line role is uncached.
    assert {tool['name'] for tool in first['tools']} >= {'get_statement_details'}
    for params in debaters:
        assert params['model'] == first['model'] and params['system'] == first['system']
        assert params['tools'] == first['tools']
        assert params['output_config'] == first['output_config']
        assert params['messages'][0] == first['messages'][0]


def test_bear_opening_waits_until_bull_response_starts(tmp_path):
    """Concurrent requests cannot read each other's cache, so Bear must not race Bull."""
    def before_send(role, sent):
        if role == 'bull' and not sent:
            time.sleep(0.3)  # Bull's request has not started streaming yet.
            assert not any(earlier == 'bear' for earlier, _ in sent)

    sent = run_debate(tmp_path, before_send)
    assert [role for role, _ in sent][:2] == ['bull', 'bear']
