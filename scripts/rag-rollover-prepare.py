"""Copy stopped integration fixtures, migrate from saved contexts, then publish G2.

Never use for live backups. Source must be the saved multistock test fixture.
No provider/model calls; snapshots and original contexts are unchanged.
"""
import argparse
from contextlib import closing
from datetime import datetime, timezone
import json
from pathlib import Path
import shutil

from bullbear.rag.binding import migrate_binding, check_bindings
from bullbear.rag.index import GenerationIndex
from bullbear.rag.replay import load_context
from bullbear.rag.store import RagStore
from bullbear.server.store import Store

parser = argparse.ArgumentParser()
parser.add_argument('source', type=Path)
parser.add_argument('destination', type=Path)
parser.add_argument('--report', type=Path, required=True)
args = parser.parse_args()
report = json.loads(args.report.read_text(encoding='utf-8'))
manifest = json.loads((args.source / 'manifest.json').read_text(encoding='utf-8'))
if not manifest['scope'].startswith('stored_real_and_mock_sources'):
    raise ValueError('integration fixture source required')
with closing(Store(args.source / 'http', maintenance=True, read_only=True)):
    shutil.copytree(args.source, args.destination, ignore=shutil.ignore_patterns('owner.sqlite3*'))
with closing(Store(args.destination / 'http', maintenance=True)) as worker, RagStore(args.destination / 'rag') as archive:
    pins = []
    for row in manifest['rows']:
        old = next(item for item in report['rows'] if item['snapshot_id'] == row['snapshot_id'])
        context = load_context(archive, old['documents']['context_id'])
        pins.append(migrate_binding(worker, archive, row['snapshot_id'], context, apply=True))
    previous = manifest['generation_id']
    manifest['generation_id'] = GenerationIndex(archive).publish(datetime.now(timezone.utc))
    assert previous != manifest['generation_id']
    manifest['previous_generation_id'] = previous
    manifest['bindings'] = pins
    manifest['binding_check'] = check_bindings(worker, archive)
    manifest['scope'] += '_legacy_context_migration_and_generation_rollover'
(args.destination / 'manifest.json').write_text(json.dumps(manifest, ensure_ascii=False, indent=2), encoding='utf-8')
print(json.dumps({'generation_id': manifest['generation_id'], 'bound_count': len(pins)}, ensure_ascii=False))
