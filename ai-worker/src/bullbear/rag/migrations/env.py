"""Use the caller's transaction; never read a global application database URL."""
from alembic import context

connection = context.config.attributes.get("connection")
if connection is None:
    raise RuntimeError("use python -m bullbear.rag.storage migrate")
context.configure(connection=connection, version_table="rag_alembic_version", version_table_schema="public", transactional_ddl=True)
with context.begin_transaction():
    context.run_migrations()
