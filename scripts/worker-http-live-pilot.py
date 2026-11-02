"""Explicit paid pilot through real localhost Uvicorn, with an isolated data store.

Keeps production prompts, output/tool/review limits and LiveRunner. The only LLM
instrumentation is durable request budgeting/observations and no SDK retries.
Run from ai-worker; requires --allow-paid. Raw artifacts remain under data/.
"""
from __future__ import annotations

import argparse
from contextlib import contextmanager
from dataclasses import replace
from datetime import datetime, timezone
from decimal import Decimal
import hashlib
import json
import os
from pathlib import Path
import secrets
import shutil
import socket
import sys
import threading
import time
from types import SimpleNamespace
from uuid import uuid4

sys.path.insert(0, str(Path(__file__).resolve().parents[1] / 'ai-worker' / 'src'))
import anthropic
import httpx
import uvicorn
from dotenv import load_dotenv
from bullbear.config import load_settings
from bullbear.audit import provenance
from bullbear.llm import LLM, LLMRequestBlocked
from bullbear.server import service as service_module
from bullbear.server.app import create_app

PRICE_SOURCE = 'https://platform.claude.com/docs/en/about-claude/pricing'
LIMIT_NANO = 3_000_000_000


def usage_cost(model, usage):
    if model not in {'claude-haiku-5-5', 'claude-sonnet-5-5'}:
        raise RuntimeError('unpriced response model')
    i, o = usage['input_tokens'], usage['output_tokens']
    read, creation = usage.get('cache_read_input_tokens', 0), usage.get('cache_creation_input_tokens', 0)
    if any(type(n) is not int or n < 0 for n in (i, o, read, creation)) or creation:
        raise RuntimeError('unexpected usage or cache creation')
    if i + read > 1_000_000 or o > 16000:
        raise RuntimeError('provider exceeded reserved limits')
    if 'haiku' in model:
        rates = (100, 500, 10) if i + read <= 100000 else (500, 2500, 50)
    else:
        rates = (2000, 10000, 100)
    return i * rates[0] + o * rates[1] + read * rates[2]


def prior_spend(directory, seen=None):
    """Read a finished sequential pilot chain; never settle unknown calls as zero.

    This is not a shared multi-process budget. A new run must name the latest run
    in this authorization with --prior-run; human authorization is still required.
    """
    if directory is None:
        return 0, None
    directory = Path(directory).resolve()
    seen = set() if seen is None else seen
    if directory in seen:
        raise ValueError('cyclic prior pilot chain')
    seen.add(directory)
    raw = (directory / 'requests.json').read_bytes()
    ledger = json.loads(raw)
    report = json.loads((directory / 'report.json').read_bytes())
    if report.get('server_stopped') is not True or report.get('unknown_requests') != 0:
        raise ValueError('prior pilot is unfinished or has unknown usage')
    if ledger.get('halted') or ledger.get('limit_usd') != 3 or ledger.get('price_source') != PRICE_SOURCE:
        raise ValueError('prior pilot budget policy mismatch or halted')
    parent = ledger.get('prior_run')
    carried, parent_hash = prior_spend(parent, seen)
    if (ledger.get('prior_spent_nano', 0) != carried
            or ledger.get('prior_ledger_sha256') != parent_hash):
        raise ValueError('prior pilot chain changed')
    cost = 0
    for record in ledger['requests']:
        if record.get('status') != 'received' or record.get('model') != record.get('response_model'):
            raise ValueError('prior pilot has unconfirmed requests')
        actual = usage_cost(record['response_model'], record['usage'])
        if (type(record.get('actual_nano')) is not int or record['actual_nano'] != actual
                or type(record.get('reserved_nano')) is not int or record['reserved_nano'] < actual):
            raise ValueError('prior pilot usage and cost mismatch')
        cost += actual
    reported = Decimal(str(report['known_cost_usd'])) * 1_000_000_000
    if not reported.is_finite() or reported != cost:
        raise ValueError('prior pilot report and ledger mismatch')
    return carried + cost, hashlib.sha256(raw).hexdigest()


