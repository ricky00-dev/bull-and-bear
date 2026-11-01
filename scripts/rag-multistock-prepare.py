"""Offline integration fixtures: local documents -> publish -> readiness -> save snapshots.

Usage (PYTHONPATH=ai-worker/src):
  python scripts/rag-multistock-prepare.py prepare DATA --snapshot FILE --snapshot FILE
  python scripts/rag-multistock-prepare.py seed DATA --dsn LOCAL_POSTGRES_DSN
Original files/IDs/timestamps are preserved. Newly saved copies are explicitly test fixtures.
"""
import argparse
from datetime import datetime, timezone
import hashlib
import json
from pathlib import Path
from uuid import uuid5, NAMESPACE_URL

from bullbear.snapshot import Snapshot
from bullbear.rag import RagStore, DocumentInput, CollectionBatch, ChunkInput, AnnotationInput
from bullbear.rag.index import GenerationIndex
from bullbear.rag.readiness import check_generation
from bullbear.rag.binding import capture_binding
from bullbear.server.store import Store


def prepare(directory, paths):
    originals = [(path, Snapshot.model_validate_json(path.read_text(encoding='utf-8'))) for path in paths]
    if len({snapshot.ticker for _, snapshot in originals}) < 2:
        raise ValueError('At least two distinct saved tickers required')
    directory.mkdir(parents=True, exist_ok=False)
    rows = []
    with RagStore(directory / 'rag') as store:
        for path, snapshot in originals:
            at = datetime.now(timezone.utc)
            text = f'PER 종목분리검증 {snapshot.ticker} 전용 문단. 테스트 fixture이며 투자 정보가 아니다.'
            document = DocumentInput(source='integration-fixture', source_item_id=snapshot.ticker,
                kind='knowledge', source_ref='local-test', url=f'https://example.invalid/{snapshot.ticker}',
                title='PER 종목분리검증', text=text, tickers=(snapshot.ticker,),
                published_at=at, observed_at=at, timestamp_precision='instant',
                content_level='full_text', publication_verified=True,
                metadata={'scope': 'integration_fixture_not_financial_information'})
            store.import_collection(CollectionBatch(collection_id='multi-'+snapshot.ticker,
                source=document.source, query_key=snapshot.ticker, window_start=at, window_end=at,
                started_at=at, finished_at=at, status='completed', coverage='complete', pages=1,
                items=(document,), observation_mode='current'))
            chunk = ChunkInput(revision_id=document.revision_id, ordinal=0, text=text,
                source_locator='paragraph:1', chunker_version='integration-v1')
            store.add_chunk(chunk)
            store.annotate(AnnotationInput(chunk_id=chunk.chunk_id, horizons=('common',),
                markets=('KR',), tickers=(snapshot.ticker,), topics=('per',),
                review_status='approved', created_at=at, reviewed_at=at,
                tagging_policy_version='integration-fixture-v1', applicability='종목 분리 테스트 전용',
                limitations=('실제 금융 문서가 아닌 테스트 자료',)))
            rows.append({'ticker': snapshot.ticker, 'source_snapshot_id': snapshot.snapshot_id,
                'source_sha256': hashlib.sha256(path.read_bytes()).hexdigest(),
                'source_provider': snapshot.provider, 'source_created_at': snapshot.created_at.isoformat(),
                'source_is_mock': 'fake' in snapshot.provider.lower(),
                'chunk_id': chunk.chunk_id, 'as_of': snapshot.as_of.isoformat(),
                'close': snapshot.facts['PX.CLOSE'].value,
                'original_debate_id': str(uuid5(NAMESPACE_URL, 'original:'+snapshot.snapshot_id))})
        generation = GenerationIndex(store).publish(datetime.now(timezone.utc))
        publication = check_generation(store, generation)
        assert publication['ready_for_new_snapshot']
        assert publication['member_count'] == len(originals), 'All ticker test documents must be published'
        snapshots = []
        (directory / 'snapshots').mkdir()
        http = Store(directory / 'http')
        try:
            for row, (_, original) in zip(rows, originals):
                # A new test observation, never a historical correction/replacement.
                now = datetime.now(timezone.utc)
                fixture = original.model_copy(update={
                    'snapshot_id': 'MULTI.' + row['ticker'] + '.' + hashlib.sha256(now.isoformat().encode()).hexdigest()[:16],
                    'created_at': now, 'provider': 'integration_copy_of:'+original.provider})
                row.update(snapshot_id=fixture.snapshot_id, created_at=fixture.created_at.isoformat(),
                    debate_id=str(uuid5(NAMESPACE_URL, fixture.snapshot_id)))
                for value in (original, fixture):
                    (directory / 'snapshots' / (value.snapshot_id+'.json')).write_text(value.model_dump_json(), encoding='utf-8')
                    with http.db:
                        http.db.execute('INSERT INTO snapshots VALUES (?,?)', (value.snapshot_id, value.model_dump_json()))
                http.bind_generation(fixture.snapshot_id, capture_binding(store, fixture, generation))
                snapshots.extend((original, fixture))
        finally:
            http.close()
        checks = check_generation(store, generation, snapshots=snapshots)
        for row in checks['snapshots']:
            assert row['eligible'] == row['snapshot_id'].startswith('MULTI.')
        manifest = {'generation_id': generation, 'publication': publication, 'readiness': checks,
                    'rows': rows, 'scope': 'stored_real_and_mock_sources_with_new_post_publication_test_copies'}
        (directory / 'manifest.json').write_text(json.dumps(manifest, ensure_ascii=False, indent=2), encoding='utf-8')
    print(json.dumps(manifest, ensure_ascii=False))


def seed(directory, dsn):
    import psycopg
    manifest = json.loads((directory / 'manifest.json').read_text(encoding='utf-8'))
    with psycopg.connect(dsn) as db:
        # Never seed into an application database already containing debates.
        if db.execute('select count(*) from debates').fetchone()[0]:
            raise ValueError('Seed requires an empty dedicated integration database')
        for row in manifest['rows']:
            for old in (True, False):
                id = row['original_debate_id'] if old else row['debate_id']
                sid = row['source_snapshot_id'] if old else row['snapshot_id']
                db.execute('''INSERT INTO debates(id,ticker,stock_name,status,snapshot_id,trade_date,base_price,
                    created_at,completed_at,origin,debate_day,data_date)
                    VALUES(%s,%s,%s,'FAILED',%s,%s,%s,now(),now(),'USER',%s,%s)''',
                    (id,row['ticker'],'검증용 '+row['ticker'],sid,row['as_of'],row['close'],row['as_of'],row['as_of']))
                db.execute('''INSERT INTO debate_events(debate_id,seq,type,payload,created_at)
                    VALUES(%s,1,'debate_failed','{"error":{"message":"저장 자료 조회 전용 검증"}}',now())''', (id,))
    print('Seeded saved-snapshot references only; no debate API or models called.')


if __name__ == '__main__':
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument('action', choices=['prepare', 'seed'])
    parser.add_argument('directory', type=Path)
    parser.add_argument('--snapshot', type=Path, action='append', default=[])
    parser.add_argument('--dsn')
    args = parser.parse_args()
    if args.action == 'prepare':
        prepare(args.directory, args.snapshot)
    else:
        seed(args.directory, args.dsn)
