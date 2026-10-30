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
    debater_model: str | None = None
    moderator_model: str | None = None

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
        debater_model=os.getenv("BULLBEAR_DEBATER_MODEL") or os.getenv("BULLBEAR_MODEL", "claude-haiku-5-5"),
        moderator_model=os.getenv("BULLBEAR_MODERATOR_MODEL") or os.getenv("BULLBEAR_MODEL", "claude-sonnet-5-5"),
    )
