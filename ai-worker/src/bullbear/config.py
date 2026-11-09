from __future__ import annotations

import os
from dataclasses import dataclass, field
from pathlib import Path

from dotenv import load_dotenv


@dataclass(frozen=True)
class Settings:
    model: str
    dart_api_key: str | None = field(repr=False)
    naver_client_id: str | None = field(repr=False)
    naver_client_secret: str | None = field(repr=False)
    data_dir: Path
    debater_effort: str
    moderator_effort: str
    krx_api_key: str | None = field(default=None, repr=False)
    rag_enabled: bool = False
    rag_generation_id: str | None = None
    rag_profile: str = "knowledge-short-v1"
    rag_selection_policy: Path | None = field(default=None, repr=False)
    rag_shadow_selection_policy: Path | None = field(default=None, repr=False)
    rag_shadow_enabled: bool = False
    rag_shadow_spec: Path | None = field(default=None, repr=False)
    rag_shadow_prepare_query: bool = False
    rag_shadow_daily_budget_nano: int = 0
    rag_archive_backend: str = "sqlite"
    rag_object_backend: str = "local"
    rag_s3_bucket: str = ""
    rag_s3_prefix: str = "rag/objects"
    rag_s3_endpoint: str | None = field(default=None, repr=False)
    rag_context_backend: str = "sqlite"
    rag_postgres_dsn: str | None = field(default=None, repr=False)
    debater_model: str | None = None
    moderator_model: str | None = None
    worker_budget_usd: str | None = None
    worker_budget_id: str | None = None
    review_statements: bool = True

    @property
    def snapshot_dir(self) -> Path:
        return self.data_dir / "snapshots"

    @property
    def debate_dir(self) -> Path:
        return self.data_dir / "debates"

    @property
    def cache_dir(self) -> Path:
        return self.data_dir / "cache"


def load_settings() -> Settings:
    load_dotenv()
    return Settings(
        model=os.getenv("BULLBEAR_MODEL", "claude-sonnet-5-5"),
        dart_api_key=os.getenv("OPENDART_API_KEY") or None,
        naver_client_id=os.getenv("NAVER_CLIENT_ID") or None,
        naver_client_secret=os.getenv("NAVER_CLIENT_SECRET") or None,
        data_dir=Path(os.getenv("BULLBEAR_DATA_DIR", "data")),
        debater_effort=os.getenv("BULLBEAR_DEBATER_EFFORT", "medium"),
        moderator_effort=os.getenv("BULLBEAR_MODERATOR_EFFORT", "high"),
        krx_api_key=os.getenv("KRX_API_KEY") or None,
        rag_enabled=os.getenv("BULLBEAR_RAG_ENABLED", "false").strip().lower() == "true",
        rag_generation_id=os.getenv("BULLBEAR_RAG_GENERATION_ID") or None,
        rag_profile=os.getenv("BULLBEAR_RAG_PROFILE", "knowledge-short-v1"),
        rag_selection_policy=Path(os.environ["BULLBEAR_RAG_SELECTION_POLICY"]) if os.getenv("BULLBEAR_RAG_SELECTION_POLICY") else None,
        rag_shadow_selection_policy=Path(os.environ["BULLBEAR_RAG_SHADOW_SELECTION_POLICY"]) if os.getenv("BULLBEAR_RAG_SHADOW_SELECTION_POLICY") else None,
        rag_shadow_enabled=os.getenv("BULLBEAR_RAG_SHADOW_ENABLED", "false").strip().lower() == "true",
        rag_shadow_spec=Path(os.environ["BULLBEAR_RAG_SHADOW_SPEC"]) if os.getenv("BULLBEAR_RAG_SHADOW_SPEC") else None,
        rag_shadow_prepare_query=os.getenv("BULLBEAR_RAG_SHADOW_PREPARE_QUERY", "false").strip().lower() == "true",
        rag_shadow_daily_budget_nano=int(os.getenv("BULLBEAR_RAG_SHADOW_DAILY_BUDGET_NANO", "0")),
        rag_archive_backend=os.getenv("BULLBEAR_RAG_ARCHIVE_BACKEND", "sqlite").strip().lower(),
        rag_object_backend=os.getenv("BULLBEAR_RAG_OBJECT_BACKEND", "local").strip().lower(),
        rag_s3_bucket=os.getenv("BULLBEAR_RAG_S3_BUCKET", ""),
        rag_s3_prefix=os.getenv("BULLBEAR_RAG_S3_PREFIX", "rag/objects"),
        rag_s3_endpoint=os.getenv("BULLBEAR_RAG_S3_ENDPOINT") or None,
        rag_context_backend=os.getenv("BULLBEAR_RAG_CONTEXT_BACKEND", "sqlite").strip().lower(),
        rag_postgres_dsn=os.getenv("BULLBEAR_RAG_POSTGRES_DSN") or None,
        debater_model=os.getenv("BULLBEAR_DEBATER_MODEL") or os.getenv("BULLBEAR_MODEL", "claude-sonnet-5-5"),
        moderator_model=os.getenv("BULLBEAR_MODERATOR_MODEL") or os.getenv("BULLBEAR_MODEL", "claude-sonnet-5-5"),
        worker_budget_usd=os.getenv("BULLBEAR_WORKER_BUDGET_USD") or None,
        worker_budget_id=os.getenv("BULLBEAR_WORKER_BUDGET_ID") or None,
        review_statements=os.getenv("BULLBEAR_REVIEW_STATEMENTS", "true").strip().lower() == "true",
    )
