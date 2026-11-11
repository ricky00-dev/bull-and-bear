"""Optional durable budget for standard Anthropic worker requests.

One authorization per database, shared across roles/runs and process restarts.
Reserve the full context window at the highest tier, including 5-minute cache
writes when requested; never rely on a prompt token estimate. Unknown responses
retain their reservation and halt dispatch.
"""
from __future__ import annotations

import argparse
from contextlib import closing, contextmanager
from datetime import datetime, timezone
import hashlib
import json
from pathlib import Path
import re
import sqlite3
from uuid import uuid4

from .budget import amount_nano
from .llm import LLMError, LLMRequestBlocked
from .news_lookup import WEB_FETCH_URL_SOURCES

NANO = 1_000_000_000
PRICE_SOURCE = 'https://platform.claude.com/docs/en/about-claude/pricing'
POLICY = {
    'version': 'anthropic-worker-standard-2026-11-11-v3',
    'context': 1_000_000, 'max_output': 16000, 'haiku_threshold': 100000,
    'rates_nano': {'claude-haiku-5-5': [[100, 500, 10], [500, 2500, 50]],
                   'claude-sonnet-5-5': [[2000, 10000, 100], [2000, 10000, 100]]},
    'cache_writes': {'ttl': '5m', 'multiplier': [5, 4]},
    'hosted_tools': {'web_fetch_20250910': {'max_uses': 1, 'max_content_tokens': 3000}},
    'source': PRICE_SOURCE,
}
PRICE_HASH = hashlib.sha256(json.dumps(POLICY, sort_keys=True).encode()).hexdigest()
# Existing authorizations keep their prices, reservations, and settled costs.
PREVIOUS_PRICE_HASH = hashlib.sha256(json.dumps({
    **POLICY, 'version': 'anthropic-worker-standard-2026-11-10-v2', 'hosted_tools': False,
}, sort_keys=True).encode()).hexdigest()
LEGACY_PRICE_HASH = hashlib.sha256(json.dumps({
    **POLICY, 'version': 'anthropic-worker-standard-2026-11-02-v1', 'cache_writes': False,
    'hosted_tools': False,
}, sort_keys=True).encode()).hexdigest()


class BudgetDenied(LLMRequestBlocked):
    """Rejected before dispatch: no new billable request or unknown usage."""
    before_dispatch = True


class BudgetUsageError(LLMError):
    pass


def _now():
    return datetime.now(timezone.utc).isoformat()


def _check_content(value, *, allow_fetch=False, fetched_document=False):
    """Validate supported content and count explicit 5-minute cache markers."""
    if hasattr(value, 'model_dump'):
        value = value.model_dump(mode='json')
    markers = 0
    if isinstance(value, dict):
        kind = value.get('type')
        if isinstance(kind, str) and kind in {'image', 'document', 'audio', 'video'} and not (
                kind == 'document' and fetched_document):
            raise BudgetDenied('Only text inputs are budgeted')
        if 'cache_control' in value:
            control = value['cache_control']
            if (not isinstance(control, dict) or set(control) - {'type', 'ttl'}
                    or control.get('type') != 'ephemeral' or control.get('ttl', '5m') != '5m'):
                raise BudgetDenied('Only ephemeral 5-minute cache writes are budgeted')
            markers += 1
        for key, child in value.items():
            markers += _check_content(child, allow_fetch=allow_fetch,
                fetched_document=allow_fetch and key == 'content' and (
                    kind == 'web_fetch_tool_result' or (kind == 'web_fetch_result' and fetched_document)))
    elif isinstance(value, (list, tuple)):
        for child in value:
            markers += _check_content(child, allow_fetch=allow_fetch)
    return markers


def _cache_write_rate(input_rate):
    numerator, denominator = POLICY['cache_writes']['multiplier']
    return input_rate * numerator // denominator


def reservation(request):
    model, output = request.get('model'), request.get('max_tokens')
    if model not in POLICY['rates_nano']:
        raise BudgetDenied('Model has no authorized worker price')
    if type(output) is not int or not 1 <= output <= POLICY['max_output']:
        raise BudgetDenied('Invalid worker output allowance')
    allowed = {'model', 'max_tokens', 'system', 'messages', 'tools', 'output_config',
               'service_tier', 'inference_geo'}
    if set(request) - allowed:
        raise BudgetDenied('Request options are outside the worker budget policy')
    if request.get('service_tier') != 'standard_only' or request.get('inference_geo') != 'global':
        raise BudgetDenied('Worker budget requires standard global inference')
    tool_list = request.get('tools')
    hosted = [t for t in tool_list if t.get('type', 'custom') != 'custom'] if isinstance(tool_list, list) else []
    if hosted:
        tool = hosted[0]
        limits = POLICY['hosted_tools'].get(tool['type'])
        if (len(hosted) != 1 or model != 'claude-sonnet-5-5' or limits is None
                or tool.get('name') != 'web_fetch' or tool.get('url_sources') != WEB_FETCH_URL_SOURCES
                or any(type(tool.get(key)) is not int or not 1 <= tool[key] <= limit
                       for key, limit in limits.items())):
            raise BudgetDenied('Hosted tool is outside the budget policy')
    markers = _check_content(request, allow_fetch=bool(hosted))
    if markers > 4:
        raise BudgetDenied('At most four explicit cache breakpoints are supported')
    input_rate, output_rate, _ = POLICY['rates_nano'][model][1]
    if markers:
        # A cold cache can write the entire prefix. Never reserve at the read rate.
        input_rate = _cache_write_rate(input_rate)
    return POLICY['context'] * input_rate + output * output_rate


