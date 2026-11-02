"""Snapshot publication pins. No latest-generation or historical-time fallback."""
from datetime import datetime, timezone

from .index import GenerationIndex
from .schemas import digest, stamp


def publication(manifest):
    return {key: manifest[key] for key in ('as_of', 'committed_at', 'publication_sha256')}


def capture_binding(archive, snapshot, generation_id, *, source_context_id=None):
    db, manifest = GenerationIndex(archive).open(generation_id)
    db.close()
    cutoff = stamp(snapshot.created_at)
    if any(stamp(datetime.fromisoformat(manifest[key])) > cutoff for key in ('as_of', 'committed_at')):
        raise ValueError('publication follows snapshot')
    return dict(schema='snapshot-generation-v1', state='bound', snapshot_id=snapshot.snapshot_id,
        snapshot_hash=digest(snapshot.model_dump(mode='json')), generation_id=generation_id,
        publication=publication(manifest), source_context_id=source_context_id,
        bound_at=stamp(datetime.now(timezone.utc)))


def unavailable_binding(snapshot, generation_id):
    return dict(schema='snapshot-generation-v1', state='unavailable', snapshot_id=snapshot.snapshot_id,
        snapshot_hash=digest(snapshot.model_dump(mode='json')), generation_id=generation_id or '',
        bound_at=stamp(datetime.now(timezone.utc)))


def validate_binding(binding, snapshot, generation_id, manifest):
    if (binding.get('schema') != 'snapshot-generation-v1' or binding.get('state') != 'bound'
            or binding.get('snapshot_id') != snapshot.snapshot_id
            or binding.get('snapshot_hash') != digest(snapshot.model_dump(mode='json'))
            or binding.get('generation_id') != generation_id
            or binding.get('publication') != publication(manifest)):
        raise ValueError('snapshot publication binding mismatch')


def migrate_binding(worker, archive, snapshot_id, context, *, apply=False):
    """Explicit legacy migration using an existing successful observed context only."""
    from ..snapshot import Snapshot
    snapshot = Snapshot.model_validate(worker.snapshot(snapshot_id))
    payload = context.payload
    if (payload.get('snapshot_id') != snapshot_id
            or payload.get('snapshot_hash') != digest(snapshot.model_dump(mode='json'))
            or payload.get('time_policy') != 'observed-v1'
            or payload.get('status') not in {'completed', 'empty'}
            or payload.get('warnings')
            or not payload.get('generation_committed_at')
            or payload.get('evidence', {}).get('mode') == 'facts'):
        raise ValueError('migration requires matching observed document context')
    binding = capture_binding(archive, snapshot, payload['generation_id'], source_context_id=context.context_id)
    if (binding['publication']['committed_at'] != payload['generation_committed_at']
            or binding['publication']['as_of'] != payload['generation_as_of']):
        raise ValueError('original publication receipt required')
    old = worker.generation_binding(snapshot_id)
    if old is not None:
        if any(old.get(key) != binding.get(key) for key in ('snapshot_hash', 'generation_id', 'publication')):
            raise ValueError('existing binding cannot be replaced')
        return old
    if apply:
        return worker.bind_generation(snapshot_id, binding)
    return binding


def check_bindings(worker, archive):
    """Offline inventory for rollout/restore. Does not create or repair pins."""
    from ..snapshot import Snapshot
    rows = []
    for row in worker.db.execute('SELECT id,data FROM snapshots ORDER BY id').fetchall():
        snapshot = Snapshot.model_validate_json(row['data'])
        binding = worker.generation_binding(row['id'])
        result = dict(snapshot_id=row['id'], ticker=snapshot.ticker,
            generation_id=binding.get('generation_id') if binding else None,
            state=binding.get('state') if binding else 'unbound', ready=False)
        try:
            if binding is None or binding.get('state') != 'bound':
                raise ValueError('unbound')
            db, manifest = GenerationIndex(archive).open(binding['generation_id'])
            db.close()
            validate_binding(binding, snapshot, binding['generation_id'], manifest)
            cutoff = stamp(snapshot.created_at)
            if any(stamp(datetime.fromisoformat(manifest[key])) > cutoff for key in ('as_of', 'committed_at')):
                raise ValueError('future publication')
            result['ready'] = True
        except Exception:
            result['reason'] = 'binding_or_publication_unavailable'
        rows.append(result)
    return dict(schema='snapshot-bindings-check-v1', snapshots=rows,
        all_ready=all(row['ready'] for row in rows), snapshot_count=len(rows))
