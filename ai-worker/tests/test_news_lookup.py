from copy import deepcopy
from csv import DictReader
from io import StringIO
import json
from types import SimpleNamespace as NS

from anthropic.types.beta import BetaMessage
import pytest

from bullbear.anthropic_budget import WorkerSpendLedger
from bullbear.context_ids import RequestIds
from bullbear.data.article_body import ArticleUnavailable
from bullbear.events import EventLog
from bullbear.graph_runtime import GraphRuntime
from bullbear.llm import Conversation, LLM
from bullbear.news_lookup import NewsLookup
from bullbear.snapshot import build_snapshot
from bullbear.tools import DEBATE_TOOL_DEFINITIONS, SnapshotTools

from .fakes import FakeNews, FakeSource, NOW
from .graph_fakes import GraphLLM
from .prompt_helpers import initial_payload


MODEL = 'claude-sonnet-5-5'
BODY = '보유율 하락과 함께 11월 2~6일 순매도가 2.2조 원으로 집계됐다.'


def article_snapshot():
    snap = build_snapshot(FakeSource(), '000000', '가짜전자', now=NOW, news=FakeNews())
    article, = snap.by_category('news')
    return snap, article


def mock_fetch(monkeypatch, success):
    calls = []

    def fetch(url):
        calls.append(url)
        if not success:
            raise ArticleUnavailable('http_error')
        return BODY

    monkeypatch.setattr('bullbear.news_lookup.fetch_article_body', fetch)
    return calls


@pytest.mark.parametrize('success', [True, False])
def test_budgeted_llm_reads_body_by_article_alias_or_falls_back_to_summary(tmp_path, monkeypatch, success):
    snap, article = article_snapshot()
    fetches = mock_fetch(monkeypatch, success)
    events = []
    news = NewsLookup(snap, enabled=True, require_summary_lookup=True,
                      record=lambda source_id, event: events.append((source_id, event)))
    ids = RequestIds(snap, [])
    alias = ids.fact_ids[article.id]
    assert news.issues([article.id])[0].code == 'news_source_unavailable'
    requests = []

    def stream(**kwargs):
        requests.append(deepcopy(kwargs))
        usage = {'input_tokens': 100, 'output_tokens': 20, 'cache_creation_input_tokens': 0,
                 'cache_read_input_tokens': 0}
        if len(requests) == 1:
            content = [
                {'type': 'tool_use', 'name': 'read_snapshot', 'id': 'toolu_summary',
                 'input': {'kind': 'facts', 'args': [alias]}},
                {'type': 'tool_use', 'name': 'get_news_body', 'id': 'toolu_too_early', 'input': {'source_id': alias}},
            ]
            reason = 'tool_use'
        elif len(requests) == 2:
            assert not fetches
            early_reply = json.loads(kwargs['messages'][-1]['content'][1]['content'])
            assert early_reply['status'] == 'summary' and early_reply['reason'] == 'summary_first'
            content = [{'type': 'tool_use', 'name': 'get_news_body', 'id': 'toolu_article', 'input': {'source_id': alias}}]
            reason = 'tool_use'
        else:
            assert len(requests) == 3
            content, reason = [{'type': 'text', 'text': '{}'}], 'end_turn'
        message = BetaMessage.model_validate({'id': 'msg_local', 'model': MODEL, 'role': 'assistant',
            'type': 'message', 'stop_reason': reason, 'content': content, 'usage': usage})

        class Stream:
            def __enter__(self): return self
            def __exit__(self, *args): pass
            def __iter__(self): return iter(())
            def get_final_message(self): return message

        return Stream()

    client = NS(max_retries=0, beta=NS(messages=NS(stream=stream)))
    ledger = WorkerSpendLedger(tmp_path / 'ledger.sqlite3', 'fetch-test', '3.00')
    llm = LLM(MODEL, client=client, budget=ledger)
    conv = Conversation('role', [{'role': 'user', 'content': '기사 근거를 확인하세요.'}])
    tools = SnapshotTools(snap)
    assert llm.structured(conv, schema={}, effort='medium', tools=DEBATE_TOOL_DEFINITIONS,
        tool_handler=ids.wrap_tool_handler(lambda name, args: news.handle_tool(tools, name, args)),
        on_event=news.observe) == {}
    assert {tool['name'] for tool in requests[0]['tools']} == {'get_news_body', 'read_snapshot'}
    reply, = requests[2]['messages'][-1]['content']
    delivered = json.loads(reply['content'])
    assert delivered['source_id'] == alias and 'url' not in delivered
    assert fetches == [article.url]
    result = news.results[article.id]
    assert result['status'] == ('body' if success else 'summary')
    assert result.get('text') == (BODY if success else None)
    assert not news.issues([article.id])
    assert events[0][0] == article.id and BODY not in str(events)
    assert delivered['text' if success else 'summary'] == (BODY if success else article.note)
    assert ledger.summary()['known_cost_usd'] == .0012
    assert not ledger.summary()['halted']


