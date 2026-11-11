from concurrent.futures import ThreadPoolExecutor
from types import SimpleNamespace as NS
import sqlite3

import pytest

from bullbear.anthropic_budget import (
    BudgetDenied, BudgetUsageError, LEGACY_PRICE_HASH, PREVIOUS_PRICE_HASH, PRICE_HASH, WEB_FETCH_PRICE_HASH,
    WorkerSpendLedger, read_summary, usage_cost,
)


def request(**changes):
    return {'model': 'claude-sonnet-5-5', 'max_tokens': 16000, 'messages': [], 'system': 'test',
            'service_tier': 'standard_only', 'inference_geo': 'global', **changes}


def cached_request(**control):
    return request(messages=[{'role': 'user', 'content': [
        {'type': 'text', 'text': 'shared snapshot',
         'cache_control': {'type': 'ephemeral', **control}},
    ]}])


def response(model='claude-sonnet-5-5', **usage):
    return NS(model=model, usage=NS(**{'input_tokens': 100, 'output_tokens': 20,
                                     'cache_read_input_tokens': 0, 'cache_creation_input_tokens': 0, **usage}))


def ledger(tmp_path, limit='3'):
    return WorkerSpendLedger(tmp_path/'budget.sqlite3', 'test-approved', limit)


def test_settlement_and_restart_keep_known_spend(tmp_path):
    first = ledger(tmp_path)
    ident = first.reserve(request(), scope='debate:moderator')
    assert first.summary()['accounted_upper_usd'] == 2.16
    first.settle(ident, response(cache_read_input_tokens=30))
    reopened = ledger(tmp_path)
    assert reopened.summary()['known_cost_usd'] == .000403
    assert reopened.summary()['unconfirmed_requests'] == 0
    assert reopened.recover_interrupted() == 0
    with pytest.raises(BudgetUsageError):
        reopened.settle(ident, response())


def test_public_cost_is_run_scoped_and_unknown_is_not_zero(tmp_path):
    spend = ledger(tmp_path, '5')
    a = spend.reserve(request(), scope='a:debater')
    spend.settle(a, response(input_tokens=100))
    b = spend.reserve(request(), scope='b:moderator')
    assert spend.cost_for_scopes({'a:debater'}) == .0004
    assert spend.cost_for_scopes({'b:moderator'}) is None
    spend.settle(b, response(input_tokens=200))
    assert spend.cost_for_scopes({'b:moderator'}) == .0006
    assert spend.cost_for_scopes({'a:debater', 'b:moderator'}) == .001


def test_concurrent_reservations_cannot_overcommit(tmp_path):
    ledger(tmp_path)
    def reserve(_):
        try:
            return ledger(tmp_path).reserve(request(), scope='parallel')
        except BudgetDenied:
            return None
    with ThreadPoolExecutor(max_workers=8) as pool:
        accepted = list(pool.map(reserve, range(16)))
    assert sum(x is not None for x in accepted) == 1
    assert ledger(tmp_path).summary()['accounted_upper_usd'] == 2.16


def test_cache_miss_and_hit_settle_separately_and_survive_restart(tmp_path):
    spend = ledger(tmp_path)
    cold = spend.reserve(cached_request(ttl='5m'), scope='bull')
    assert spend.summary()['accounted_upper_usd'] == 2.66
    # A second cold parallel request must still reserve writes, not assume a hit.
    with pytest.raises(BudgetDenied):
        spend.reserve(cached_request(), scope='bear-before-cache-ready')
    spend.settle(cold, response(cache_creation_input_tokens=1000, cache_creation={
        'ephemeral_5m_input_tokens': 1000, 'ephemeral_1h_input_tokens': 0,
    }))
    warm = spend.reserve(cached_request(), scope='bear')
    spend.settle(warm, response(cache_read_input_tokens=1000))
    reopened = ledger(tmp_path)
    assert reopened.cost_for_scopes({'bull'}) == .0029
    assert reopened.cost_for_scopes({'bear'}) == .0005
    assert reopened.summary()['known_cost_usd'] == .0034
    assert reopened.summary()['unconfirmed_requests'] == 0


