# AI 워커. FastAPI 서버(bullbear.server:app)가 완성되면 그대로 뜬다 — 담당 jangwonii
# 의존성에 fastapi, uvicorn을 추가해야 한다 (docs/DEPLOY.md)
FROM ghcr.io/astral-sh/uv:python3.12-bookworm-slim
WORKDIR /app
ENV UV_COMPILE_BYTECODE=1 UV_LINK_MODE=copy
COPY pyproject.toml uv.lock README.md ./
RUN uv sync --frozen --no-dev --no-install-project
COPY src src
RUN uv sync --frozen --no-dev
RUN useradd --system --create-home --uid 1001 app && mkdir -p /app/data && chown app /app/data
USER app
# uv 없이 가상환경을 바로 쓴다 (실행 사용자에게 uv 캐시 디렉터리가 필요 없게)
ENV PATH="/app/.venv/bin:$PATH"
EXPOSE 8000
CMD ["uvicorn", "bullbear.server:app", "--host", "0.0.0.0", "--port", "8000"]
