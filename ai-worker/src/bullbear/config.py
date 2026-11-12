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
    fred_api_key: str | None = field(default=None, repr=False)
    ecos_api_key: str | None = field(default=None, repr=False)
    vix_enabled: bool = False
    market_news_limit: int = 8
    stock_news_limit: int = 30
    news_web_fetch_enabled: bool = False

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
        fred_api_key=os.getenv("FRED_API_KEY") or None,
        ecos_api_key=os.getenv("ECOS_API_KEY") or None,
        vix_enabled=os.getenv("BULLBEAR_VIX_ENABLED", "false").strip().lower() == "true",
        market_news_limit=_news_limit("BULLBEAR_MARKET_NEWS_LIMIT", 8),
        stock_news_limit=_news_limit("BULLBEAR_STOCK_NEWS_LIMIT", 30),
        news_web_fetch_enabled=os.getenv("BULLBEAR_NEWS_WEB_FETCH_ENABLED", "false").strip().lower() == "true",
    )


def _news_limit(name: str, default: int) -> int:
    value = int(os.getenv(name, str(default)))
    if not 0 <= value <= 30:
        raise ValueError(f"{name} must be between 0 and 30")
    return value