@pytest.mark.parametrize('prior_hash', [LEGACY_PRICE_HASH, PREVIOUS_PRICE_HASH, WEB_FETCH_PRICE_HASH])
def test_legacy_policy_migration_preserves_spend_reservations_and_halt(tmp_path, prior_hash):
    spend = ledger(tmp_path, '5')
    done = spend.reserve(request(), scope='settled')
    spend.settle(done, response())
    unknown = spend.reserve(request(), scope='unknown')
    spend.reserve(request(), scope='interrupted')
    spend.unknown(unknown, 'TimeoutError')
    with spend._db() as db:
        db.execute('UPDATE authorization SET price_hash=?', (prior_hash,))
        requests_before = db.execute('SELECT * FROM requests ORDER BY id').fetchall()
    before = spend.summary()
    reopened = ledger(tmp_path, '5')
    assert reopened.summary() == {**before, 'price_hash': PRICE_HASH}
    with reopened._db() as db:
        assert db.execute('SELECT * FROM requests ORDER BY id').fetchall() == requests_before
    with pytest.raises(BudgetDenied):
        reopened.reserve(cached_request(), scope='still-halted')


def test_unknown_policy_hash_cannot_be_migrated(tmp_path):
    spend = ledger(tmp_path)
    with spend._db() as db:
        db.execute("UPDATE authorization SET price_hash='unrecognized-policy'")
    with pytest.raises(BudgetDenied, match='cannot be reset'):
        ledger(tmp_path)
    assert read_summary(tmp_path/'budget.sqlite3')['price_hash'] == 'unrecognized-policy'


def test_unknown_and_interrupted_calls_cannot_be_released_by_restart(tmp_path):
    first = ledger(tmp_path)
    ident = first.reserve(request(), scope='before-crash')
    reopened = ledger(tmp_path)
    assert reopened.recover_interrupted() == 1
    report = reopened.summary()
    assert report['halted'] and report['unconfirmed_requests'] == 1
    assert report['reserved_unconfirmed_usd'] == 2.16
    assert report['known_cost_usd'] == 0
    reopened.cancel_before_dispatch(ident)  # Cannot release a recovered unknown call.
    with pytest.raises(BudgetDenied):
        reopened.reserve(request(), scope='after-crash')
    assert reopened.summary() == report


@pytest.mark.parametrize('name,limit', [('changed', '3'), ('test-approved', '4')])
def test_changed_authorization_cannot_reset_existing_ledger(tmp_path, name, limit):
    ledger(tmp_path)
    with pytest.raises(BudgetDenied, match='cannot be reset'):
        WorkerSpendLedger(tmp_path/'budget.sqlite3', name, limit)


@pytest.mark.parametrize('changes', [
    {'model': 'claude-opus-5-5'}, {'max_tokens': 16001}, {'max_tokens': True},
    {'service_tier': 'auto'}, {'inference_geo': 'us'}, {'speed': 'fast'},
    {'tools': [{'type': 'web_fetch_20250910', 'name': 'web_fetch'}]},
    {'tools': [{'type': 'web_search_20250305', 'name': 'web_search'}]},
    {'cache_control': {'type': 'ephemeral'}},  # Automatic caching is outside this explicit-prefix policy.
    {'messages': [{'role': 'user', 'content': [{'type': 'image', 'source': {}}]}]},
])
def test_unbudgeted_options_are_rejected_without_reservation(tmp_path, changes):
    spend = ledger(tmp_path)
    with pytest.raises(BudgetDenied):
        spend.reserve({**request(), **changes}, scope='rejected')
    assert spend.summary()['requests'] == 0


@pytest.mark.parametrize('control', [
    None, {}, 'ephemeral', {'type': 'persistent'}, {'type': 'ephemeral', 'ttl': '1h'},
    {'type': 'ephemeral', 'ttl': None}, {'type': 'ephemeral', 'scope': 'global'},
])
def test_unbudgeted_cache_options_are_rejected_before_reservation(tmp_path, control):
    payload = cached_request()
    payload['messages'][0]['content'][0]['cache_control'] = control
    spend = ledger(tmp_path)
    with pytest.raises(BudgetDenied):
        spend.reserve(payload, scope='invalid-cache')
    assert spend.summary()['requests'] == 0


@pytest.mark.parametrize('changes', [
    {'input_tokens': None}, {'input_tokens': -1}, {'input_tokens': True},
    {'cache_creation_input_tokens': 1}, {'inference_geo': 'us'}, {'service_tier': 'priority'},
    {'server_tool_use': {'web_search_requests': 1}},
])
def test_unpriced_usage_halts_and_retains_reservation(tmp_path, changes):
    spend = ledger(tmp_path)
    ident = spend.reserve(request(), scope='invalid-usage')
    with pytest.raises(BudgetUsageError):
        spend.settle(ident, response(**changes))
    report = spend.summary()
    assert report['halted'] and report['reserved_unconfirmed_usd'] == 2.16


