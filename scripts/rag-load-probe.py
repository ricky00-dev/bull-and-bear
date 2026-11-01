"""Bounded local HTTP concurrency probe. Fixture data only; not a production SLA.

Predeclared gates: concurrency <=4 must succeed; higher load may return only 503.
Every 200 must equal the stored baseline response; no 500, cross-ticker leakage,
market/model invocation or external socket is accepted. Uses the real app/storage.
"""
import argparse
from concurrent.futures import ThreadPoolExecutor
from dataclasses import replace
import ipaddress
import json
from math import ceil
from pathlib import Path
import sys
from time import perf_counter

from fastapi.testclient import TestClient
from bullbear.config import load_settings
from bullbear.server.app import create_app


class NoMarket:
    def __getattr__(self, name):
        raise AssertionError('market forbidden: ' + name)


def probe(directory, baseline):
    manifest = json.loads((directory / 'manifest.json').read_text(encoding='utf-8'))
    if not manifest['scope'].startswith('stored_real_and_mock_sources') or not manifest.get('bindings'):
        raise ValueError('rollover fixture required')
    expected = json.loads(baseline.read_text(encoding='utf-8'))
    settings = replace(load_settings(), data_dir=directory, rag_enabled=True,
        rag_generation_id=manifest['generation_id'], rag_archive_backend='sqlite', rag_context_backend='sqlite',
        rag_object_backend='local', rag_selection_policy=None, rag_shadow_enabled=False)
    def no_runner():
        raise AssertionError('model runner forbidden')
    app = create_app(settings=settings, market=NoMarket(), token='probe-token', runner_factory=no_runner)
    phases = []
    with TestClient(app) as client:
        def request(number, route):
            row = expected['rows'][number % len(expected['rows'])]
            body = dict(snapshot_id=row['snapshot_id'], ticker=row['ticker'])
            body.update({'question': 'PER 종목분리검증'} if route == 'search' else {'metric': 'close', 'unit': 'KRW/share'})
            started = perf_counter()
            response = client.post('/rag/' + route, json=body, headers={'X-Worker-Token': 'probe-token'})
            elapsed = perf_counter() - started
            if response.status_code == 200:
                assert response.json() == row['documents' if route == 'search' else 'facts'], 'response changed or leaked'
            else:
                assert response.status_code == 503, response.text
                assert response.json()['error']['code'] == 'RETRIEVAL_UNAVAILABLE', response.text
            return {'status': response.status_code, 'seconds': elapsed}
        for route in ('search', 'facts'):
            for concurrency in (1, 4, 8):
                started = perf_counter()
                with ThreadPoolExecutor(max_workers=concurrency) as pool:
                    results = list(pool.map(lambda n: request(n, route), range(32)))
                elapsed = perf_counter() - started
                latencies = sorted(item['seconds'] for item in results)
                counts = {str(code): sum(item['status'] == code for item in results) for code in (200, 503)}
                phase = dict(route=route, concurrency=concurrency, requests=len(results), statuses=counts,
                    wall_seconds=elapsed, requests_per_second=len(results)/elapsed,
                    p50_seconds=latencies[ceil(len(latencies)*.5)-1], p95_seconds=latencies[ceil(len(latencies)*.95)-1],
                    max_seconds=max(latencies), gate_passed=concurrency > 4 or counts['503'] == 0)
                phases.append(phase)
    return dict(schema='rag-local-load-probe-v1', scope='in_process_http_sqlite_fixture_not_deployment_load',
        gate='32 requests/phase; concurrency<=4 all200; concurrency8 may503; all200 exact baseline equality',
        all_gates_passed=all(row['gate_passed'] for row in phases), phases=phases,
        model_calls=0, limitations=['two tickers/two fixture documents', 'no Spring/browser/network transport load',
                                   'no PostgreSQL or production hardware', 'no sustained endurance or SLA claim'])


if __name__ == '__main__':
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument('directory', type=Path)
    parser.add_argument('--baseline', type=Path, required=True)
    parser.add_argument('--report', type=Path, required=True)
    args = parser.parse_args()
    connections = []
    def offline(event, values):
        if event == 'socket.connect':
            allowed = ipaddress.ip_address(values[1][0]).is_loopback
            connections.append({'host': values[1][0], 'allowed': allowed})
            if not allowed:
                raise RuntimeError('external network forbidden')
    sys.addaudithook(offline)
    report = probe(args.directory, args.baseline)
    report['socket_connections'] = connections
    args.report.write_text(json.dumps(report, ensure_ascii=False, indent=2), encoding='utf-8')
    print(json.dumps({'all_gates_passed': report['all_gates_passed'], 'phases': report['phases']}))
    raise SystemExit(0 if report['all_gates_passed'] else 1)
