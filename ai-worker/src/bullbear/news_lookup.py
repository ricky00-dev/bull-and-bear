"""Scope article tools and evidence to the current snapshot and debate turn."""
import json
from hashlib import sha256
from time import monotonic

from .news_extraction import ArticleExtractor, Extraction, FETCH_TIMEOUT
from .verifier import Issue

FETCH_NEWS_TOOL = {
    "name": "fetch_news",
    "description": "스냅샷의 기사 Fact ID로 본문을 조회한다. 성공한 경우 content가 본문이다. URL은 입력할 수 없다.",
    "input_schema": {
        "type": "object",
        "properties": {"article_id": {"type": "string", "description": "스냅샷에 표시된 뉴스 source_id"}},
        "required": ["article_id"],
        "additionalProperties": False,
    },
}

# A registered alternative can help with unavailable pages or unusable HTML.
# Explicit access restrictions and rate limits terminate the lookup.
_FALLBACK_ERRORS = {
    "INVALID_URL", "NOT_FOUND", "DNS_FAILED", "NETWORK_ERROR", "NO_ARTICLE_BODY",
    "BODY_TOO_LONG", "UNSUPPORTED_CONTENT_TYPE", "UNSUPPORTED_ENCODING", "RESPONSE_TOO_LARGE",
}


class NewsLookup:
    def __init__(self, snapshot, *, extractor: ArticleExtractor | None = None, previous=None, record=None):
        self.snapshot = snapshot
        self.extractor = extractor
        self.results = dict(previous or {})
        self.record = record
        self.attempted = False
        self.urls = {}
        if extractor is not None:
            cutoff = snapshot.information_cutoff
            for fact in snapshot.by_category("news"):
                published = fact.published_at
                if (published is None or published.utcoffset() is None or cutoff.utcoffset() is None
                        or published > cutoff):
                    continue
                alternate = snapshot.news_alternate_urls.get(fact.id)
                urls = tuple(dict.fromkeys(url for url in (fact.url, alternate) if url))
                if urls:
                    self.urls[fact.id] = urls

    def tools(self, local_tools):
        return [*local_tools, FETCH_NEWS_TOOL] if self.urls else local_tools

    def handle_tool(self, tools, name, arguments):
        if name != FETCH_NEWS_TOOL["name"]:
            return tools(name, arguments)
        article_id = arguments.get("article_id")
        if set(arguments) != {"article_id"} or not isinstance(article_id, str):
            return json.dumps(self._result(None, Extraction("UNSUPPORTED", error_code="INVALID_INPUT")))
        return json.dumps(self._fetch(article_id), ensure_ascii=False)

    def _result(self, article_id, extraction: Extraction):
        fact = self.snapshot.facts.get(article_id)
        return {
            "article_id": article_id,
            "status": extraction.status,
            "url": extraction.url,
            "title": fact.label if fact is not None and fact.category == "news" else None,
            "content": extraction.content,
            "extraction_method": "trafilatura",
            "verified_full_text": extraction.status == "SUCCESS",
            "error_code": extraction.error_code,
        }

    def _fetch(self, article_id):
        if article_id in self.results:
            return self.results[article_id]
        urls = self.urls.get(article_id)
        if not urls:
            return self._result(article_id, Extraction("UNSUPPORTED", error_code="ARTICLE_UNAVAILABLE"))
        if self.attempted:
            outcome = Extraction("FETCH_FAILED", error_code="LOOKUP_LIMIT")
        else:
            self.attempted = True
            deadline = monotonic() + FETCH_TIMEOUT
            outcome = self.extractor.fetch(urls[0], deadline=deadline)
            if len(urls) > 1 and outcome.error_code in _FALLBACK_ERRORS and monotonic() < deadline:
                outcome = self.extractor.fetch(urls[1], deadline=deadline)
        result = self.results[article_id] = self._result(article_id, outcome)
        if self.record is not None:
            audit = {key: result[key] for key in ("status", "error_code", "extraction_method", "verified_full_text")}
            if outcome.content is not None:
                audit["sha256"] = sha256(outcome.content.encode("utf-8")).hexdigest()
            self.record(article_id, audit)
        return result

    def issues(self, source_ids):
        issues = []
        for key in dict.fromkeys(source_ids):
            fact = self.snapshot.facts.get(key)
            if fact is None or fact.category != "news":
                continue
            result = self.results.get(key)
            if result is None and key in self.urls:
                message = f"{key}: fetch_news에 article_id를 넣어 기사 본문을 확인한 뒤 인용하세요."
            elif (result is None or not result["verified_full_text"]) and not (fact.note or "").strip():
                message = f"{key}: 인용할 본문과 저장된 요약문이 없습니다. 다른 근거를 쓰세요."
            else:
                continue
            issues.append(Issue(severity="error", code="news_source_unavailable", message=message))
        return issues
