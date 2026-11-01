"""Durable captured-batch queue and immutable attempt events."""
from alembic import op

revision = "0003_rag_ingest_jobs"
down_revision = "0002_rag_archive"
branch_labels = None
depends_on = None

SCHEMA = """
CREATE TABLE IF NOT EXISTS ingest_jobs (
 job_id TEXT PRIMARY KEY, collection_id TEXT NOT NULL UNIQUE,
 source TEXT NOT NULL, query_key TEXT NOT NULL, ticker TEXT NOT NULL,
 window_start TEXT NOT NULL, window_end TEXT NOT NULL,
 fingerprint TEXT NOT NULL, payload TEXT NOT NULL,
 state TEXT NOT NULL CHECK(state IN ('pending','running','retry','succeeded','partial','failed')),
 attempts INTEGER NOT NULL, max_attempts INTEGER NOT NULL,
 available_at TEXT NOT NULL, lease_until TEXT, lease_token TEXT,
 created_at TEXT NOT NULL, updated_at TEXT NOT NULL, safe_error TEXT);
CREATE INDEX IF NOT EXISTS ingest_jobs_due ON ingest_jobs(state,available_at,lease_until);
CREATE INDEX IF NOT EXISTS ingest_jobs_scope ON ingest_jobs(source,query_key,state,window_start,window_end);
CREATE TABLE IF NOT EXISTS ingest_attempts (
 event_id TEXT PRIMARY KEY, job_id TEXT NOT NULL REFERENCES ingest_jobs(job_id),
 lease_token TEXT NOT NULL, attempt INTEGER NOT NULL, event TEXT NOT NULL,
 occurred_at TEXT NOT NULL, safe_error TEXT);
CREATE INDEX IF NOT EXISTS ingest_attempts_job ON ingest_attempts(job_id,attempt,occurred_at);
"""


def upgrade():
    op.execute("SET LOCAL search_path TO rag, pg_catalog")
    for statement in SCHEMA.split(";"):
        if statement.strip():
            op.execute(statement)
    op.execute("CREATE TRIGGER immutable_ingest_attempts BEFORE UPDATE OR DELETE ON rag.ingest_attempts "
               "FOR EACH ROW EXECUTE FUNCTION rag.reject_context_mutation()")
    op.execute("CREATE TRIGGER immutable_ingest_attempts_truncate BEFORE TRUNCATE ON rag.ingest_attempts "
               "FOR EACH STATEMENT EXECUTE FUNCTION rag.reject_context_mutation()")


def downgrade():
    raise RuntimeError("destructive ingestion downgrade is unsupported")
