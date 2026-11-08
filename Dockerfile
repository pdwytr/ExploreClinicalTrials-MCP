FROM python:3.12-slim

COPY --from=ghcr.io/astral-sh/uv:0.5.11 /uv /usr/local/bin/uv
ENV UV_COMPILE_BYTECODE=1 UV_LINK_MODE=copy PYTHONUNBUFFERED=1

WORKDIR /app
COPY pyproject.toml uv.lock README.md ./
RUN uv sync --frozen --no-dev --no-install-project
COPY src ./src
COPY docs ./docs
RUN uv sync --frozen --no-dev

ENV PATH="/app/.venv/bin:$PATH"
EXPOSE 8080
# 0.0.0.0 so Fly's proxy can reach it; 8080 matches internal_port in fly.toml
CMD ["uvicorn", "cheiron.api.app:app", "--host", "0.0.0.0", "--port", "8080"]