def write(path, value):
    temp = path.with_suffix('.tmp')
    with temp.open('w', encoding='utf-8') as f:
        json.dump(value, f, ensure_ascii=False, indent=2)
        f.flush()
        os.fsync(f.fileno())
    os.replace(temp, path)


class Ledger:
    def __init__(self, directory, *, prior_run=None):
        self.directory, self.scope = directory, 'preflight'
        if (directory / 'requests.json').exists():
            raise FileExistsError('existing pilot ledger must not be overwritten')
        carried, prior_hash = prior_spend(prior_run)
        if carried >= LIMIT_NANO:
            raise ValueError('authorization budget already exhausted')
        self.data = dict(limit_usd=3, max_requests=48, price_source=PRICE_SOURCE,
                         pricing_checked_on='2026-11-02', requests=[], halted=False,
                         prior_run=str(Path(prior_run).resolve()) if prior_run is not None else None,
                         prior_spent_nano=carried, prior_ledger_sha256=prior_hash)
        self.save()

    def save(self):
        write(self.directory / 'requests.json', self.data)

    def reserve(self, request):
        model, output = request['model'], request['max_tokens']
        if model not in {'claude-haiku-5-5', 'claude-sonnet-5-5'} or output != 16000:
            raise RuntimeError('pilot model or output policy mismatch')
        # No cache writes or auxiliary paid tools. Reserve the full input limit,
        # plus all possible output, at the highest prompt-length tier.
        if 'cache_control' in json.dumps(request, default=str):
            raise RuntimeError('pilot cache writes are not budgeted')
        reserve = 1_000_000 * (500 if 'haiku' in model else 2000) + output * (2500 if 'haiku' in model else 10000)
        spent = self.data['prior_spent_nano'] + sum(r.get('actual_nano', r['reserved_nano']) for r in self.data['requests'])
        if self.data['halted'] or len(self.data['requests']) >= 48 or spent + reserve > LIMIT_NANO:
            raise LLMRequestBlocked('pilot budget or request limit reached before dispatch')
        record = dict(number=len(self.data['requests']) + 1, scope=self.scope, model=model,
                      status='reserved', reserved_nano=reserve, started_at=datetime.now(timezone.utc).isoformat())
        self.data['requests'].append(record)
        self.save()
        return record

    def settle(self, record, message, elapsed):
        usage = message.usage.model_dump(mode='json')
        write(self.directory / f"response-{record['number']:03}.json", message.model_dump(mode='json'))
        record.update(response_model=message.model, usage=usage, elapsed_seconds=round(elapsed, 3), stop_reason=message.stop_reason)
        if message.model != record['model']:
            raise RuntimeError('unpriced response model')
        actual = usage_cost(message.model, usage)
        record.update(status='received', actual_nano=actual)
        if actual > record['reserved_nano']:
            self.data['halted'] = True
            self.save()
            raise RuntimeError('provider exceeded reserved limits')
        self.save()


class Stream:
    def __init__(self, raw, ledger, record, start):
        self.raw, self.ledger, self.record, self.start = raw, ledger, record, start

    def __iter__(self):
        return iter(self.raw)

    def get_final_message(self):
        message = self.raw.get_final_message()
        self.ledger.settle(self.record, message, time.perf_counter() - self.start)
        return message


class Client:
    def __init__(self, ledger):
        self.ledger = ledger
        self.real = anthropic.Anthropic(max_retries=0, timeout=180.0)
        self.beta = SimpleNamespace(messages=SimpleNamespace(stream=self.stream))

    @contextmanager
    def stream(self, **request):
        record = self.ledger.reserve(request)
        start = time.perf_counter()
        try:
            with self.real.beta.messages.stream(**request) as raw:
                yield Stream(raw, self.ledger, record, start)
        except BaseException as exc:
            if record['status'] != 'received':
                record.update(status='unknown', error_type=type(exc).__name__,
                              http_status=getattr(exc, 'status_code', None), elapsed_seconds=round(time.perf_counter() - start, 3))
                self.ledger.data['halted'] = True
                self.ledger.save()
            raise

    def close(self):
        self.real.close()


