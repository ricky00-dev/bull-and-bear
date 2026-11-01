"""Exact pgvector search over a sealed, fully embedded generation. No ANN index."""
import json
import math
from datetime import datetime

from .embeddings import EmbeddingService, EmbeddingUnavailable, checked_vector
from .index import GenerationIndex
from .objects import ArchiveCorruptError
from .schemas import canonical_json, digest, stamp


def install_vectors(dsn):
    """Explicit migration privilege operation; never run by search workers."""
    from .context_repository import PostgresContextRepository
    with PostgresContextRepository(dsn)._connection() as db:
        db.execute("SELECT pg_advisory_xact_lock(7348201101)")
        db.execute("CREATE EXTENSION IF NOT EXISTS vector WITH SCHEMA public")
        schema = db.execute("SELECT n.nspname FROM pg_extension e JOIN pg_namespace n ON n.oid=e.extnamespace WHERE e.extname='vector'").fetchone()[0]
        if schema != "public":
            raise ValueError("pgvector must be installed in public schema")
        db.execute("""CREATE TABLE IF NOT EXISTS rag.embedding_vectors (
            embedding_id TEXT PRIMARY KEY REFERENCES rag.embeddings(embedding_id),
            embedding public.vector NOT NULL,
            dimensions INTEGER NOT NULL CHECK(public.vector_dims(embedding)=dimensions))""")
        for name, clause in (("immutable_embedding_vectors", "BEFORE UPDATE OR DELETE FOR EACH ROW"),
                             ("immutable_embedding_vectors_truncate", "BEFORE TRUNCATE FOR EACH STATEMENT")):
            if not db.execute("SELECT 1 FROM pg_trigger WHERE tgrelid='rag.embedding_vectors'::regclass AND tgname=%s", (name,)).fetchone():
                before, each = clause.split(" FOR ")
                db.execute(f"CREATE TRIGGER {name} {before} ON rag.embedding_vectors FOR {each} EXECUTE FUNCTION rag.reject_context_mutation()")


