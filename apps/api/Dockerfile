FROM python:3.11-slim-bookworm AS builder

COPY --from=ghcr.io/astral-sh/uv:0.11.15 /uv /uvx /bin/

ENV UV_COMPILE_BYTECODE=1 \
    UV_LINK_MODE=copy \
    UV_PYTHON_DOWNLOADS=never

WORKDIR /app

# Install dependencies first (separate layer from app source so source edits don't
# bust the dependency cache). BuildKit cache/bind mounts were removed so this image
# builds on non-BuildKit builders too (e.g. Cloud Build's default docker daemon).
COPY uv.lock pyproject.toml ./
RUN uv sync --locked --no-install-project --no-dev

COPY . /app

RUN uv sync --locked --no-dev

FROM python:3.11-slim-bookworm

RUN useradd --create-home --uid 1000 appuser
WORKDIR /app
COPY --from=builder --chown=appuser:appuser /app /app

ENV PATH="/app/.venv/bin:$PATH"
USER appuser

EXPOSE 8000

CMD ["uvicorn", "api.main:app", "--host", "0.0.0.0", "--port", "8000"]