def usage_cost(model, data):
    if model not in POLICY['rates_nano']:
        raise BudgetUsageError('Unpriced provider model')
    i, o = data.get('input_tokens'), data.get('output_tokens')
    read, write = data.get('cache_read_input_tokens', 0), data.get('cache_creation_input_tokens', 0)
    if any(type(n) is not int or n < 0 for n in (i, o, read, write)):
        raise BudgetUsageError('Invalid token usage')
    creation = data.get('cache_creation')
    if creation is not None or write:
        if not isinstance(creation, dict) or set(creation) - {'ephemeral_5m_input_tokens', 'ephemeral_1h_input_tokens'}:
            raise BudgetUsageError('Missing or unpriced cache creation duration')
        five_min, one_hour = creation.get('ephemeral_5m_input_tokens', 0), creation.get('ephemeral_1h_input_tokens', 0)
        if (any(type(n) is not int or n < 0 for n in (five_min, one_hour))
                or one_hour or five_min != write):
            raise BudgetUsageError('Invalid or unpriced cache creation usage')
    if data.get('service_tier') not in (None, 'standard') or data.get('inference_geo') not in (None, 'global'):
        raise BudgetUsageError('Unpriced provider service tier or region')
    hosted = data.get('server_tool_use')
    if hosted and (not isinstance(hosted, dict) or set(hosted) - {'web_fetch_requests', 'web_search_requests'}
                   or model != 'claude-sonnet-5-5'
                   or type(hosted.get('web_fetch_requests', 0)) is not int
                   or hosted.get('web_fetch_requests', 0) < 0
                   or hosted.get('web_search_requests', 0) != 0):
        raise BudgetUsageError('Unpriced hosted tool use')
    if data.get('speed') not in (None, 'standard'):
        raise BudgetUsageError('Unpriced speed or hosted tool use')
    rates = POLICY['rates_nano'][model][int(i + read + write > POLICY['haiku_threshold'])]
    return i * rates[0] + o * rates[1] + read * rates[2] + write * _cache_write_rate(rates[0])


