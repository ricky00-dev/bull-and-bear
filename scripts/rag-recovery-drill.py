"""Offline recovery exercise for stopped, SQLite/local integration fixtures only.

Not a live/production backup tool. No provider, model, S3 or PostgreSQL access.
Backup SQLite through its backup API (including committed WAL), retain sealed
generation bytes/receipts, verify inventory before restoring into a new directory.
"""
import argparse
from contextlib import closing
from dataclasses import replace
import hashlib
import ipaddress
import json
from pathlib import Path
import shutil
import sqlite3
import sys
from time import perf_counter

from fastapi.testclient import TestClient
from bullbear.config import load_settings
from bullbear.rag.binding import check_bindings
from bullbear.rag.store import RagStore
from bullbear.server.app import create_app
from bullbear.server.store import Store


def sha(path):
    return hashlib.sha256(path.read_bytes()).hexdigest()


def inventory(directory):
    files = {}
    for path in sorted(directory.rglob('*')):
        if path.is_symlink() or path.is_junction():
            raise ValueError('linked fixture paths are not supported')
        if path.is_file():
            files[path.relative_to(directory).as_posix()] = sha(path)
    return files


def logical_hash(path):
    with closing(sqlite3.connect(path.resolve().as_uri() + '?mode=ro', uri=True)) as db:
        assert db.execute('PRAGMA integrity_check').fetchone()[0] == 'ok'
        assert not db.execute('PRAGMA foreign_key_check').fetchall()
        schema = db.execute('SELECT type,name,sql FROM sqlite_master ORDER BY type,name').fetchall()
        tables = [r[0] for r in db.execute("SELECT name FROM sqlite_master WHERE type='table' ORDER BY name")]
        contents = [(table, sorted(map(repr, db.execute('SELECT * FROM "' + table.replace('"', '""') + '"').fetchall())))
                    for table in tables]
    return hashlib.sha256(repr((schema, contents)).encode()).hexdigest()


def backup(source, destination):
    # The worker owner lock excludes live HTTP writers. All other fixture writers
    # must be stopped by the caller. This exercise never claims online consistency.
    logical = {}
    with closing(Store(source / 'http', maintenance=True, read_only=True)):
        destination.mkdir(parents=True, exist_ok=False)
        for path in sorted(source.rglob('*')):
            if path.is_symlink() or path.is_junction():
                raise ValueError('linked fixture paths are not supported')
            if not path.is_file() or path.name.startswith('owner.sqlite3') or path.name.endswith(('-wal', '-shm')):
                continue
            if path.name == '.env' or path.name.startswith('.env.'):
                raise ValueError('fixture must not contain environment files')
            relative = path.relative_to(source)
            target = destination / relative
            target.parent.mkdir(parents=True, exist_ok=True)
            if path.suffix == '.sqlite3' and 'generations' not in relative.parts:
                before = logical_hash(path)
                with closing(sqlite3.connect(path.resolve().as_uri() + '?mode=ro', uri=True)) as reader:
                    with closing(sqlite3.connect(target)) as writer:
                        reader.backup(writer)
                if logical_hash(target) != before or logical_hash(path) != before:
                    raise ValueError('fixture database changed during backup')
                logical[relative.as_posix()] = before
            else:
                shutil.copyfile(path, target)
    return {'files': inventory(destination), 'database_logical_hashes': logical}


def restore(backup_dir, destination, expected):
    if inventory(backup_dir) != expected['files']:
        raise ValueError('backup inventory mismatch')
    # New destinations only. Never replace live data or remove a partial restore.
    shutil.copytree(backup_dir, destination)
    if inventory(destination) != expected['files']:
        raise ValueError('restore inventory mismatch')
    for name, digest in expected['database_logical_hashes'].items():
        if logical_hash(destination / name) != digest:
            raise ValueError('restored database mismatch')


class NoMarket:
    def close(self):
        pass

    def __getattr__(self, name):
        raise AssertionError('market access forbidden: ' + name)


