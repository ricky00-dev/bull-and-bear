from copy import deepcopy
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
    conv = Conversation.from_snapshot('role', {'snapshot_id': snap.snapshot_id},
                                      {'task': '기사 근거를 확인하세요.'}, common_system='공통 분석 규칙')
    tools = SnapshotTools(snap)
    assert llm.structured(conv, schema={}, effort='medium', tools=news.tools(TOOL_DEFINITIONS),
        tool_handler=lambda name, args: news.handle_tool(tools, name, args), on_event=news.observe) == {}
    assert requests[0]['tools'][-1] == {
        **news.tool, 'cache_control': {'type': 'ephemeral', 'ttl': '5m'},
    }
    assert 'cache_control' not in news.tool
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
            if self.count == 2:
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
    rejected = next(event for event in records if event['type'] == 'statement_rejected')
    assert any(issue['code'] == 'news_source_unavailable' for issue in rejected['issues'])
    assert 'news_lookup_results' not in initial_payload(bear.calls[0][0])
    observed = initial_payload(bear.calls[1][0])['news_lookup_results'][article.id]
    assert observed['status'] == ('body' if success else 'summary')
    assert observed.get('text') == (BODY if success else None)
    fact = initial_payload(reviewer.calls[0][0])['facts'][article.id]
    assert fact['news_lookup_result'] == observed and fact['note'] == article.note
    assert initial_payload(moderator.calls[0][0])['news_lookup_results'][article.id] == observed
    assert BODY not in log.path.read_text(encoding='utf-8')