def run(args):
    if not args.allow_paid:
        raise ValueError('--allow-paid is required')
    # Fail before loading credentials or starting any provider if prior usage is unknown.
    prior_spend(args.prior_run)
    load_dotenv(Path('.env'), override=True)
    settings = load_settings()
    models = (settings.debater_model, settings.moderator_model)
    if models != ('claude-haiku-5-5', 'claude-sonnet-5-5'):
        raise ValueError('pilot requires configured default Haiku/Sonnet models')
    directory = Path('data') / ('http-live-' + datetime.now().strftime('%Y%m%d-%H%M%S') + '-' + uuid4().hex[:6])
    directory.mkdir(parents=True)
    print(json.dumps({'directory': str(directory.resolve())}), flush=True)
    if settings.cache_dir.exists():
        shutil.copytree(settings.cache_dir, directory / 'cache')
    ledger = Ledger(directory, prior_run=args.prior_run)

    class PilotLLM(LLM):
        def __init__(self, model):
            super().__init__(model, client=Client(ledger))

    service_module.LLM = PilotLLM
    settings = replace(settings, data_dir=directory.resolve(), rag_enabled=False, rag_shadow_enabled=False)
    token = secrets.token_urlsafe(32)
    app = create_app(settings=settings, token=token, max_running=1)
    sock = socket.socket()
    sock.bind(('127.0.0.1', 0))
    port = sock.getsockname()[1]
    server = uvicorn.Server(uvicorn.Config(app, log_level='warning', access_log=False))
    thread = threading.Thread(target=server.run, kwargs={'sockets': [sock]}, daemon=True)
    thread.start()
    report = dict(ticker=args.ticker, models=models, rag=False, max_extra_rounds=args.max_extra_rounds,
                  sdk_retries=0, request_timeout_seconds=180, output_limit=16000,
                  provenance=provenance(), runs=[])
    try:
        for _ in range(100):
            if server.started:
                break
            time.sleep(.1)
        if not server.started:
            raise RuntimeError('server did not start')
        with httpx.Client(base_url=f'http://127.0.0.1:{port}', headers={'X-Worker-Token': token}, timeout=30) as client:
            report['health'] = client.get('/health').json()
            report['unauthenticated_status'] = httpx.get(f'http://127.0.0.1:{port}/stocks/{args.ticker}').status_code
            snapshot_id = None
            for mode in ('debate', 'single'):
                if mode == 'single' and snapshot_id is None:
                    report['runs'].append(dict(mode=mode, status='not_started', reason='no_snapshot'))
                    break
                ledger.scope = mode
                body = dict(ticker=args.ticker, mode=mode, request_id='pilot-' + uuid4().hex,
                            max_extra_rounds=args.max_extra_rounds)
                if mode == 'single':
                    body['snapshot_id'] = snapshot_id
                started = time.perf_counter()
                run = dict(mode=mode, post_attempts=[], events=[])
                report['runs'].append(run)
                while True:
                    at = time.perf_counter()
                    response = client.post('/debates', json=body)
                    run['post_attempts'].append(dict(status=response.status_code, elapsed_seconds=round(time.perf_counter() - at, 3)))
                    if response.status_code != 503 or time.perf_counter() - started > 300:
                        break
                    time.sleep(3)
                run['post_elapsed_seconds'] = round(time.perf_counter() - started, 3)
                if response.status_code != 202:
                    run.update(status='request_failed', error=response.json())
                    write(directory / 'report.json', report)
                    continue
                accepted = response.json()
                run['accepted'] = accepted
                ident = accepted['debate_id']
                print(json.dumps({'mode': mode, 'accepted': accepted}), flush=True)
                with client.stream('GET', f'/debates/{ident}/events', timeout=httpx.Timeout(35, connect=10)) as stream:
                    stream.raise_for_status()
                    event = {}
                    for line in stream.iter_lines():
                        if line.startswith('id: '): event['id'] = int(line[4:])
                        elif line.startswith('event: '): event['type'] = line[7:]
                        elif line.startswith('data: '): event['data'] = json.loads(line[6:])
                        elif not line and event:
                            event['elapsed_seconds'] = round(time.perf_counter() - started, 3)
                            run['events'].append(event)
                            write(directory / 'report.json', report)
                            print(json.dumps({'mode': mode, 'event': event['type'], 'seconds': event['elapsed_seconds']}, ensure_ascii=False), flush=True)
                            event = {}
                        if time.perf_counter() - started > 1800:
                            ledger.data['halted'] = True
                            ledger.save()
                            raise TimeoutError('pilot wall time exceeded')
                run['elapsed_seconds'] = round(time.perf_counter() - started, 3)
                detail = client.get(f'/debates/{ident}').json()
                run.update(status=detail['status'], detail=detail)
                snapshot_id = detail.get('snapshot_id') or next((e['data']['snapshot_id'] for e in run['events'] if e['type'] == 'snapshot_created'), None)
                if snapshot_id:
                    snap = client.get(f'/snapshots/{snapshot_id}').json()
                    write(directory / f'{mode}-snapshot.json', snap)
                    run['snapshot_sha256'] = hashlib.sha256(json.dumps(snap, sort_keys=True, ensure_ascii=False).encode()).hexdigest()
                n = len(ledger.data['requests'])
                reused = client.post('/debates', json=body)
                run['idempotency'] = dict(status=reused.status_code, same_id=reused.json().get('debate_id') == ident,
                                          reused=reused.json().get('reused'), no_new_model_requests=len(ledger.data['requests']) == n)
                last = run['events'][-1]['id']
                replay = client.get(f'/debates/{ident}/events', headers={'Last-Event-ID': str(last - 1)})
                run['last_event_replay'] = dict(status=replay.status_code, body=replay.text)
                write(directory / 'report.json', report)
                print(json.dumps({'mode': mode, 'status': run['status'], 'seconds': run['elapsed_seconds']}), flush=True)
    except Exception as exc:
        report['harness_error'] = dict(type=type(exc).__name__, http_status=getattr(exc, 'status_code', None))
        raise
    finally:
        write(directory / 'report.json', report)
        server.should_exit = True
        thread.join(timeout=240)
        report['server_stopped'] = not thread.is_alive()
        report['known_cost_usd'] = sum(r.get('actual_nano', 0) for r in ledger.data['requests']) / 1e9
        report['authorization_known_cost_usd'] = (ledger.data['prior_spent_nano']
            + sum(r.get('actual_nano', 0) for r in ledger.data['requests'])) / 1e9
        report['unknown_requests'] = sum(r['status'] != 'received' for r in ledger.data['requests'])
        write(directory / 'report.json', report)
        print(json.dumps({'finished': str(directory.resolve()), 'known_cost_usd': report['known_cost_usd'], 'unknown_requests': report['unknown_requests']}), flush=True)


if __name__ == '__main__':
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument('--allow-paid', action='store_true')
    parser.add_argument('--ticker', default='005930')
    parser.add_argument('--prior-run', type=Path,
                        help='Latest completed pilot in the same $3 authorization; subtract its entire chain')
    parser.add_argument('--check-budget', action='store_true',
                        help='Check prior usage without loading credentials or making network calls')
    parser.add_argument('--max-extra-rounds', type=int, choices=(0, 1), default=1,
                        help='Use 0 to measure the base three rounds without an extra round')
    args = parser.parse_args()
    if args.check_budget:
        spent, _ = prior_spend(args.prior_run)
        print(json.dumps({'limit_usd': 3, 'prior_spent_usd': spent / 1e9,
                          'remaining_usd': max(0, LIMIT_NANO - spent) / 1e9, 'network_calls': 0}))
    else:
        run(args)
