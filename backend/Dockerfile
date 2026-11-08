# Code a Cuisine backend (FastAPI). Built and run via docker-compose.yml.
FROM python:3.12-slim

# uv installs the exact versions from uv.lock.
COPY --from=ghcr.io/astral-sh/uv:0.13.7 /uv /bin/uv

ENV PYTHONDONTWRITEBYTECODE=1 \
    PYTHONUNBUFFERED=1 \
    UV_COMPILE_BYTECODE=1 \
    UV_LINK_MODE=copy \
    UV_PROJECT_ENVIRONMENT=/app/.venv \
    PATH="/app/.venv/bin:$PATH"

WORKDIR /app

# Dependencies first (cached layer), then the code.
COPY pyproject.toml uv.lock .python-version ./
RUN uv sync --frozen --no-dev --no-install-project

# Run as non-root user.
RUN useradd --create-home --uid 10001 app && mkdir -p /app/data && chown -R app /app
USER app
ENV ANONYMIZED_TELEMETRY=False

# Build the vector index (recipes + USDA foods) into the image. Only the files
# the index needs are copied first, so changes to agents or the API reuse this
# cached layer instead of re-embedding ~7,500 texts (several minutes).
# This also downloads the small embedding model (all-MiniLM-L6-v2, ONNX, ~80 MB),
# so the container needs no network access for search at runtime.
COPY --chown=app core/__init__.py core/config.py core/schemas.py core/recipes.py core/retrieval.py core/nutrition.py ./core/
COPY --chown=app ingest/__init__.py ingest/build_index.py ./ingest/
COPY --chown=app data/recipes.jsonl data/usda_foods.jsonl ./data/
RUN python -m ingest.build_index

COPY --chown=app core ./core
COPY --chown=app api ./api

EXPOSE 8000

HEALTHCHECK --interval=30s --timeout=5s --start-period=10s --retries=3 \
    CMD python -c "import urllib.request; urllib.request.urlopen('http://127.0.0.1:8000/health', timeout=3)"

# --proxy-headers: read the real client IP from the reverse proxy (X-Forwarded-For).
# Which proxies are trusted is set via FORWARDED_ALLOW_IPS in docker-compose.yml.
CMD ["uvicorn", "api.main:app", "--host", "0.0.0.0", "--port", "8000", "--proxy-headers"]
