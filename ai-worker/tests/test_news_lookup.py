from copy import deepcopy
from datetime import timedelta
import json
from types import SimpleNamespace as NS

from anthropic.types.beta import BetaMessage
import httpx
import pytest

from bullbear.anthropic_budget import WorkerSpendLedger
from bullbear.events import EventLog
from bullbear.graph_runtime import GraphRuntime
from bullbear.llm import Conversation, LLM
from bullbear.news_lookup import NewsLookup
from bullbear.snapshot import Snapshot, build_snapshot
from bullbear.tools import SnapshotTools, TOOL_DEFINITIONS

from .fakes import FakeNews, FakeSource, NOW
from .graph_fakes import GraphLLM
from .prompt_helpers import initial_payload
from .test_news_extraction import BODY, URL, html_response, make_extractor, public_dns


MODEL = "claude-sonnet-5-5"


def article_snapshot():
    snap = build_snapshot(FakeSource(), "000000", "가짜전자", now=NOW, news=FakeNews())
    article, = snap.by_category("news")
    article.url = URL
    return snap, article


@pytest.mark.parametrize("status,expected", [(404, "SUCCESS"), (403, "FETCH_FAILED")])
def test_registered_alternate_is_used_only_when_access_policy_permits(public_dns, status, expected):
    snap, article = article_snapshot()
    snap.news_alternate_urls[article.id] = "https://mirror.example/article"
    snap = Snapshot.model_validate_json(snap.model_dump_json())
    hosts = []

    def handler(request):
        if request.url.path == "/robots.txt":
            return httpx.Response(404)
        host = request.headers["host"]
        hosts.append(host)
        return httpx.Response(status) if host == "publisher.example" else html_response()

    news = NewsLookup(snap, extractor=make_extractor(handler))
    result = json.loads(news.handle_tool(SnapshotTools(snap), "fetch_news", {"article_id": article.id}))
    assert result["status"] == expected and result["title"] == article.label
    assert result["verified_full_text"] is (status == 404)
    assert result["url"] == ("https://mirror.example/article" if status == 404 else URL)
    assert hosts == (["publisher.example", "mirror.example"] if status == 404 else ["publisher.example"])


def test_only_snapshot_article_ids_available_at_cutoff_can_fetch(public_dns):
    snap, article = article_snapshot()
    article.published_at = snap.information_cutoff + timedelta(seconds=1)
    news = NewsLookup(snap, extractor=make_extractor(lambda _: pytest.fail("unexpected network request")))
    tools = SnapshotTools(snap)
    assert news.tools(TOOL_DEFINITIONS) == TOOL_DEFINITIONS
    for args, code in [({"article_id": article.id}, "ARTICLE_UNAVAILABLE"),
                       ({"article_id": URL}, "ARTICLE_UNAVAILABLE"),
                       ({"url": URL}, "INVALID_INPUT"),
                       ({"article_id": article.id, "url": URL}, "INVALID_INPUT")]:
        result = json.loads(news.handle_tool(tools, "fetch_news", args))
        assert result["status"] == "UNSUPPORTED" and result["error_code"] == code
        assert result["content"] is None and result["verified_full_text"] is False


def test_limits_new_articles_per_turn_but_reuses_previous_and_allows_summary(public_dns):
    snap, first = article_snapshot()
    second = first.model_copy(update={"id": "NEWS.second", "url": "https://publisher.example/other"})
    snap.facts[second.id] = second

    def handler(request):
        assert request.url.path != "/other"
        return httpx.Response(404) if request.url.path == "/robots.txt" else html_response()

    news = NewsLookup(snap, extractor=make_extractor(handler))
    tools = SnapshotTools(snap)
    assert news.issues([first.id, second.id])
    first_call = news.handle_tool(tools, "fetch_news", {"article_id": first.id})
    assert json.loads(first_call)["status"] == "SUCCESS"
    assert json.loads(news.handle_tool(tools, "fetch_news", {"article_id": second.id}))["error_code"] == "LOOKUP_LIMIT"
    assert news.handle_tool(tools, "fetch_news", {"article_id": first.id}) == first_call
    assert not news.issues([first.id, second.id])
    second.note = None
    assert news.issues([second.id])[0].code == "news_source_unavailable"


