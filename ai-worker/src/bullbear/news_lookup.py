"""Resolve an article ID in the current snapshot and read its body or saved summary."""
import json
from csv import DictReader
from hashlib import sha256
from io import StringIO
from datetime import datetime

from .data.article_body import ArticleUnavailable, fetch_article_body
from .snapshot import KST
from .verifier import Issue

# Retained for the budget ledger's legacy hosted-tool validation.
WEB_FETCH_URL_SOURCES = {
    'user_input': {'type': 'none'}, 'server_tool_results': {'type': 'none'},
    'client_tool_results': {'type': 'only', 'tools': [{'type': 'tool_reference', 'name': 'get_new_url'}]},
}
_MAX_BODY_CHARS = 3000
_MAX_FETCH_ATTEMPTS = 2


def _fetchable_article(fact, cutoff):
    return bool(fact.url and fact.published_at and fact.published_at.utcoffset() is not None
                and fact.published_at <= cutoff)


class NewsLookup:
    def __init__(self, snapshot, *, enabled=False, previous=None, record=None, require_summary_lookup=False):
        self.snapshot = snapshot
        self.enabled = enabled
        self.results = dict(previous or {})
        self.require_summary_lookup = require_summary_lookup
        self.record = record
        self.fetch_attempts = 0
        self._summaries_before_batch: set[str] | None = None

    def observe(self, event, _payload):
        if event == 'tool_batch_start':
            # Parallel tool calls cannot rely on results the model has not received yet.
            self._summaries_before_batch = {key for key, value in self.results.items() if value.get('summary_read')}

    def handle_tool(self, tools, name, arguments):
        if name == 'get_news_body':
            return self._get_body(arguments)
        result = tools(name, arguments)
        summary_table = name in {'get_facts', 'get_snapshot_news'} or (
            name == 'read_snapshot' and arguments.get('kind') in {'facts', 'news'})
        if (self.require_summary_lookup or self.enabled) and summary_table:
            for row in DictReader(StringIO(json.loads(result).get('facts_csv', ''))):
                self._read_summary(row.get('source_id'), row.get('note'))
        return result

    def _get_body(self, arguments):
        if (not isinstance(arguments, dict) or set(arguments) != {'source_id'}
                or not isinstance(arguments['source_id'], str)):
            raise ValueError('스냅샷의 뉴스 source_id 하나를 입력하세요')
        fact = self.snapshot.facts.get(arguments['source_id'])
        if fact is None or fact.category != 'news':
            raise ValueError('스냅샷에 해당 뉴스 Fact가 없습니다')
        previous = self.results.get(fact.id, {})
        result = previous
        if previous.get('status') != 'body':
            summary_ready = previous.get('summary_read') and (
                self._summaries_before_batch is None or fact.id in self._summaries_before_batch)
            if self.enabled and fact.note and fact.note.strip() and not summary_ready:
                # A premature body call still gives the model the summary before any network request.
                self._read_summary(fact.id, fact.note)
                result = {**self.results[fact.id], 'reason': 'summary_first'}
                return json.dumps({'source_id': fact.id, **result}, ensure_ascii=False, separators=(',', ':'))
            result = self._read_body_or_summary(fact, previous)
            self._store(fact.id, result)
        return json.dumps({'source_id': fact.id, **result}, ensure_ascii=False, separators=(',', ':'))

    def _read_body_or_summary(self, fact, previous):
        reason = previous.get('reason')
        attempted = bool(previous.get('body_attempted'))
        if self.enabled and not reason:
            if not _fetchable_article(fact, self.snapshot.information_cutoff):
                reason = 'body_unavailable'
            elif self.fetch_attempts >= _MAX_FETCH_ATTEMPTS:
                reason = 'fetch_limit'
            else:
                self.fetch_attempts += 1
                attempted = True
                try:
                    text = fetch_article_body(fact.url)
                except ArticleUnavailable as exc:
                    reason = str(exc)
                else:
                    return {'status': 'body', 'text': text[:_MAX_BODY_CHARS],
                            'truncated': len(text) > _MAX_BODY_CHARS,
                            'retrieved_at': datetime.now(KST).isoformat()}
        result = ({'status': 'summary', 'summary_read': True, 'summary': fact.note}
                  if fact.note and fact.note.strip() else {'status': 'unavailable'})
        if reason:
            result.update(reason=reason, body_attempted=attempted)
        return result

    def _store(self, source_id, result):
        if self.results.get(source_id) == result:
            return
        self.results[source_id] = result
        if self.record is not None:
            audit = {key: value for key, value in result.items() if key not in {'summary', 'text'}}
            content = result.get('text') or result.get('summary')
            if content:
                audit['sha256'] = sha256(content.encode('utf-8')).hexdigest()
            self.record(source_id, audit)

    def _read_summary(self, source_id, summary):
        fact = self.snapshot.facts.get(source_id)
        if (fact is None or fact.category != 'news' or not isinstance(summary, str)
                or not summary.strip() or summary != fact.note):
            return
        previous = self.results.get(source_id, {})
        if previous.get('status') == 'body':
            return
        self._store(source_id, {**previous, 'status': 'summary', 'summary_read': True, 'summary': summary})

    def issues(self, source_ids):
        issues = []
        for key in dict.fromkeys(source_ids):
            fact = self.snapshot.facts.get(key)
            if fact is None or fact.category != 'news':
                continue
            result = self.results.get(key)
            if result is not None and result.get('status') == 'body':
                continue
            if not fact.note or not fact.note.strip():
                if self.enabled and _fetchable_article(fact, self.snapshot.information_cutoff) and not result:
                    message = f'{key}: 저장된 요약이 없습니다. 필요하면 get_news_body로 본문을 조회하세요.'
                else:
                    message = f'{key}: 인용할 본문과 저장된 요약문이 없습니다. 다른 근거를 쓰세요.'
            elif self.require_summary_lookup and not (result and result.get('summary_read')
                                                      and result.get('summary') == fact.note):
                message = f'{key}: 제목만으로 인용할 수 없습니다. read_snapshot(kind="facts", args=[source_id])로 저장된 요약문을 확인하세요.'
            else:
                continue
            issues.append(Issue(severity='error', code='news_source_unavailable', message=message))
        return issues
