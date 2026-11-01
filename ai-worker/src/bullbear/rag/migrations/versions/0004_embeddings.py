"""Versioned embedding cache and append-only budget reservations/receipts.

pgvector itself is installed explicitly, so BM25-only deployments still migrate.
"""
from alembic import op

revision = "0004_rag_embeddings"
down_revision = "0003_rag_ingest_jobs"
branch_labels = None
depends_on = None


def upgrade():
    op.execute("""CREATE TABLE rag.embedding_versions (
        version_id TEXT PRIMARY KEY, spec_json TEXT NOT NULL)""")
    op.execute("""CREATE TABLE rag.embedding_calls (
        call_id TEXT PRIMARY KEY, version_id TEXT NOT NULL REFERENCES rag.embedding_versions,
        input_hash TEXT NOT NULL, role TEXT NOT NULL CHECK(role IN ('document','query')),
        reserved_nano BIGINT NOT NULL CHECK(reserved_nano>=0),
        token_bound INTEGER NOT NULL CHECK(token_bound>0),
        price_revision TEXT NOT NULL, nano_usd_per_token BIGINT NOT NULL CHECK(nano_usd_per_token>=0),
        created_at TIMESTAMPTZ NOT NULL DEFAULT clock_timestamp())""")
    op.execute("""CREATE TABLE rag.embedding_receipts (
        call_id TEXT PRIMARY KEY REFERENCES rag.embedding_calls,
        input_tokens INTEGER NOT NULL CHECK(input_tokens>=0), cost_nano BIGINT NOT NULL CHECK(cost_nano>=0),
        status TEXT NOT NULL CHECK(status IN ('completed','invalid_response')),
        stored_at TIMESTAMPTZ NOT NULL DEFAULT clock_timestamp())""")
    op.execute("""CREATE TABLE rag.embeddings (
        embedding_id TEXT PRIMARY KEY REFERENCES rag.embedding_calls(call_id),
        version_id TEXT NOT NULL REFERENCES rag.embedding_versions,
        vector_json TEXT NOT NULL, vector_hash TEXT NOT NULL,
        stored_at TIMESTAMPTZ NOT NULL DEFAULT clock_timestamp())""")
    op.execute("""CREATE TABLE rag.vector_generations (
        vector_generation_id TEXT PRIMARY KEY, generation_id TEXT NOT NULL,
        version_id TEXT NOT NULL REFERENCES rag.embedding_versions,
        manifest_json TEXT NOT NULL, ready_at TIMESTAMPTZ NOT NULL DEFAULT clock_timestamp(),
        UNIQUE(generation_id,version_id))""")
    op.execute("CREATE INDEX embedding_calls_date ON rag.embedding_calls(created_at)")
    for table in ("embedding_versions", "embedding_calls", "embedding_receipts", "embeddings", "vector_generations"):
        op.execute(f"CREATE TRIGGER immutable_{table} BEFORE UPDATE OR DELETE ON rag.{table} "
                   "FOR EACH ROW EXECUTE FUNCTION rag.reject_context_mutation()")
        op.execute(f"CREATE TRIGGER immutable_{table}_truncate BEFORE TRUNCATE ON rag.{table} "
                   "FOR EACH STATEMENT EXECUTE FUNCTION rag.reject_context_mutation()")


def downgrade():
    raise RuntimeError("destructive embedding downgrade is unsupported")
