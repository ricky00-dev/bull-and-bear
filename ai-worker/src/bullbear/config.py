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
    # HTTP 서버 (bullbear.server)
    worker_token: str = "dev-worker-token"
    max_concurrent_debates: int = 3  # 동시에 실제로 도는 토론. Anthropic 속도 제한·메모리 기준
    max_queued_debates: int = 10  # 대기열까지 합쳐 이보다 많으면 BUSY(429)
    agents: str = "llm"  # llm | scripted (LLM 없이 연동 확인용, server/scripted.py)

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
        worker_token=os.getenv("WORKER_TOKEN", "dev-worker-token"),
        max_concurrent_debates=int(os.getenv("BULLBEAR_MAX_CONCURRENT_DEBATES", "3")),
        max_queued_debates=int(os.getenv("BULLBEAR_MAX_QUEUED_DEBATES", "10")),
        agents=os.getenv("BULLBEAR_AGENTS", "llm"),
    )
