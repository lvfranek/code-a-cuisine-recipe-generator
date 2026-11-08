"""FastAPI app for the Code a Cuisine frontend.

Start locally (from the backend/ folder):
    uv run uvicorn api.main:app --reload --port 8000
"""

import json
import logging

from fastapi import FastAPI, Request
from fastapi.middleware.cors import CORSMiddleware
from fastapi.responses import JSONResponse
from pydantic import ValidationError

from core.config import get_settings
from core.generate import generate_recipes
from core.ratelimit import create_rate_limiter, hash_ip
from core.schemas import MAX_BODY_BYTES, GenerateRequest

logging.basicConfig(level=logging.INFO, format="%(levelname)s %(name)s: %(message)s")
log = logging.getLogger("api")

settings = get_settings()

app = FastAPI(
    title="Code a Cuisine API",
    version="0.2.0",
    description="Recipe generation backend for Code a Cuisine.",
)

app.add_middleware(
    CORSMiddleware,
    allow_origins=settings.origins,
    allow_methods=["GET", "POST"],
    allow_headers=["Content-Type", "X-CAC-Client"],
    expose_headers=["X-RateLimit-Remaining", "Retry-After"],
    max_age=600,
)

limiter = create_rate_limiter(
    redis_url=settings.redis_url,
    per_ip_daily=settings.ratelimit_per_ip_daily,
    per_ip_burst=settings.ratelimit_per_ip_burst,
    global_daily=settings.ratelimit_global_daily,
)

BASE_HEADERS = {"X-Content-Type-Options": "nosniff", "Cache-Control": "no-store"}


def error_response(status: int, message: str, headers: dict | None = None, **extra) -> JSONResponse:
    return JSONResponse({"error": message, **extra}, status_code=status, headers={**BASE_HEADERS, **(headers or {})})


def first_error_message(err: ValidationError) -> str:
    msg = err.errors()[0].get("msg", "Invalid request.")
    return msg.removeprefix("Value error, ")


@app.get("/health")
def health() -> dict[str, str]:
    """Simple liveness check for local testing, Docker and the reverse proxy."""
    return {"status": "ok"}


@app.post("/generate")
async def generate(request: Request) -> JSONResponse:
    # Trims drive-by bot traffic. Not a security boundary; the rate limit is.
    if request.headers.get("x-cac-client") != "web":
        return error_response(403, "Forbidden")

    declared = request.headers.get("content-length", "0")
    if declared.isdigit() and int(declared) > MAX_BODY_BYTES:
        return error_response(413, "Request body too large")
    body = await request.body()
    if len(body) > MAX_BODY_BYTES:
        return error_response(413, "Request body too large")

    if not get_settings().openrouter_api_key:
        return error_response(500, "OPENROUTER_API_KEY is not configured")

    try:
        raw = json.loads(body or b"{}")
    except ValueError:
        return error_response(400, "Invalid JSON body")
    if not isinstance(raw, dict):
        return error_response(400, "Request body must be a JSON object.")

    try:
        payload = GenerateRequest.model_validate(raw)
    except ValidationError as err:
        return error_response(400, first_error_message(err))

    client_ip = request.client.host if request.client else "unknown"
    limit = await limiter.check(hash_ip(client_ip))
    if not limit.ok:
        return error_response(429, limit.error, {"Retry-After": str(limit.retry_after)}, scope=limit.scope)

    try:
        result = await generate_recipes(payload)
    except Exception:
        log.exception("Recipe generation failed")
        return error_response(502, "Could not generate recipes right now. Please try again.")

    return JSONResponse(
        result.model_dump(),
        headers={**BASE_HEADERS, "X-RateLimit-Remaining": str(limit.remaining)},
    )