@pytest.mark.parametrize('creation', [
    None, {}, {'ephemeral_5m_input_tokens': 9},
    {'ephemeral_5m_input_tokens': 10, 'ephemeral_1h_input_tokens': 1},
    {'ephemeral_5m_input_tokens': 0, 'ephemeral_1h_input_tokens': 10},
    {'ephemeral_5m_input_tokens': True}, {'ephemeral_5m_input_tokens': -1},
    {'ephemeral_5m_input_tokens': 10, 'unknown_duration_input_tokens': 0},
])
def test_unpriced_cache_usage_retains_full_write_reservation(tmp_path, creation):
    spend = ledger(tmp_path)
    ident = spend.reserve(cached_request(), scope='invalid-cache-usage')
    with pytest.raises(BudgetUsageError):
        spend.settle(ident, response(cache_creation_input_tokens=10, cache_creation=creation))
    report = spend.summary()
    assert report['halted'] and report['reserved_unconfirmed_usd'] == 2.66


def test_context_limit_includes_written_cache_tokens(tmp_path):
    spend = ledger(tmp_path)
    ident = spend.reserve(cached_request(), scope='over-context')
    with pytest.raises(BudgetUsageError, match='exceeded'):
        spend.settle(ident, response(input_tokens=1_000_000, cache_creation_input_tokens=1,
            cache_creation={'ephemeral_5m_input_tokens': 1, 'ephemeral_1h_input_tokens': 0}))
    report = spend.summary()
    assert report['halted'] and report['known_cost_usd'] == 2.0002025


def test_output_overrun_records_actual_and_halts(tmp_path):
    spend = ledger(tmp_path)
    ident = spend.reserve(request(), scope='overrun')
    with pytest.raises(BudgetUsageError):
        spend.settle(ident, response(output_tokens=16001))
    report = spend.summary()
    assert report['halted'] and report['known_cost_usd'] > 0


def test_observer_failure_before_transport_can_release_only_that_reservation(tmp_path):
    spend = ledger(tmp_path)
    ident = spend.reserve(request(), scope='not-dispatched')
    spend.cancel_before_dispatch(ident)
    assert spend.summary()['accounted_upper_usd'] == 0
    ident2 = spend.reserve(request(), scope='unknown')
    spend.unknown(ident2, 'TimeoutError')
    spend.cancel_before_dispatch(ident2)
    assert spend.summary()['reserved_unconfirmed_usd'] == 2.16


def test_haiku_long_context_price_uses_cached_tokens_in_threshold():
    assert usage_cost('claude-haiku-5-5', {'input_tokens': 100000, 'output_tokens': 10}) == 10005000
    assert usage_cost('claude-haiku-5-5', {'input_tokens': 100000, 'output_tokens': 10,
                                        'cache_read_input_tokens': 1}) == 50025050
    assert usage_cost('claude-haiku-5-5', {'input_tokens': 99999, 'output_tokens': 10,
        'cache_creation_input_tokens': 1, 'cache_creation': {'ephemeral_5m_input_tokens': 1}}) == 10005025
    assert usage_cost('claude-haiku-5-5', {'input_tokens': 100000, 'output_tokens': 10,
        'cache_creation_input_tokens': 1, 'cache_creation': {'ephemeral_5m_input_tokens': 1}}) == 50025625


def test_schema_property_named_type_is_not_a_media_block(tmp_path):
    spend = ledger(tmp_path)
    ident = spend.reserve(request(output_config={'format': {'type': 'json_schema', 'schema': {
        'type': 'object', 'properties': {'type': {'type': 'string'}}}}}), scope='schema')
    assert ident and spend.summary()['requests'] == 1


def test_summary_does_not_create_a_missing_database(tmp_path):
    with pytest.raises(sqlite3.OperationalError):
        read_summary(tmp_path/'missing.sqlite3')
    assert not (tmp_path/'missing.sqlite3').exists()


class FakeStream:
    def __init__(self, *, fail=False, tool=False):
        self.fail, self.tool = fail, tool
    def __enter__(self):
        if self.fail:
            raise TimeoutError('private error must not be stored')
        return self
    def __exit__(self, *args):
        pass
    def __iter__(self):
        return iter([])
    def get_final_message(self):
        msg = response()
        msg.stop_reason = 'tool_use' if self.tool else 'end_turn'
        msg.content = ([NS(type='tool_use', id='t1', name='local', input={})] if self.tool
                       else [NS(type='text', text='{}')])
        return msg


