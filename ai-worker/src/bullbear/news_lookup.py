"""Connect a Sonnet web fetch result to an article in the current snapshot."""
import json
from csv import DictReader
from hashlib import sha256
from io import StringIO
from urllib.parse import urlsplit

from .verifier import Issue

WEB_FETCH_URL_SOURCES = {
    'user_input': {'type': 'none'}, 'server_tool_results': {'type': 'none'},
    'client_tool_results': {'type': 'only', 'tools': [{'type': 'tool_reference', 'name': 'get_new_url'}]},
}


def _fetchable_article(fact, cutoff):
    if not fact.url or not fact.published_at or fact.published_at.utcoffset() is None:
        return False
    if fact.published_at > cutoff:
        return False
    try:
        url = urlsplit(fact.url)
    except ValueError:
        return False
    return (url.scheme in {'http', 'https'} and bool(url.hostname)
            and url.username is None and url.password is None)


class NewsLookup:
    def __init__(self, snapshot, *, enabled=False, previous=None, record=None, require_summary_lookup=False):
        self.snapshot = snapshot
        self.results = dict(previous or {})
        self.require_summary_lookup = require_summary_lookup
        self.record = record
        self.pending = {}
        self.issued = set()
        self.urls = {}
        if enabled:
            for fact in snapshot.by_category('news'):
                if _fetchable_article(fact, snapshot.information_cutoff):
                    self.urls[fact.url] = fact.id
        # Anthropic rejects the entire request if an allowed domain blocks its crawler.
        # Scope by the URL-returning tool instead, so a blocked article fails individually.
        self.tool = {
            'type': 'web_fetch_20250910', 'name': 'web_fetch',
            'max_uses': 1, 'max_content_tokens': 3000, 'url_sources': WEB_FETCH_URL_SOURCES,
        } if self.urls else None

    def tools(self, local_tools):
        return [*local_tools, self.tool] if self.tool else local_tools

    def handle_tool(self, tools, name, arguments):
        result = tools(name, arguments)
        summary_table = name in {'get_facts', 'get_snapshot_news'} or (
            name == 'read_snapshot' and arguments.get('kind') in {'facts', 'news'})
        item = json.loads(result) if summary_table or name == 'get_new_url' else None
        if self.require_summary_lookup and item is not None:
            if summary_table:
                # Only complete returned rows count, never merely requested or paginated IDs.
                for row in DictReader(StringIO(item.get('facts_csv', ''))):
                    self._read_summary(row.get('source_id'), row.get('note'))
            elif name == 'get_new_url':
                fact = self.snapshot.facts.get(item.get('source_id'))
                if fact is not None and fact.note and fact.note.strip():
                    item['summary'] = fact.note
                    self._read_summary(fact.id, fact.note)
                    result = json.dumps(item, ensure_ascii=False, separators=(',', ':'))
        if self.tool and name == 'get_new_url':
            url = item.get('url')
            if url and url not in self.urls:
                return json.dumps({'source_id': item['source_id'], 'note': '본문을 조회할 수 없는 주소입니다',
                                   **({'summary': item['summary']} if 'summary' in item else {})},
                                  ensure_ascii=False)
            if url:
                self.issued.add(url)
        return result

    def _read_summary(self, source_id, summary):
        fact = self.snapshot.facts.get(source_id)
        if (fact is None or fact.category != 'news' or not isinstance(summary, str)
                or not summary.strip() or summary != fact.note):
            return
        previous = self.results.get(source_id, {})
        if previous.get('status') == 'body':
            return
        self.results[source_id] = {**previous, 'status': 'summary', 'summary_read': True, 'summary': summary}
        if self.record is not None and not previous.get('summary_read'):
            self.record(source_id, {'status': 'summary', 'summary_read': True,
                                   'sha256': sha256(summary.encode('utf-8')).hexdigest()})

    def observe(self, event, block):
        if event == 'server_tool_use' and block.get('name') == 'web_fetch':
            url = block['input'].get('url')
            if isinstance(url, str) and url in self.issued:
                self.pending[block['id']] = url
        if event != 'web_fetch_tool_result':
            return
        url = self.pending.pop(block['tool_use_id'], None)
        if url is None:
            return
        source_id = self.urls[url]
        content = block['content']
        document = (content.get('content') or {}).get('source') or {}
        text = document.get('data') if document.get('type') == 'text' else None
        if content.get('type') == 'web_fetch_result' and content.get('url') == url and text and text.strip():
            result = {'status': 'body', 'text': text, 'retrieved_at': content.get('retrieved_at')}
            audit = {'status': 'body', 'retrieved_at': result['retrieved_at'],
                     'sha256': sha256(text.encode('utf-8')).hexdigest()}
        else:
            result = {'status': 'summary', 'reason': content.get('error_code', 'body_unavailable')}
            if self.require_summary_lookup:
                result['body_attempted'] = True
                previous = self.results.get(source_id, {})
                if previous.get('summary_read'):
                    result.update(summary_read=True, summary=previous['summary'])
            audit = {key: value for key, value in result.items() if key != 'summary'}
        # A failed lookup must not erase a successful earlier result.
        if self.results.get(source_id, {}).get('status') != 'body':
            self.results[source_id] = result
        if self.record is not None:
            self.record(source_id, audit)

    def issues(self, source_ids):
        issues = []
        for key in dict.fromkeys(source_ids):
            fact = self.snapshot.facts.get(key)
            if fact is None or fact.category != 'news':
                continue
            result = self.results.get(key)
            if result is not None and result.get('status') == 'body':
                continue
            attempted = bool(result and (result.get('body_attempted') or result.get('reason')))
            if fact.url in self.urls and (result is None or self.require_summary_lookup and not attempted):
                message = f'{key}: get_new_url로 주소를 확인하고 web_fetch로 본문을 조회한 뒤 인용하세요.'
            elif not fact.note or not fact.note.strip():
                message = f'{key}: 인용할 본문과 저장된 요약문이 없습니다. 다른 근거를 쓰세요.'
            elif self.require_summary_lookup and not (result and result.get('summary_read')
                                                      and result.get('summary') == fact.note):
                message = f'{key}: 제목만으로 인용할 수 없습니다. read_snapshot(kind="facts", args=[source_id])로 저장된 요약문을 확인하세요.'
            else:
                continue
            issues.append(Issue(severity='error', code='news_source_unavailable', message=message))
        return issues