def drill(source, output, baseline):
    source = source.resolve()
    output = output.resolve()
    if source == output or source in output.parents or output in source.parents:
        raise ValueError('source and output must be separate directories')
    manifest = json.loads((source / 'manifest.json').read_text(encoding='utf-8'))
    if not manifest['scope'].startswith('stored_real_and_mock_sources') or not manifest.get('bindings'):
        raise ValueError('stopped rollover integration fixture required')
    output.mkdir(parents=True, exist_ok=False)
    started = perf_counter()
    saved = backup(source, output / 'backup')
    backup_seconds = perf_counter() - started
    # Damage only a disposable backup copy; original data and valid backup stay intact.
    shutil.copytree(output / 'backup', output / 'corrupt-backup')
    receipt = next((output / 'corrupt-backup' / 'rag' / 'generations').glob('*/index.ready.json'))
    receipt.write_bytes(receipt.read_bytes() + b'corrupt')
    try:
        restore(output / 'corrupt-backup', output / 'must-not-exist', saved)
    except ValueError:
        pass
    else:
        raise AssertionError('damaged backup accepted')
    assert not (output / 'must-not-exist').exists()
    started = perf_counter()
    restored = output / 'restored'
    restore(output / 'backup', restored, saved)
    restore_seconds = perf_counter() - started
    with closing(Store(restored / 'http', maintenance=True)) as worker, RagStore(restored / 'rag') as archive:
        binding_report = check_bindings(worker, archive)
        assert sum(row['ready'] for row in binding_report['snapshots']) == len(manifest['bindings'])
    settings = replace(load_settings(), data_dir=restored, rag_enabled=True,
        rag_generation_id=manifest['generation_id'], rag_archive_backend='sqlite', rag_context_backend='sqlite',
        rag_object_backend='local', rag_selection_policy=None, rag_shadow_enabled=False)
    def forbidden_runner():
        raise AssertionError('runner creation forbidden')
    expected = json.loads(baseline.read_text(encoding='utf-8'))
    results = []
    # Two independent application lifetimes exercise restart after restore.
    for attempt in range(2):
        app = create_app(settings=settings, market=NoMarket(), token='drill-token', runner_factory=forbidden_runner)
        with TestClient(app) as client:
            for row in expected['rows']:
                identity = dict(snapshot_id=row['snapshot_id'], ticker=row['ticker'])
                for route, request, key in [('search', {'question': 'PER 종목분리검증'}, 'documents'),
                                            ('facts', {'metric': 'close', 'unit': 'KRW/share'}, 'facts')]:
                    response = client.post('/rag/' + route, json={**identity, **request}, headers={'X-Worker-Token': 'drill-token'})
                    assert response.status_code == 200, response.text
                    assert response.json() == row[key], (route, row['ticker'])
                    results.append(dict(restart=attempt, ticker=row['ticker'], route=route, context_id=response.json()['context_id']))
    return dict(schema='rag-local-recovery-drill-v1', scope='sqlite_local_fixture_not_cloud_restore',
        backup_seconds=backup_seconds, restore_seconds=restore_seconds,
        backup_inventory=saved, binding_check=binding_report, checks=results,
        corrupt_backup_rejected_before_destination_created=True, model_calls=0,
        limitations=['fixture corpus and mixed real/mock snapshots', 'all writers stopped',
                     'not PostgreSQL backup recovery', 'not cloud/IAM/TLS verification', 'not capacity or RTO guarantee'])


if __name__ == '__main__':
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument('source', type=Path)
    parser.add_argument('output', type=Path)
    parser.add_argument('--baseline', type=Path, required=True)
    parser.add_argument('--report', type=Path, required=True)
    args = parser.parse_args()
    # Windows asyncio uses loopback socketpair internally. Forbid external sockets.
    connections = []
    def offline(event, values):
        if event == 'socket.connect':
            host = values[1][0]
            allowed = ipaddress.ip_address(host).is_loopback
            connections.append({'host': host, 'allowed': allowed})
            if not allowed:
                raise RuntimeError('external network forbidden during recovery drill')
    sys.addaudithook(offline)
    report = drill(args.source, args.output, args.baseline)
    report['socket_connections'] = connections
    args.report.write_text(json.dumps(report, ensure_ascii=False, indent=2), encoding='utf-8')
    print(json.dumps({key: report[key] for key in ('scope', 'backup_seconds', 'restore_seconds', 'corrupt_backup_rejected_before_destination_created')}))