def fake_client(calls, **options):
    def stream(**kwargs):
        calls.append(kwargs)
        return FakeStream(**options)
    return NS(max_retries=0, beta=NS(messages=NS(stream=stream)), close=lambda: None)


def test_llm_reserves_before_transport_and_keeps_known_usage_on_block(tmp_path):
    from bullbear.llm import LLM, Conversation, LLMRequestBlocked
    calls = []
    spend = ledger(tmp_path, '2.16')
    llm = LLM('claude-sonnet-5-5', client=fake_client(calls, tool=True), budget=spend, budget_scope='run:role')
    with pytest.raises(LLMRequestBlocked):
        llm.structured(Conversation('test'), schema={}, effort='medium', tool_handler=lambda *_: 'result')
    assert len(calls) == 1 and llm.usage_complete
    assert llm.usage_payload()['calls'][0]['input_tokens'] == 100
    assert spend.summary()['known_cost_usd'] == .0004
    assert spend.summary()['unconfirmed_requests'] == 0
    assert calls[0]['service_tier'] == 'standard_only' and calls[0]['inference_geo'] == 'global'


def test_llm_timeout_retains_reservation_and_stops_future_requests(tmp_path):
    from bullbear.llm import LLM, Conversation
    calls = []
    spend = ledger(tmp_path)
    llm = LLM('claude-sonnet-5-5', client=fake_client(calls, fail=True), budget=spend)
    with pytest.raises(TimeoutError):
        llm.structured(Conversation('test'), schema={}, effort='medium')
    assert not llm.usage_complete
    with pytest.raises(BudgetDenied):
        llm.structured(Conversation('test'), schema={}, effort='medium')
    assert len(calls) == 1 and spend.summary()['reserved_unconfirmed_usd'] == 2.16
    with spend._db() as db:
        assert db.execute('SELECT error_type FROM requests').fetchone()[0] == 'TimeoutError'


def test_sdk_retry_configuration_cannot_bypass_per_request_reservation(tmp_path):
    from bullbear.llm import LLM
    client = fake_client([])
    client.max_retries = 2
    with pytest.raises(ValueError, match='hidden SDK retries'):
        LLM('claude-sonnet-5-5', client=client, budget=ledger(tmp_path))


def test_observer_failure_before_network_releases_reservation(tmp_path):
    from bullbear.llm import LLM, Conversation
    calls = []
    spend = ledger(tmp_path)
    llm = LLM('claude-sonnet-5-5', client=fake_client(calls), budget=spend)
    def broken(_):
        raise OSError('audit write failed')
    llm.request_observer = broken
    with pytest.raises(OSError):
        llm.structured(Conversation('test'), schema={}, effort='medium')
    assert not calls and spend.summary()['accounted_upper_usd'] == 0


def test_external_predispatch_guard_does_not_mark_provider_usage_unknown():
    from bullbear.llm import LLM, Conversation, LLMRequestBlocked
    records = []
    def blocked(**_):
        raise LLMRequestBlocked('local budget')
    llm = LLM('claude-sonnet-5-5', client=NS(beta=NS(messages=NS(stream=blocked))))
    llm.request_observer = records.append
    with pytest.raises(LLMRequestBlocked):
        llm.structured(Conversation('test'), schema={}, effort='medium')
    assert llm.usage_complete and records[-1]['status'] == 'not_dispatched'


def test_process_crash_keeps_reserved_money(tmp_path):
    import subprocess, sys, json
    path = tmp_path/'budget.sqlite3'
    code = """import json,os,sys
from bullbear.anthropic_budget import WorkerSpendLedger
ledger=WorkerSpendLedger(sys.argv[1],'test-approved','3')
ledger.reserve(json.loads(sys.argv[2]),scope='crashed')
os._exit(7)
"""
    proc = subprocess.run([sys.executable, '-c', code, str(path), json.dumps(request())], capture_output=True)
    assert proc.returncode == 7
    recovered = ledger(tmp_path)
    assert recovered.recover_interrupted() == 1
    assert recovered.summary()['reserved_unconfirmed_usd'] == 2.16
    with pytest.raises(BudgetDenied):
        recovered.reserve(request(), scope='new-process')
