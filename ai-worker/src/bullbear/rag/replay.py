"""Replay facade; defaults to the existing archive-local SQLite file."""
from .context import KnowledgeContext
from .context_repository import ContextRepository, SQLiteContextRepository


def _repository(store, repository):
    return repository if repository is not None else SQLiteContextRepository(store.directory / "contexts.sqlite3")


def save_context(store, context: KnowledgeContext, audit: dict, *, repository: ContextRepository | None = None) -> str:
    return _repository(store, repository).save(context, audit)


def load_context(store, context_id: str, *, repository: ContextRepository | None = None) -> KnowledgeContext:
    return _repository(store, repository).load(context_id)


def retrieval_audits(store, context_id: str, *, repository: ContextRepository | None = None) -> list[dict]:
    return _repository(store, repository).audits(context_id)
