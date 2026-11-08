FROM python:3.12-slim

COPY --from=ghcr.io/astral-sh/uv:latest /uv /usr/local/bin/uv

WORKDIR /srv
COPY pyproject.toml uv.lock .python-version ./
RUN uv sync --frozen --no-dev --no-install-project

COPY app ./app

# One worker only: cases live in memory and the poll loops must not run twice.
CMD ["sh", "-c", "exec .venv/bin/uvicorn app.main:app --host 0.0.0.0 --port ${PORT:-8000} --workers 1"]