class VectorIndex:
    def __init__(self, embeddings: EmbeddingService):
        self.embeddings = embeddings

    @property
    def version_id(self):
        return self.embeddings.spec.version_id

    def build(self, store, generation_id, *, daily_budget_nano):
        with self.embeddings.repository._connection() as connection:
            if connection.execute("SELECT to_regclass('rag.embedding_vectors')").fetchone()[0] is None:
                raise EmbeddingUnavailable("install pgvector storage before embedding calls")
        db, manifest = GenerationIndex(store).open(generation_id)
        db.close()
        members = {}
        for member in manifest["members"]:
            key, vector = self.embeddings.prepare(member["text"], "document", daily_budget_nano=daily_budget_nano)
            with self.embeddings.repository._connection() as db:
                db.execute("INSERT INTO rag.embedding_vectors VALUES (%s,%s::public.vector,%s) ON CONFLICT DO NOTHING",
                           (key, canonical_json(vector), len(vector)))
                saved = db.execute("SELECT embedding::text FROM rag.embedding_vectors WHERE embedding_id=%s", (key,)).fetchone()[0]
                if checked_vector(json.loads(saved), len(vector)) != vector:
                    raise ArchiveCorruptError("pgvector value differs from immutable cache")
            members[member["chunk_id"]] = {"embedding_id": key, "vector_hash": digest(vector)}
        payload = {"generation_id": generation_id, "embedding_version": self.version_id, "members": members}
        vector_generation_id = "VG." + digest(payload)
        with self.embeddings.repository._connection() as db:
            # Empty generations still need a registered version (no provider calls).
            db.execute("INSERT INTO rag.embedding_versions VALUES (%s,%s) ON CONFLICT DO NOTHING", (
                self.version_id, canonical_json(self.embeddings.spec.semantic_spec())))
            db.execute("INSERT INTO rag.vector_generations(vector_generation_id,generation_id,version_id,manifest_json) VALUES (%s,%s,%s,%s) ON CONFLICT DO NOTHING",
                       (vector_generation_id, generation_id, self.version_id, canonical_json(payload)))
        return vector_generation_id

    def distances(self, eligible, generation_id, manifest, query_text, *, cutoff, time_policy):
        # Cache only: no network embedding request can outlive a search timeout and charge later.
        query_id, query = self.embeddings.cached(query_text, "query")
        with self.embeddings.repository._connection() as db:
            rows = db.execute("SELECT vector_generation_id,manifest_json,ready_at FROM rag.vector_generations WHERE generation_id=%s AND version_id=%s",
                              (generation_id, self.version_id)).fetchall()
            if len(rows) != 1:
                raise EmbeddingUnavailable("complete vector generation not ready")
            vector_id, payload_json, ready_at = rows[0]
            payload = json.loads(payload_json)
            if "VG." + digest(payload) != vector_id:
                raise ArchiveCorruptError("vector manifest hash mismatch")
            if payload["generation_id"] != generation_id or payload["embedding_version"] != self.version_id:
                raise ArchiveCorruptError("vector manifest version mismatch")
            if time_policy == "observed-v1" and stamp(ready_at) > cutoff:
                raise EmbeddingUnavailable("vector generation not ready at decision")
            expected = {m["chunk_id"]: self.embeddings.input(m["text"], "document")[2] for m in manifest["members"]}
            if {k: v["embedding_id"] for k, v in payload["members"].items()} != expected:
                raise ArchiveCorruptError("vector generation membership mismatch")
            keys = list({expected[m["chunk_id"]] for m in eligible.values()})
            values = db.execute("""SELECT v.embedding_id,v.embedding OPERATOR(public.<=>) %s::public.vector,
                v.embedding::text,e.vector_hash FROM rag.embedding_vectors v JOIN rag.embeddings e USING(embedding_id)
                WHERE v.embedding_id=ANY(%s)""", (canonical_json(query), keys)).fetchall() if keys else []
            if len(values) != len(keys):
                raise EmbeddingUnavailable("vector generation incomplete")
        scores = {}
        for key, distance, vector_json, vector_hash in values:
            vector = checked_vector(json.loads(vector_json), self.embeddings.spec.dimensions)
            if not math.isfinite(distance) or digest(vector) != vector_hash:
                raise ArchiveCorruptError("vector search integrity failure")
            scores[key] = (float(distance), vector_hash)
        for member in eligible.values():
            record = payload["members"][member["chunk_id"]]
            if scores[record["embedding_id"]][1] != record["vector_hash"]:
                raise ArchiveCorruptError("vector membership hash mismatch")
        return {rowid: scores[expected[m["chunk_id"]]][0] for rowid, m in eligible.items()}, {
            "vector_generation_id": vector_id, "embedding_version": self.version_id,
            "query_embedding_id": query_id, "vector_ready_at": stamp(ready_at), "distance": "cosine_exact"}


def ranked_rows(lexical, grades, distances, strategy, *, limit=20):
    """Keep suitability priority for every strategy; fuse ranks, never raw scores."""
    bm25 = {int(r["rowid"]): float(r["score"]) for r in lexical}
    dense = sorted((int(i) for i in grades), key=lambda i: (grades[str(i)], distances[i], i))[:limit]
    dense_rank = {i: rank for rank, i in enumerate(dense, 1)}
    lexical_rank = {int(r["rowid"]): rank for rank, r in enumerate(lexical, 1)}
    ids = set(dense) if strategy == "dense" else set(dense) | set(lexical_rank)
    rrf = {i: (1 / (60 + dense_rank[i]) if i in dense_rank else 0) +
              (1 / (60 + lexical_rank[i]) if i in lexical_rank else 0) for i in ids}
    order = sorted(ids, key=lambda i: (grades[str(i)], distances[i] if strategy == "dense" else -rrf[i], i))[:limit]
    return [{"rowid": i, "score": bm25.get(i), "grade": grades[str(i)], "cosine_distance": distances[i],
             "rrf": rrf[i] if strategy == "hybrid" else None} for i in order]
