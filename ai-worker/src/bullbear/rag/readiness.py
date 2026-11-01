"""Read-only publication checks. Never backdate snapshots or select a newer index."""
from datetime import datetime, timezone
from .index import GenerationIndex
from .schemas import stamp


def check_generation(store, generation_id, *, at=None, snapshots=()):
    checked_at = stamp(at or datetime.now(timezone.utc))
    db, manifest = GenerationIndex(store).open(generation_id)
    db.close()
    as_of = stamp(datetime.fromisoformat(manifest['as_of']))
    committed = stamp(datetime.fromisoformat(manifest['committed_at']))

    def reasons(cutoff):
        return (["future_generation"] if as_of > cutoff else []) + (
            ["generation_not_committed_at_decision"] if committed > cutoff else [])

    results = []
    for snapshot in snapshots:
        cutoff = stamp(snapshot.created_at)
        problems = reasons(cutoff)
        results.append(dict(snapshot_id=snapshot.snapshot_id, ticker=snapshot.ticker,
            created_at=cutoff, eligible=not problems, reasons=problems))
    problems = reasons(checked_at)
    return dict(schema='generation-readiness-v1', generation_id=generation_id,
        checked_at=checked_at, generation_as_of=as_of, committed_at=committed,
        member_count=len(manifest['members']), ready_for_new_snapshot=not problems,
        reasons=problems, snapshots=results,
        all_snapshots_eligible=all(row['eligible'] for row in results))


def require_ready_generation(settings):
    """Gate only new snapshot collection; existing snapshots keep their old cutoff."""
    if not settings.rag_generation_id:
        raise ValueError('RAG requires an explicit published generation before snapshot collection')
    from .archive_repository import configured_archive
    with configured_archive(settings) as store:
        result = check_generation(store, settings.rag_generation_id)
    if not result['ready_for_new_snapshot']:
        raise ValueError('RAG generation is not ready before snapshot collection')
    return result
