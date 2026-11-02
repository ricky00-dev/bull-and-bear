# AI 워커 HTTP/SSE 서버. 데이터 볼륨당 단일 프로세스로 실행한다.
FROM ghcr.io/astral-sh/uv:python3.12-bookworm-slim
WORKDIR /app
ENV UV_COMPILE_BYTECODE=1 UV_LINK_MODE=copy
COPY pyproject.toml uv.lock README.md ./
RUN uv sync --frozen --no-dev --no-install-project --extra rag-postgres
COPY src src
RUN uv sync --frozen --no-dev --extra rag-postgres
RUN useradd --system --create-home --uid 1001 app && mkdir -p /app/data && chown app /app/data
USER app
# uv 없이 가상환경을 바로 쓴다 (실행 사용자에게 uv 캐시 디렉터리가 필요 없게)
ENV PATH="/app/.venv/bin:$PATH"
EXPOSE 8000
CMD ["uvicorn", "bullbear.server:app", "--host", "0.0.0.0", "--port", "8000"]