@pytest.mark.parametrize('success', [True, False])
def test_new_debate_passes_fetch_outcome_to_review_and_later_rounds(tmp_path, monkeypatch, success):
    snap, article = article_snapshot()
    fetches = mock_fetch(monkeypatch, success)

    class NewsDebater(GraphLLM):
        def structured(self, conv, **kwargs):
            raw = super().structured(conv, **kwargs)
            if self.count <= 2:
                raw['evidence'][0].update(source_id=article.id, value=None)
                raw['argument'] = '기사로 확인한 수급을 전망 근거로 삼되 불확실해요 [E1].'
            if self.count <= 2:
                alias = conv.context_ids.fact_ids[article.id]
                if self.count == 1:
                    kwargs['tool_handler']('read_snapshot', {'kind': 'facts', 'args': [alias]})
                kwargs['tool_handler']('get_news_body', {'source_id': alias})
            return raw

    bull = NewsDebater(snap, model=MODEL)
    bear, reviewer, moderator = (GraphLLM(snap, model=MODEL) for _ in range(3))
    log = EventLog(tmp_path / 'debate.jsonl')
    run = GraphRuntime(snap, debate_id='fetch', bull=bull, bear=bear, moderator=moderator,
                       log=log, statement_reviewers={'bull': reviewer}, news_web_fetch=True)
    assert run.run()['graph_status'] == 'accepted'
    assert fetches == [article.url]
    records = EventLog.read(log.path)
    assert not any(event['type'] == 'statement_rejected' for event in records)
    assert bull.count == 3
    assert 'news_lookup_results' not in initial_payload(bear.calls[0][0])
    observed = initial_payload(bear.calls[1][0])['news_lookup_results'][article.id]
    assert observed['status'] == ('body' if success else 'summary')
    assert observed.get('text') == (BODY if success else None)
    review_input = initial_payload(reviewer.calls[0][0])
    review_facts = {row['source_id']: row for row in DictReader(StringIO(review_input['facts_csv']))}
    assert review_facts[article.id]['note'] == article.note
    assert review_input['news_lookup_results'][article.id] == observed
    assert initial_payload(moderator.calls[0][0])['news_lookup_results'][article.id] == observed
    assert BODY not in log.path.read_text(encoding='utf-8')


@pytest.mark.parametrize('tool_name, arguments', [
    ('get_facts', lambda article: {'source_ids': [article.id]}),
    ('get_snapshot_news', lambda article: {'scope': article.news_scope or 'company', 'offset': 0}),
    ('read_snapshot', lambda article: {'kind': 'facts', 'args': [article.id]}),
    ('read_snapshot', lambda article: {'kind': 'news', 'args': [article.news_scope or 'company', '0']}),
])
def test_title_only_news_requires_reading_the_returned_summary(tool_name, arguments):
    snap, article = article_snapshot()
    news = NewsLookup(snap, require_summary_lookup=True)
    assert news.issues([article.id])[0].code == 'news_source_unavailable'
    assert '제목만으로' in news.issues([article.id])[0].message
    news.handle_tool(SnapshotTools(snap), tool_name, arguments(article))
    assert not news.issues([article.id])
    assert news.results[article.id]['summary_read'] is True
    assert news.results[article.id]['summary'] == article.note
    # Future agents receive the actual summary along with the read marker.
    later = NewsLookup(snap, previous=news.results, require_summary_lookup=True)
    assert not later.issues([article.id])
    assert later.results[article.id]['summary'] == article.note


