"""토론 이벤트 기록.

스냅샷, 발언 시도, 검증 결과, 중재자 판단, 사용자 판정을 순서대로 JSONL에 덧붙인다.
이 파일만으로 "그때 왜 그렇게 판정했는지"를 재생할 수 있어야 한다. 기존 줄은 고치지 않는다.
"""

from __future__ import annotations

import json
from datetime import datetime
from pathlib import Path
from typing import Any

from pydantic import BaseModel


def _default(obj: Any) -> Any:
    if isinstance(obj, BaseModel):
        return obj.model_dump(mode="json")
    if hasattr(obj, "isoformat"):
        return obj.isoformat()
    if hasattr(obj, "value"):  # Enum
        return obj.value
    raise TypeError(f"직렬화할 수 없는 타입: {type(obj)}")


class EventLog:
    def __init__(self, path: Path):
        self.path = path
        self.path.parent.mkdir(parents=True, exist_ok=True)
        self._seq = sum(1 for _ in path.open()) if path.exists() else 0

    def append(self, type_: str, **payload: Any) -> None:
        self._seq += 1
        record = {"seq": self._seq, "ts": datetime.now().astimezone().isoformat(), "type": type_, **payload}
        with self.path.open("a") as f:
            f.write(json.dumps(record, ensure_ascii=False, default=_default) + "\n")

    @staticmethod
    def read(path: Path) -> list[dict]:
        return [json.loads(line) for line in path.read_text().splitlines() if line.strip()]
