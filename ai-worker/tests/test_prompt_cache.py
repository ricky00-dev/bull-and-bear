"""The prompt cache only pays off when later requests repeat the same prefix."""
import json
import threading
import time
from types import SimpleNamespace as NS

import pytest

from bullbear import graph_runtime, prompts
from bullbear.events import EventLog
from bullbear.graph_runtime import GraphRuntime
from bullbear.llm import LLM, Conversation
from bullbear.schemas import Side
from bullbear.snapshot import build_snapshot
from .fakes import NOW, FakeSource
from .graph_fakes import GraphLLM


class Stream:
    """Server-sent events in API order; ``generating`` runs once generation has begun."""
    def __init__(self, text, generating=lambda: None, timeline=None):
        self.text, self.generating, self.timeline = text, generating, timeline

    def __enter__(self):
        return self

    def __exit__(self, *args):
        pass

    def __iter__(self):
        for event in ('message_start', 'content_block_start'):
            if self.timeline is not None:
                self.timeline.append(event)
            yield NS(type=event)
        self.generating()
        yield NS(type='text', text='')

    def get_final_message(self):
        return NS(model='claude-sonnet-5-5', stop_reason='end_turn', content=[NS(type='text', text=self.text)],
                  usage=NS(input_tokens=1, output_tokens=1, cache_read_input_tokens=0, cache_creation_input_tokens=0))


def run_debate(tmp_path, before_send=lambda role, sent: None, generating=lambda role: None, sent=None):
    """Run the real request assembly and return every (role, request) sent."""
    snapshot = build_snapshot(FakeSource(), '000000', '가짜전자', now=NOW)
    sent = [] if sent is None else sent

    def llm(role):
        fake = GraphLLM(snapshot)

        def stream(**params):
            before_send(role, sent)
            # Copy the list: the client appends the reply to it after sending.
            sent.append((role, {**params, 'messages': list(params['messages'])}))
            system = next(m['content'] for m in params['messages'] if m['role'] == 'system')
            raw = fake.structured(Conversation(system, params['messages'], system_in_messages=True),
                                  schema=params['output_config']['format']['schema'])
            return Stream(json.dumps(raw, ensure_ascii=False), lambda: generating(role))

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
    debaters = [(role, params) for role, params in sent if role in ('bull', 'bear')]
    assert [role for role, _ in sent].count('moderator') == 1 and len(debaters) == 6
    first = debaters[0][1]
    cache = {'type': 'ephemeral', 'ttl': '5m'}
    # Shared debater rules: cached separately so other snapshots' debates reuse them too.
    assert [block['cache_control'] for block in first['system']] == [cache]
    assert first['system'][0]['text'] == prompts.DEBATER_COMMON_SYSTEM
    assert first['messages'][0]['content'][0]['cache_control'] == cache
    assert {tool['name'] for tool in first['tools']} >= {'get_statement_details'}
    for role, params in debaters:
        assert params['model'] == first['model'] and params['system'] == first['system']
        assert params['tools'] == first['tools']
        assert params['output_config'] == first['output_config']
        assert params['messages'][0] == first['messages'][0]
        # Only the role, the one place the two sides differ, follows the request uncached.
        assert params['messages'][-1] == {'role': 'system', 'content': prompts.debater_role(Side(role))}
        assert len(params['messages'][-1]['content']) < 200


def test_bear_opening_waits_until_bull_response_starts(tmp_path):
    """Concurrent requests cannot read each other's cache, so Bear must not race Bull."""
    def before_send(role, sent):
        if role == 'bull' and not sent:
            time.sleep(0.3)  # Bull's request has not started streaming yet.
            assert not any(earlier == 'bear' for earlier, _ in sent)

    sent = run_debate(tmp_path, before_send)
    assert [role for role, _ in sent][:2] == ['bull', 'bear']


def test_stream_started_waits_for_generation_not_headers():
    """Response headers and message_start can precede prefill; a cache write is
    readable once the response has begun generating."""
    timeline = []
    client = NS(beta=NS(messages=NS(stream=lambda **params: Stream('{}', timeline=timeline))))
    LLM('claude-sonnet-5-5', client=client).structured(
        Conversation('역할', [{'role': 'user', 'content': '질문'}]), schema={'type': 'object'}, effort='low',
        on_event=lambda event, payload: timeline.append(event) if event == 'stream_started' else None)
    assert timeline == ['message_start', 'content_block_start', 'stream_started']


def test_bear_opening_starts_while_bull_is_still_generating(tmp_path):
    bear_sent = threading.Event()

    def before_send(role, sent):
        if role == 'bear':
            bear_sent.set()

    def generating(role):
        if role == 'bull' and not bear_sent.is_set():
            assert bear_sent.wait(timeout=5)  # Bear must not wait for Bull's whole turn.

    sent = run_debate(tmp_path, before_send, generating)
    assert [role for role, _ in sent][:2] == ['bull', 'bear']


def test_bear_sends_nothing_when_bull_opening_fails(tmp_path):
    class BullDown(Exception):
        pass

    def before_send(role, sent):
        if role == 'bull':
            raise BullDown()

    sent, started = [], time.monotonic()
    with pytest.raises(BullDown):  # The real cause surfaces, not Bear's skip.
        run_debate(tmp_path, before_send, sent=sent)
    assert sent == [] and time.monotonic() - started < 5
    waits = [e for e in EventLog.read(tmp_path / 'cache.jsonl') if e['type'] == 'opening_wait']
    assert [(e['side'], e['outcome']) for e in waits] == [('bear', 'bull_failed')]


def test_bear_wait_timeout_is_recorded(tmp_path, monkeypatch):
    monkeypatch.setattr(graph_runtime, '_PREFIX_WAIT_SECONDS', 0.05)

    def before_send(role, sent):
        if role == 'bull' and not sent:
            time.sleep(0.5)  # Bull's request is slow to start.

    sent = run_debate(tmp_path, before_send)
    assert [role for role, _ in sent][:2] == ['bear', 'bull']
    waits = [e for e in EventLog.read(tmp_path / 'cache.jsonl') if e['type'] == 'opening_wait']
    assert [(e['side'], e['outcome']) for e in waits] == [('bear', 'timeout')]