class WorkerSpendLedger:
    def __init__(self, path, authorization_id, max_usd):
        if not isinstance(authorization_id, str) or not re.fullmatch(r'[A-Za-z0-9._-]{1,100}', authorization_id):
            raise BudgetDenied('A non-secret worker budget authorization id is required')
        self.limit = amount_nano(max_usd)
        self.path = Path(path).resolve()
        self.path.parent.mkdir(parents=True, exist_ok=True)
        with self._db() as db:
            db.executescript('''
                CREATE TABLE IF NOT EXISTS authorization (
                    id INTEGER PRIMARY KEY CHECK(id=1), name TEXT NOT NULL,
                    limit_nano INTEGER NOT NULL, price_hash TEXT NOT NULL, halted INTEGER NOT NULL DEFAULT 0);
                CREATE TABLE IF NOT EXISTS requests (
                    id TEXT PRIMARY KEY, scope TEXT NOT NULL, model TEXT NOT NULL, status TEXT NOT NULL,
                    reserved_nano INTEGER NOT NULL, actual_nano INTEGER, output_limit INTEGER NOT NULL,
                    usage_json TEXT, error_type TEXT, created_at TEXT NOT NULL, finished_at TEXT);
            ''')
            db.execute('BEGIN IMMEDIATE')
            db.execute('INSERT OR IGNORE INTO authorization(id,name,limit_nano,price_hash) VALUES (1,?,?,?)',
                       (authorization_id, self.limit, PRICE_HASH))
            existing = db.execute('SELECT name,limit_nano,price_hash FROM authorization WHERE id=1').fetchone()
            if (existing[:2] != (authorization_id, self.limit)
                    or existing[2] not in (PRICE_HASH, PREVIOUS_PRICE_HASH, LEGACY_PRICE_HASH)):
                raise BudgetDenied('Existing worker authorization or pricing cannot be reset by configuration')
            if existing[2] != PRICE_HASH:
                db.execute('UPDATE authorization SET price_hash=? WHERE id=1', (PRICE_HASH,))

    @contextmanager
    def _db(self):
        db = sqlite3.connect(self.path, timeout=10)
        try:
            db.execute('PRAGMA synchronous=FULL')
            with db:
                yield db
        finally:
            db.close()

    def reserve(self, request, *, scope):
        reserved = reservation(request)
        ident = uuid4().hex
        with self._db() as db:
            db.execute('BEGIN IMMEDIATE')
            halted, = db.execute('SELECT halted FROM authorization WHERE id=1').fetchone()
            spent, = db.execute('SELECT COALESCE(SUM(COALESCE(actual_nano,reserved_nano)),0) FROM requests').fetchone()
            if halted or spent + reserved > self.limit:
                raise BudgetDenied('Worker authorization budget exhausted or halted before dispatch')
            db.execute('INSERT INTO requests VALUES (?,?,?,?,?,?,?,?,?,?,?)',
                       (ident, scope, request['model'], 'reserved', reserved, None, request['max_tokens'],
                        None, None, _now(), None))
        return ident

    def unknown(self, ident, reason):
        with self._db() as db:
            db.execute('BEGIN IMMEDIATE')
            changed = db.execute("UPDATE requests SET status='unknown',error_type=?,finished_at=? "
                                 "WHERE id=? AND status='reserved'", (reason, _now(), ident)).rowcount
            if changed:
                db.execute('UPDATE authorization SET halted=1 WHERE id=1')

    def cancel_before_dispatch(self, ident):
        # Only the caller that knows transport was never entered may release it.
        with self._db() as db:
            db.execute("UPDATE requests SET status='cancelled',actual_nano=0,finished_at=? "
                       "WHERE id=? AND status='reserved'", (_now(), ident))

    def recover_interrupted(self):
        """Call only after the HTTP store's exclusive process lock is acquired."""
        with self._db() as db:
            db.execute('BEGIN IMMEDIATE')
            changed = db.execute("UPDATE requests SET status='unknown',error_type='worker_restart',finished_at=? "
                                 "WHERE status='reserved'", (_now(),)).rowcount
            if changed:
                db.execute('UPDATE authorization SET halted=1 WHERE id=1')
        return changed

    def settle(self, ident, message):
        try:
            usage = message.usage
            data = usage.model_dump(mode='json') if hasattr(usage, 'model_dump') else vars(usage)
            actual = usage_cost(message.model, data)
        except Exception as exc:
            self.unknown(ident, type(exc).__name__)
            raise BudgetUsageError('Provider usage could not be priced; reservation retained') from None
        violated = False
        with self._db() as db:
            db.execute('BEGIN IMMEDIATE')
            row = db.execute('SELECT model,status,reserved_nano,output_limit FROM requests WHERE id=?', (ident,)).fetchone()
            if row is None or row[1] != 'reserved':
                raise BudgetUsageError('Unknown or already settled request')
            violated = (message.model != row[0] or actual > row[2]
                        or data['output_tokens'] > row[3]
                        or (data['input_tokens'] + data.get('cache_read_input_tokens', 0)
                            + data.get('cache_creation_input_tokens', 0)) > POLICY['context'])
            db.execute('UPDATE requests SET status=?,actual_nano=?,usage_json=?,finished_at=? WHERE id=?',
                       ('violation' if violated else 'settled', actual, json.dumps(data), _now(), ident))
            if violated:
                db.execute('UPDATE authorization SET halted=1 WHERE id=1')
        if violated:
            raise BudgetUsageError('Provider response exceeded reserved model or usage limits')

    def summary(self):
        return read_summary(self.path)

    def cost_for_scopes(self, scopes):
        if not scopes:
            return 0.0
        with self._db() as db:
            marks = ','.join('?' for _ in scopes)
            rows = db.execute(f'SELECT actual_nano FROM requests WHERE scope IN ({marks})', tuple(scopes)).fetchall()
        return None if any(row[0] is None for row in rows) else sum(row[0] for row in rows)/NANO


def read_summary(path):
    path = Path(path).resolve()
    with closing(sqlite3.connect(path.as_uri() + '?mode=ro', uri=True)) as db:
        db.execute('BEGIN')
        name, limit, price_hash, halted = db.execute(
            'SELECT name,limit_nano,price_hash,halted FROM authorization WHERE id=1').fetchone()
        count, known, held, unknown = db.execute('SELECT COUNT(*),COALESCE(SUM(actual_nano),0),'
            'COALESCE(SUM(CASE WHEN actual_nano IS NULL THEN reserved_nano ELSE 0 END),0),'
            'COALESCE(SUM(actual_nano IS NULL),0) FROM requests').fetchone()
    return dict(authorization_id=name, limit_usd=limit/NANO, price_hash=price_hash,
                known_cost_usd=known/NANO, reserved_unconfirmed_usd=held/NANO,
                accounted_upper_usd=(known+held)/NANO, remaining_usd=max(0, limit-known-held)/NANO,
                requests=count, unconfirmed_requests=unknown, halted=bool(halted))


if __name__ == '__main__':
    parser = argparse.ArgumentParser(description='Read the worker budget without network calls or changes')
    parser.add_argument('ledger', type=Path)
    args = parser.parse_args()
    print(json.dumps(read_summary(args.ledger), ensure_ascii=False, indent=2))
