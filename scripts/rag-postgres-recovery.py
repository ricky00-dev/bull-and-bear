"""Local PostgreSQL dump/restore drill; only newly named fixture databases.

Requires the dedicated localhost:15439 test cluster and unpacked WSL Ubuntu
PostgreSQL clients. Existing databases/destinations are never replaced or dropped.
"""
import argparse
from contextlib import closing
from dataclasses import replace
import hashlib
import importlib.util
import ipaddress
import json
from pathlib import Path
import re
import subprocess
import sys
from time import perf_counter

import psycopg
from psycopg import sql
from fastapi.testclient import TestClient
from bullbear.config import load_settings
from bullbear.rag.archive_repository import PostgresArchive
from bullbear.rag.archive_transfer import import_archive
from bullbear.rag.context_repository import PostgresContextRepository
from bullbear.rag.storage import migrate, import_sqlite_contexts
from bullbear.rag.generation_transfer import push_generation
from bullbear.rag.embeddings import EmbeddingSpec, EmbeddingService
from bullbear.rag.vectors import install_vectors, VectorIndex
from bullbear.server.app import create_app


def helper():
    spec = importlib.util.spec_from_file_location('recovery_drill', Path(__file__).with_name('rag-recovery-drill.py'))
    module = importlib.util.module_from_spec(spec)
    spec.loader.exec_module(module)
    return module


def dsn(name):
    if not re.fullmatch(r'rag_restore_[a-z0-9_]+', name):
        raise ValueError('dedicated rag_restore_ database prefix required')
    return f'postgresql://rag_test@127.0.0.1:15439/{name}?connect_timeout=5'


def database_signature(connection):
    with psycopg.connect(connection) as db:
        db.execute("SET TIME ZONE 'UTC'")
        tables = db.execute("SELECT schemaname,tablename FROM pg_tables WHERE schemaname IN ('rag','public') ORDER BY 1,2").fetchall()
        contents = {}
        for schema, table in tables:
            rows = sorted(row[0] for row in db.execute(sql.SQL('SELECT row_to_json(t)::text FROM {}.{} t').format(sql.Identifier(schema), sql.Identifier(table))))
            contents[schema + '.' + table] = {'count': len(rows), 'sha256': hashlib.sha256('\n'.join(rows).encode()).hexdigest()}
        sequences = {}
        # information_schema.sequences omits identity-owned sequences; use pg_class.
        for schema, name in db.execute("SELECT n.nspname,c.relname FROM pg_class c JOIN pg_namespace n ON n.oid=c.relnamespace WHERE c.relkind='S' AND n.nspname='rag' ORDER BY 1,2"):
            sequences[schema + '.' + name] = list(db.execute(sql.SQL('SELECT last_value,is_called FROM {}.{}').format(sql.Identifier(schema), sql.Identifier(name))).fetchone())
        assert sequences, 'identity sequences must be inspected'
        triggers = db.execute("SELECT c.relname,t.tgname,pg_get_triggerdef(t.oid) FROM pg_trigger t JOIN pg_class c ON c.oid=t.tgrelid JOIN pg_namespace n ON n.oid=c.relnamespace WHERE n.nspname='rag' AND NOT t.tgisinternal ORDER BY 1,2").fetchall()
        constraints = db.execute("SELECT c.relname,k.conname,pg_get_constraintdef(k.oid) FROM pg_constraint k JOIN pg_class c ON c.oid=k.conrelid JOIN pg_namespace n ON n.oid=c.relnamespace WHERE n.nspname='rag' ORDER BY 1,2").fetchall()
        indexes = db.execute("SELECT tablename,indexname,indexdef FROM pg_indexes WHERE schemaname='rag' ORDER BY 1,2").fetchall()
        columns = db.execute("SELECT c.relname,a.attnum,a.attname,format_type(a.atttypid,a.atttypmod),a.attnotnull,a.attidentity,pg_get_expr(d.adbin,d.adrelid) FROM pg_attribute a JOIN pg_class c ON c.oid=a.attrelid JOIN pg_namespace n ON n.oid=c.relnamespace LEFT JOIN pg_attrdef d ON d.adrelid=a.attrelid AND d.adnum=a.attnum WHERE n.nspname='rag' AND c.relkind='r' AND a.attnum>0 AND NOT a.attisdropped ORDER BY 1,2").fetchall()
        extensions = db.execute('SELECT extname,extversion FROM pg_extension ORDER BY extname').fetchall()
    return dict(tables=contents, sequences=sequences, triggers=triggers, extensions=extensions,
                constraints=constraints, indexes=indexes, columns=columns)


def linux(path):
    return subprocess.check_output(['wsl', '-d', 'Ubuntu', '--exec', 'wslpath', '-u', str(path.resolve())], text=True).strip()


def client(tools, program, *args):
    base = linux(tools)
    return subprocess.run(['wsl', '-d', 'Ubuntu', '--exec', 'env', 'LD_LIBRARY_PATH='+base+'/root/usr/lib/x86_64-linux-gnu',
        base+'/root/usr/lib/postgresql/16/bin/'+program, *args], check=True, capture_output=True, text=True).stdout.strip()


