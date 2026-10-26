"""AI 워커 HTTP 서버. `uvicorn bullbear.server:app`

app은 처음 접근할 때 만든다 (테스트가 create_app만 import해도 실제 데이터 소스가 생기지 않게).
"""

from __future__ import annotations


def __getattr__(name: str):
    if name == "app":
        from .app import create_app

        global app
        app = create_app()
        return app
    raise AttributeError(name)
