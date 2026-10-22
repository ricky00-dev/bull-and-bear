from __future__ import annotations

import os
from dataclasses import dataclass
from pathlib import Path

from dotenv import load_dotenv


@dataclass(frozen=True)
class Settings:
    model: str
    dart_api_key: str | None
    naver_client_id: str | None
    naver_client_secret: str | None
    data_dir: Path
    debater_effort: str
    moderator_effort: str

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
        model=os.getenv("BULLBEAR_MODEL", "claude-opus-5-5"),
        dart_api_key=os.getenv("OPENDART_API_KEY") or None,
        naver_client_id=os.getenv("NAVER_CLIENT_ID") or None,
        naver_client_secret=os.getenv("NAVER_CLIENT_SECRET") or None,
        data_dir=Path(os.getenv("BULLBEAR_DATA_DIR", "data")),
        debater_effort=os.getenv("BULLBEAR_DEBATER_EFFORT", "medium"),
        moderator_effort=os.getenv("BULLBEAR_MODERATOR_EFFORT", "high"),
    )