class Synthetic:
    calls = 0
    def embed(self, spec, text):
        self.calls += 1
        return [1.0, 0.0, 0.0], 1


def restricted_role_probe(settings, row, name, recovery):
    """Provision only a new test role, exercise documented grants, then remove it."""
    connection = settings.rag_postgres_dsn
    with psycopg.connect(connection, autocommit=True) as db:
        if db.execute('SELECT 1 FROM pg_roles WHERE rolname=%s', (name,)).fetchone():
            raise ValueError('new runtime test role required')
        db.execute(sql.SQL('CREATE ROLE {} LOGIN NOSUPERUSER NOCREATEDB NOCREATEROLE').format(sql.Identifier(name)))
    try:
        with psycopg.connect(connection, autocommit=True) as db:
            db.execute(sql.SQL('GRANT USAGE ON SCHEMA rag TO {}').format(sql.Identifier(name)))
            db.execute(sql.SQL('GRANT SELECT,INSERT ON ALL TABLES IN SCHEMA rag TO {}').format(sql.Identifier(name)))
            db.execute(sql.SQL('GRANT USAGE,SELECT ON ALL SEQUENCES IN SCHEMA rag TO {}').format(sql.Identifier(name)))
        runtime = connection.replace('rag_test@', name+'@')
        forbidden = []
        with psycopg.connect(runtime, autocommit=True) as db:
            for statement in ('UPDATE rag.contexts SET payload=payload', 'DELETE FROM rag.contexts',
                              'TRUNCATE rag.contexts', 'CREATE TABLE rag.forbidden_test(id int)'):
                try:
                    db.execute(statement)
                except psycopg.errors.InsufficientPrivilege:
                    forbidden.append(statement.split()[0])
                else:
                    raise AssertionError('runtime role exceeded grants')
        def no_runner():
            raise AssertionError('model forbidden')
        app = create_app(settings=replace(settings, rag_postgres_dsn=runtime), market=recovery.NoMarket(),
            token='role-token', runner_factory=no_runner)
        with TestClient(app) as http:
            for route, body, key in [('search', {'question':'PER 종목분리검증'}, 'documents'),
                                     ('facts', {'metric':'close','unit':'KRW/share'}, 'facts')]:
                response = http.post('/rag/'+route, json={'snapshot_id':row['snapshot_id'], 'ticker':row['ticker'], **body},
                    headers={'X-Worker-Token':'role-token'})
                assert response.status_code == 200, response.text
                assert response.json() == row[key]
        return dict(search_and_facts_equal=True, denied=forbidden, schema_usage=True,
                    table_permissions=['SELECT','INSERT'], sequence_permissions=['USAGE','SELECT'])
    finally:
        with psycopg.connect(connection, autocommit=True) as db:
            db.execute(sql.SQL('REVOKE ALL ON ALL TABLES IN SCHEMA rag FROM {}').format(sql.Identifier(name)))
            db.execute(sql.SQL('REVOKE ALL ON ALL SEQUENCES IN SCHEMA rag FROM {}').format(sql.Identifier(name)))
            db.execute(sql.SQL('REVOKE ALL ON SCHEMA rag FROM {}').format(sql.Identifier(name)))
            db.execute(sql.SQL('DROP ROLE {}').format(sql.Identifier(name)))


