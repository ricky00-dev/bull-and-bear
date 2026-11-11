from copy import deepcopy
from csv import DictReader
from io import StringIO
import json
from types import SimpleNamespace as NS

from anthropic.types.beta import BetaMessage
import pytest

from bullbear.anthropic_budget import WorkerSpendLedger
from bullbear.events import EventLog
from bullbear.graph_runtime import GraphRuntime
from bullbear.llm import Conversation, LLM
from bullbear.news_lookup import NewsLookup
from bullbear.snapshot import build_snapshot
from bullbear.tools import SnapshotTools, TOOL_DEFINITIONS

from .fakes import FakeNews, FakeSource, NOW
from .graph_fakes import GraphLLM
from .prompt_helpers import initial_payload


MODEL = 'claude-sonnet-5-5'
BODY = '보유율 하락과 함께 11월 2~6일 순매도가 2.2조 원으로 집계됐다.'


def article_snapshot():
    snap = build_snapshot(FakeSource(), '000000', '가짜전자', now=NOW, news=FakeNews())
    article, = snap.by_category('news')
    return snap, article


def fetch_blocks(url, success):
    request = {'type': 'server_tool_use', 'name': 'web_fetch', 'id': 'srvtoolu_fetch', 'input': {'url': url}}
    content = ({'type': 'web_fetch_result', 'url': url, 'retrieved_at': NOW.isoformat(),
                'content': {'type': 'document', 'title': '기사',
                            'source': {'type': 'text', 'media_type': 'text/plain', 'data': BODY}}}
               if success else {'type': 'web_fetch_tool_result_error', 'error_code': 'url_not_accessible'})
    return request, {'type': 'web_fetch_tool_result', 'tool_use_id': request['id'], 'content': content}


@pytest.mark.parametrize('success', [True, False])
@pytest.mark.parametrize('pause', [True, False])
def test_budgeted_sonnet_reads_body_or_falls_back_to_summary(tmp_path, success, pause):
    snap, article = article_snapshot()
    events = []
    news = NewsLookup(snap, enabled=True, record=lambda source_id, event: events.append((source_id, event)))
    assert news.issues([article.id])[0].code == 'news_source_unavailable'
    requests = []

    def stream(**kwargs):
        requests.append(deepcopy(kwargs))
        usage = {'input_tokens': 100, 'output_tokens': 20, 'cache_creation_input_tokens': 0,
                 'cache_read_input_tokens': 0}
        if len(requests) == 1:
            content = [{'type': 'tool_use', 'name': 'get_new_url', 'id': 'toolu_url', 'input': {'source_id': article.id}}]
            reason = 'tool_use'
        elif len(requests) == 2:
            request, result = fetch_blocks(article.url, success)
            content = [{'type': 'text', 'text': '기사 본문을 확인할게요.'}, request, result]
            reason = 'pause_turn' if pause else 'end_turn'
            if not pause:
                content.append({'type': 'text', 'text': '{}'})
            usage['server_tool_use'] = {'web_fetch_requests': 1, 'web_search_requests': 0}
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
    assert llm.structured(conv, schema={}, effort='medium', tools=news.tools(TOOL_DEFINITIONS),
        tool_handler=lambda name, args: news.handle_tool(tools, name, args), on_event=news.observe) == {}
    assert requests[0]['tools'][-1] == news.tool
    assert 'strict' not in news.tool and 'eager_input_streaming' not in news.tool
    assert 'allowed_domains' not in news.tool
    assert news.tool['url_sources']['client_tool_results']['tools'][0]['name'] == 'get_new_url'
    url_result, = requests[1]['messages'][-1]['content']
    assert json.loads(url_result['content']) == {'source_id': article.id, 'url': article.url}
    if pause:
        assert requests[2]['messages'][-1]['content'][-1].type == 'web_fetch_tool_result'
    result = news.results[article.id]
    assert result['status'] == ('body' if success else 'summary')
    assert result.get('text') == (BODY if success else None)
    assert not news.issues([article.id])
    assert events[0][0] == article.id and BODY not in str(events)
    assert ledger.summary()['known_cost_usd'] == (.0012 if pause else .0008)
    assert not ledger.summary()['halted']


@pytest.mark.parametrize('success', [True, False])
def test_new_debate_passes_fetch_outcome_to_review_and_later_rounds(tmp_path, success):
    snap, article = article_snapshot()

    class NewsDebater(GraphLLM):
        def structured(self, conv, **kwargs):
            raw = super().structured(conv, **kwargs)
            if self.count <= 2:
                raw['evidence'][0].update(source_id=article.id, value=None)
                raw['argument'] = '기사로 확인한 수급을 전망 근거로 삼되 불확실해요 [E1].'
            if self.count == 1:
                kwargs['tool_handler']('get_new_url', {'source_id': article.id})
                requested, fetched = fetch_blocks(article.url, success)
                kwargs['on_event'](requested['type'], requested)
                kwargs['on_event'](fetched['type'], fetched)
            return raw

    bull = NewsDebater(snap, model=MODEL)
    bear, reviewer, moderator = (GraphLLM(snap, model=MODEL) for _ in range(3))
    log = EventLog(tmp_path / 'debate.jsonl')
    run = GraphRuntime(snap, debate_id='fetch', bull=bull, bear=bear, moderator=moderator,
                       log=log, statement_reviewers={'bull': reviewer}, news_web_fetch=True)
    assert run.run()['graph_status'] == 'accepted'
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
def test_title_only_news_url_supplies_summary_but_still_requires_body_attempt(success):
    snap, article = article_snapshot()
    audit = []
    news = NewsLookup(snap, enabled=True, require_summary_lookup=True,
                      record=lambda key, result: audit.append((key, result)))
    fetched = json.loads(news.handle_tool(SnapshotTools(snap), 'get_new_url', {'source_id': article.id}))
    assert fetched['url'] == article.url and fetched['summary'] == article.note
    assert 'web_fetch' in news.issues([article.id])[0].message
    request, result = fetch_blocks(article.url, success)
    news.observe(request['type'], request)
    news.observe(result['type'], result)
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


def test_reading_summary_alone_does_not_bypass_enabled_body_fetch():
    snap, article = article_snapshot()
    news = NewsLookup(snap, enabled=True, require_summary_lookup=True)
    news.handle_tool(SnapshotTools(snap), 'get_facts', {'source_ids': [article.id]})
    assert 'web_fetch' in news.issues([article.id])[0].message


def test_legacy_full_summary_inputs_remain_compatible():
    snap, article = article_snapshot()
    news = NewsLookup(snap)
    assert not news.issues([article.id])
    assert news.results == {}