@pytest.mark.parametrize("success", [True, False])
def test_budgeted_sonnet_continues_after_worker_tool_result(tmp_path, public_dns, success):
    snap, article = article_snapshot()

    def handler(request):
        if request.url.path == "/robots.txt":
            return httpx.Response(404)
        return html_response() if success else httpx.Response(403)

    news = NewsLookup(snap, extractor=make_extractor(handler))
    requests = []

    def stream(**kwargs):
        requests.append(deepcopy(kwargs))
        usage = {"input_tokens": 100, "output_tokens": 20, "cache_creation_input_tokens": 0,
                 "cache_read_input_tokens": 0}
        if len(requests) == 1:
            content = [{"type": "tool_use", "name": "fetch_news", "id": "toolu_news",
                        "input": {"article_id": article.id}}]
            reason = "tool_use"
        else:
            assert len(requests) == 2
            content, reason = [{"type": "text", "text": "{}"}], "end_turn"
        message = BetaMessage.model_validate({"id": "msg_local", "model": MODEL, "role": "assistant",
            "type": "message", "stop_reason": reason, "content": content, "usage": usage})

        class Stream:
            def __enter__(self): return self
            def __exit__(self, *args): pass
            def __iter__(self): return iter(())
            def get_final_message(self): return message

        return Stream()

    client = NS(max_retries=0, beta=NS(messages=NS(stream=stream)))
    ledger = WorkerSpendLedger(tmp_path / "ledger.sqlite3", "fetch-test", "3.00")
    llm = LLM(MODEL, client=client, budget=ledger)
    conv = Conversation.from_snapshot("role", {"snapshot_id": snap.snapshot_id},
                                      {"task": "기사 근거를 확인하세요."}, common_system="공통 분석 규칙")
    tools = SnapshotTools(snap)
    assert llm.structured(conv, schema={}, effort="medium", tools=news.tools(TOOL_DEFINITIONS),
        tool_handler=lambda name, args: news.handle_tool(tools, name, args)) == {}
    assert requests[0]["tools"][-1]["name"] == "fetch_news"
    assert requests[0]["tools"][-1]["strict"] is True
    marker = {"type": "ephemeral", "ttl": "5m"}
    for request in requests:
        assert request["tools"][-1]["cache_control"] == marker
        assert request["system"][0]["cache_control"] == marker
        assert request["messages"][0]["content"][0]["cache_control"] == marker
    assert not any(tool.get("type", "custom") != "custom" for tool in requests[0]["tools"])
    result_block, = requests[1]["messages"][-1]["content"]
    assert result_block["type"] == "tool_result" and result_block["tool_use_id"] == "toolu_news"
    result = json.loads(result_block["content"])
    assert set(result) == {"article_id", "status", "url", "title", "content",
                           "extraction_method", "verified_full_text", "error_code"}
    assert result["article_id"] == article.id and result["url"] == URL
    assert result["extraction_method"] == "trafilatura" and result["verified_full_text"] is success
    assert result["status"] == ("SUCCESS" if success else "FETCH_FAILED")
    assert result["error_code"] == (None if success else "ACCESS_DENIED")
    assert BODY in result["content"] if success else result["content"] is None
    assert ledger.summary()["known_cost_usd"] == .0008
    assert not ledger.summary()["halted"]


@pytest.mark.parametrize("success", [True, False])
def test_parallel_bull_bear_lookup_and_evidence_review(tmp_path, public_dns, success):
    snap, article = article_snapshot()
    request_paths = []

    def handler(request):
        request_paths.append(request.url.path)
        if request.url.path == "/robots.txt":
            return httpx.Response(404)
        return html_response() if success else httpx.Response(403)

    class NewsDebater(GraphLLM):
        def structured(self, conv, **kwargs):
            raw = super().structured(conv, **kwargs)
            if initial_payload(conv)["round"] == "opening":
                raw["evidence"][0].update(source_id=article.id, value=None)
                raw["argument"] = ("기사 본문에서 확인한 수급은 전망의 한 조건이에요 [E1]."
                                   if self.count == 2 else
                                   "기사 요약에서 전한 내용을 전망의 한 조건으로 봐요 [E1].")
                if self.count == 2:
                    result = json.loads(kwargs["tool_handler"]("fetch_news", {"article_id": article.id}))
                    assert result["verified_full_text"] is success
            return raw

    bull, bear = (NewsDebater(snap, model=MODEL) for _ in range(2))
    reviewer, moderator = (GraphLLM(snap, model=MODEL) for _ in range(2))
    log = EventLog(tmp_path / "debate.jsonl")
    run = GraphRuntime(snap, debate_id="fetch", bull=bull, bear=bear, moderator=moderator,
                       log=log, statement_reviewers={"bull": reviewer}, news_fetch_enabled=True)
    run.news_extractor = make_extractor(handler)
    assert run.run()["graph_status"] == "accepted"
    assert request_paths == ["/robots.txt", "/article"]
    records = EventLog.read(log.path)
    rejections = [event for event in records if event["type"] == "statement_rejected"]
    assert sum(any(issue["code"] == "news_source_unavailable" for issue in e["issues"]) for e in rejections) == 2
    assert sum(any(issue["code"] == "news_body_unverified" for issue in e["issues"]) for e in rejections) == (0 if success else 2)
    assert "news_lookup_results" not in initial_payload(bear.calls[0][0])
    next_round = next(initial_payload(conv) for conv, _ in bear.calls if initial_payload(conv)["round"] == "rebuttal")
    observed = next_round["news_lookup_results"][article.id]
    assert observed["verified_full_text"] is success
    assert BODY in observed["content"] if success else observed["content"] is None
    fact = initial_payload(reviewer.calls[0][0])["facts"][article.id]
    assert fact["news_lookup_result"] == observed and fact["note"] == article.note
    assert initial_payload(moderator.calls[0][0])["news_lookup_results"][article.id] == observed
    assert BODY not in log.path.read_text(encoding="utf-8")
