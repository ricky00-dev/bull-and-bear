"""Append-only private contexts and retrieval attempts; no market or user tables."""
from alembic import op

revision = "0001_rag_contexts"
down_revision = None
branch_labels = None
depends_on = None


def upgrade():
    op.execute("CREATE SCHEMA IF NOT EXISTS rag")
    op.execute(r"""CREATE TABLE rag.contexts (
        id TEXT PRIMARY KEY CHECK (id ~ '^KCTX\.[0-9a-f]{64}$'),
        payload TEXT NOT NULL,
        stored_at TIMESTAMPTZ NOT NULL DEFAULT clock_timestamp()
    )""")
    op.execute(r"""CREATE TABLE rag.searches (
        seq BIGINT GENERATED ALWAYS AS IDENTITY UNIQUE,
        id TEXT PRIMARY KEY CHECK (id ~ '^SEARCH\.[0-9a-f]{32}$'),
        context_id TEXT NOT NULL REFERENCES rag.contexts(id),
        payload TEXT NOT NULL,
        stored_at TIMESTAMPTZ NOT NULL DEFAULT clock_timestamp()
    )""")
    op.execute("CREATE INDEX rag_searches_context_seq ON rag.searches(context_id, seq)")
    op.execute("""CREATE FUNCTION rag.reject_context_mutation() RETURNS trigger
        LANGUAGE plpgsql AS $$ BEGIN RAISE EXCEPTION 'RAG records are immutable'; END $$""")
    for table in ("contexts", "searches"):
        op.execute(f"CREATE TRIGGER immutable_{table} BEFORE UPDATE OR DELETE ON rag.{table} "
                   "FOR EACH ROW EXECUTE FUNCTION rag.reject_context_mutation()")
        op.execute(f"CREATE TRIGGER immutable_{table}_truncate BEFORE TRUNCATE ON rag.{table} "
                   "FOR EACH STATEMENT EXECUTE FUNCTION rag.reject_context_mutation()")


def downgrade():
    raise RuntimeError("destructive RAG downgrade is unsupported; restore a verified backup")
