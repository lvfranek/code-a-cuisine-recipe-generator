"""FastAPI app for the Code a Cuisine frontend.

Start locally (from the backend/ folder):
    uv run uvicorn api.main:app --reload --port 8000
"""

from fastapi import FastAPI

app = FastAPI(
    title="Code a Cuisine API",
    version="0.1.0",
    description="Recipe generation backend for Code a Cuisine.",
)


@app.get("/health")
def health() -> dict[str, str]:
    """Simple liveness check for local testing, Docker and the reverse proxy."""
    return {"status": "ok"}
