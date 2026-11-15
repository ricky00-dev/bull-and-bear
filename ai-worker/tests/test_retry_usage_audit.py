import json
from types import SimpleNamespace as NS

import pytest
from fastapi.testclient import TestClient

from bullbear.audit import AuditedLLM
from bullbear.llm import Conversation, LLM
from bullbear.server.service import LiveRunner
from bullbear.server.store import Store
from .test_server import setup, app_for, start, completed, parse_sse, AUTH
from .test_run_audit import make_audit


class RetryClient:
    def __init__(self, broken=True):
        self.requests = 0
        self.broken = broken
        self.beta = NS(messages=self)
    def stream(self, **kwargs):
        self.requests += 1
        owner = self
        class Stream:
            def __enter__(self):
                return self
            def __exit__(self, *args):
                return False
            def __iter__(self):
                if owner.broken and owner.requests == 1:
                    raise ValueError('private synthetic SDK parse failure')
                return iter(())
            def get_final_message(self):
                return NS(model='claude-haiku-5-5', stop_reason='end_turn',
                          usage=NS(input_tokens=10, output_tokens=5),
                          content=[NS(type='text', text='{}')])
        return Stream()
    def close(self):
        pass


def test_request_record_is_durable_before_provider_and_each_retry(setup):
    audit = make_audit(setup[0])
    provider = RetryClient()
    original = provider.stream
    def stream(**kwargs):
        manifest = json.loads(audit.path.read_text(encoding='utf-8'))
        requests = manifest['llm_calls'][0]['requests']
        assert len(requests) == provider.requests + 1
        assert requests[-1]['status'] == 'running'
        if provider.requests:
            assert requests[0]['status'] == 'unknown' and manifest['usage_complete'] is False
        return original(**kwargs)
    provider.stream = stream
    llm = LLM('claude-haiku-5-5', client=provider)
    AuditedLLM(llm, audit, 'debater').structured(Conversation('fixture'), schema={}, effort='medium')
    assert llm.usage_complete is False
    assert audit.data['usage']['calls'][0]['input_tokens'] == 10
    assert audit.data['role_usage']['debater'] == audit.data['usage']


def test_audit_request_write_failure_prevents_provider_call(setup, monkeypatch):
    audit = make_audit(setup[0])
    provider = RetryClient(False)
    llm = LLM('claude-haiku-5-5', client=provider)
    original = audit._write
    def fail_request_write():
        if any(call.get('requests') for call in audit.data['llm_calls']):
            raise OSError('synthetic disk failure')
        original()
    monkeypatch.setattr(audit, '_write', fail_request_write)
    with pytest.raises(OSError):
        AuditedLLM(llm, audit, 'debater').structured(Conversation('fixture'), schema={}, effort='medium')
    assert provider.requests == 0 and llm.request_observer is None


@pytest.mark.parametrize('broken', [True, False])
def test_retry_success_keeps_uncertainty_but_normal_usage_is_public(setup, broken):
    settings, _ = setup
    provider = RetryClient(broken)
    class Runner(LiveRunner):
        def run(self, snapshot, debate_id, max_extra_rounds, emit):
            llm = LLM('claude-haiku-5-5', client=provider)
            self.clients.append(llm)
            audited = AuditedLLM(llm, self.audit, 'debater')
            for _ in range(2):
                audited.structured(Conversation('fixture'), schema={}, effort='medium')
            return {'debate_id': debate_id}
    with TestClient(app_for(setup, runner_factory=lambda: Runner(settings))) as c:
        d = start(c).json()['debate_id']
        detail = completed(c, d)
        assert detail['status'] == 'completed'
        assert ('usage' in detail) is not broken
        terminal = parse_sse(c.get(f'/debates/{d}/events', headers=AUTH).text)[-1][2]
        assert ('usage' in terminal) is not broken
        manifest_path = settings.data_dir / 'audits' / d / 'manifest.json'
        manifest = json.loads(manifest_path.read_text(encoding='utf-8'))
        assert manifest['usage_complete'] is not broken
        assert manifest['usage']['calls'][0]['input_tokens'] == 20
        assert all(call['status'] == 'success' for call in manifest['llm_calls'])
        if not broken:
            assert detail['usage']['calls'][0]['input_tokens'] == 20
        else:
            assert [r['status'] for call in manifest['llm_calls'] for r in call['requests']] == ['unknown', 'received', 'received']
        assert 'private synthetic' not in json.dumps(manifest)
    # Crash window after audit completion but before terminal SQLite commit.
    raw = manifest_path.read_bytes()
    import sqlite3
    with sqlite3.connect(settings.data_dir / 'http' / 'worker.sqlite3') as db:
        db.execute("DELETE FROM events WHERE debate_id=? AND type='debate_completed'", (d,))
        db.execute("UPDATE debates SET status='running' WHERE id=?", (d,))
    store = Store(settings.data_dir / 'http')
    try:
        recovery = json.loads(store.db.execute('SELECT data FROM recoveries WHERE debate_id=?', (d,)).fetchone()[0])
        assert recovery['usage_complete'] is False
        assert recovery['known_usage']['calls'][0]['input_tokens'] == 20
        assert 'usage' not in json.loads(store.events(d)[-1]['data'])
        assert manifest_path.read_bytes() == raw
    finally:
        store.close()