def test_news_catalog_and_omitted_or_inaccurate_summary_do_not_count_as_read():
    snap, article = article_snapshot()
    news = NewsLookup(snap, require_summary_lookup=True)
    news.handle_tool(SnapshotTools(snap), 'get_fact_catalog', {'category': 'news', 'offset': 0})
    assert news.issues([article.id])
    for output in [
        {'facts_csv': 'source_id,note\n', 'remaining_source_ids': [article.id]},
        {'facts_csv': f'source_id,note\n{article.id},다른 요약\n'},
        {'facts_csv': f'source_id,label\n{article.id},제목만\n'},
    ]:
        news.handle_tool(lambda *_: json.dumps(output), 'get_facts', {'source_ids': [article.id]})
        assert news.issues([article.id])
        assert article.id not in news.results


@pytest.mark.parametrize('success', [True, False])
def test_body_tool_returns_success_or_summary_and_audits_without_prose(monkeypatch, success):
    snap, article = article_snapshot()
    fetches = mock_fetch(monkeypatch, success)
    audit = []
    news = NewsLookup(snap, enabled=True, require_summary_lookup=True,
                      record=lambda key, result: audit.append((key, result)))
    assert 'read_snapshot' in news.issues([article.id])[0].message
    tools = SnapshotTools(snap)
    summary = json.loads(news.handle_tool(tools, 'get_news_body', {'source_id': article.id}))
    assert summary['status'] == 'summary' and summary['summary'] == article.note
    assert not fetches and not news.issues([article.id])
    fetched = json.loads(news.handle_tool(tools, 'get_news_body', {'source_id': article.id}))
    assert 'url' not in fetched
    assert not news.issues([article.id])
    if not success:
        assert news.results[article.id]['body_attempted'] is True
        assert news.results[article.id]['summary_read'] is True
        assert news.results[article.id]['summary'] == article.note
    assert all('summary' not in event and 'text' not in event for _, event in audit)


def test_previous_fetch_failure_requires_summary_to_be_delivered_before_fallback():
    snap, article = article_snapshot()
    news = NewsLookup(snap, enabled=True, require_summary_lookup=True,
                      previous={article.id: {'status': 'summary', 'reason': 'url_not_accessible'}})
    issue, = news.issues([article.id])
    assert 'read_snapshot' in issue.message
    news.handle_tool(SnapshotTools(snap), 'read_snapshot', {'kind': 'facts', 'args': [article.id]})
    assert not news.issues([article.id])
    assert news.results[article.id]['reason'] == 'url_not_accessible'


def test_reading_summary_alone_is_sufficient_with_body_fetch_enabled(monkeypatch):
    snap, article = article_snapshot()
    fetches = mock_fetch(monkeypatch, True)
    news = NewsLookup(snap, enabled=True, require_summary_lookup=True)
    news.handle_tool(SnapshotTools(snap), 'get_facts', {'source_ids': [article.id]})
    assert not news.issues([article.id])
    assert not fetches


def test_legacy_full_summary_inputs_remain_compatible():
    snap, article = article_snapshot()
    news = NewsLookup(snap)
    assert not news.issues([article.id])
    assert news.results == {}


def test_body_tool_validates_article_id_and_falls_back_without_network_when_disabled(monkeypatch):
    snap, article = article_snapshot()
    fetches = mock_fetch(monkeypatch, True)
    tools = SnapshotTools(snap)
    enabled = NewsLookup(snap, enabled=True)
    for arguments in ({'source_id': article.url}, {'source_id': 'PX.CLOSE'},
                      {'source_id': article.id, 'url': article.url}):
        with pytest.raises(ValueError):
            enabled.handle_tool(tools, 'get_news_body', arguments)
    disabled = NewsLookup(snap)
    result = json.loads(disabled.handle_tool(tools, 'get_news_body', {'source_id': article.id}))
    assert result == {'source_id': article.id, 'status': 'summary',
                      'summary_read': True, 'summary': article.note}
    assert not fetches