def run(source, output, tools, prefix, baseline):
    source, output = source.resolve(), output.resolve()
    if source == output or source in output.parents or output in source.parents:
        raise ValueError('source and output must be separate')
    manifest = json.loads((source / 'manifest.json').read_text(encoding='utf-8'))
    if not manifest['scope'].startswith('stored_real_and_mock_sources') or not manifest.get('bindings'):
        raise ValueError('rollover fixture required')
    source_name, restored_name = prefix + '_source', prefix + '_restored'
    source_dsn, restored_dsn = dsn(source_name), dsn(restored_name)
    output.mkdir(parents=True, exist_ok=False)
    with psycopg.connect('postgresql://rag_test@127.0.0.1:15439/postgres', connect_timeout=5, autocommit=True) as admin:
        if admin.execute('SELECT 1 FROM pg_database WHERE datname=ANY(%s)', ([source_name, restored_name],)).fetchone():
            raise ValueError('new databases required')
        for name in (source_name, restored_name):
            admin.execute(sql.SQL('CREATE DATABASE {}').format(sql.Identifier(name)))
    recovery = helper()
    inventory = recovery.backup(source, output / 'files-source')
    migrate(source_dsn)
    install_vectors(source_dsn)
    with PostgresArchive(output / 'files-source' / 'rag', source_dsn) as archive:
        imported_archive = import_archive(source / 'rag' / 'rag.sqlite3', archive)
        for generation in (manifest['previous_generation_id'], manifest['generation_id']):
            push_generation(archive, generation)
        synthetic = Synthetic()
        embedding = EmbeddingService(source_dsn, EmbeddingSpec(provider='fixture', model='restore-synthetic',
            revision='v1', dimensions=3, price_revision='zero', nano_usd_per_token=0), synthetic)
        vector_id = VectorIndex(embedding).build(archive, manifest['previous_generation_id'], daily_budget_nano=1000)
    imported_contexts = import_sqlite_contexts(source / 'rag' / 'contexts.sqlite3', PostgresContextRepository(source_dsn))
    before = database_signature(source_dsn)
    archive_path = output / 'rag.dump'
    started = perf_counter()
    version = client(tools, 'pg_dump', '--version')
    client(tools, 'pg_dump', '--dbname='+source_dsn, '--format=custom', '--no-owner', '--no-acl', '--file='+linux(archive_path))
    dump_seconds = perf_counter() - started
    assert database_signature(source_dsn) == before, 'source changed during dump'
    started = perf_counter()
    client(tools, 'pg_restore', '--dbname='+restored_dsn, '--no-owner', '--no-acl', '--exit-on-error', linux(archive_path))
    restore_seconds = perf_counter() - started
    assert database_signature(restored_dsn) == before, 'database restore mismatch'
    # Include generation registry object bytes added during preparation.
    inventory['files'] = recovery.inventory(output / 'files-source')
    recovery.restore(output / 'files-source', output / 'files-restored', inventory)
    restored = output / 'files-restored'
    expected = json.loads(baseline.read_text(encoding='utf-8'))
    settings = replace(load_settings(), data_dir=restored, rag_enabled=True,
        rag_generation_id=manifest['generation_id'], rag_archive_backend='postgres', rag_context_backend='postgres',
        rag_postgres_dsn=restored_dsn, rag_object_backend='local', rag_selection_policy=None, rag_shadow_enabled=False)
    def no_runner():
        raise AssertionError('model forbidden')
    responses = []
    for restart in range(2):
        app = create_app(settings=settings, market=recovery.NoMarket(), token='restore-token', runner_factory=no_runner)
        with TestClient(app) as http:
            for row in expected['rows']:
                for route, body, key in [('search', {'question':'PER 종목분리검증'}, 'documents'),
                                         ('facts', {'metric':'close','unit':'KRW/share'}, 'facts')]:
                    response = http.post('/rag/'+route, json={'snapshot_id':row['snapshot_id'], 'ticker':row['ticker'], **body},
                        headers={'X-Worker-Token':'restore-token'})
                    assert response.status_code == 200, response.text
                    assert response.json() == row[key], 'restored response mismatch'
                    responses.append({'restart':restart, 'route':route, 'ticker':row['ticker'], 'context_id':response.json()['context_id']})
    with psycopg.connect(restored_dsn) as db:
        try:
            db.execute('UPDATE rag.contexts SET payload=payload')
        except psycopg.errors.RaiseException:
            db.rollback()
        else:
            raise AssertionError('immutable context trigger missing')
    runtime_check = restricted_role_probe(settings, expected['rows'][0], prefix + '_runtime', recovery)
    after = database_signature(restored_dsn)
    assert after['tables']['rag.searches']['count'] == before['tables']['rag.searches']['count'] + 10
    assert after['tables']['rag.contexts'] == before['tables']['rag.contexts']
    return dict(schema='rag-postgres-recovery-v1', scope='dedicated_local_postgres_and_local_objects_fixture',
        databases=[source_name,restored_name], client_version=version,
        dump_sha256=recovery.sha(archive_path), dump_seconds=dump_seconds, restore_seconds=restore_seconds,
        original_database_signature=before, restored_signature_equal_before_http=True,
        file_inventory=inventory, imported_archive=imported_archive, imported_contexts=imported_contexts,
        vector_generation=vector_id, synthetic_embedding_calls=synthetic.calls, external_model_calls=0,
        http_responses=responses, immutable_trigger_rejected_update=True, new_search_audits=10,
        restricted_runtime_role=runtime_check, temporary_role_removed=True,
        limitations=['local trust auth; not cloud TLS/IAM', 'two fixture documents and mixed real/mock snapshots',
                     'synthetic vectors verify storage only', 'not live cross-database backup', 'roles/ACLs not included'])


if __name__ == '__main__':
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument('source', type=Path)
    parser.add_argument('output', type=Path)
    parser.add_argument('--client-dir', type=Path, required=True)
    parser.add_argument('--database-prefix', required=True)
    parser.add_argument('--baseline', type=Path, required=True)
    parser.add_argument('--report', type=Path, required=True)
    args = parser.parse_args()
    connections = []
    def offline(event, values):
        if event == 'socket.connect':
            host = values[1][0]
            allowed = ipaddress.ip_address(host).is_loopback
            connections.append({'host':host,'allowed':allowed})
            if not allowed:
                raise RuntimeError('external network forbidden')
    sys.addaudithook(offline)
    result = run(args.source, args.output, args.client_dir, args.database_prefix, args.baseline)
    result['python_socket_connections'] = connections
    args.report.write_text(json.dumps(result,ensure_ascii=False,indent=2),encoding='utf-8')
    print(json.dumps({key:result[key] for key in ('databases','client_version','dump_seconds','restore_seconds','new_search_audits')}))
