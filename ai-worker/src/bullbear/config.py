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
        debater_model=os.getenv("BULLBEAR_DEBATER_MODEL") or os.getenv("BULLBEAR_MODEL", "claude-sonnet-5-5"),
        moderator_model=os.getenv("BULLBEAR_MODERATOR_MODEL") or os.getenv("BULLBEAR_MODEL", "claude-sonnet-5-5"),
        worker_budget_usd=os.getenv("BULLBEAR_WORKER_BUDGET_USD") or None,
        worker_budget_id=os.getenv("BULLBEAR_WORKER_BUDGET_ID") or None,
        review_statements=os.getenv("BULLBEAR_REVIEW_STATEMENTS", "true").strip().lower() == "true",
    )
