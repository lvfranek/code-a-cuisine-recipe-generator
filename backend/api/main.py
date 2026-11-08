"""FastAPI app for the Code a Cuisine frontend.

Start locally (from the backend/ folder):
    uv run uvicorn api.main:app --reload --port 8000
"""

import json
import logging
from contextlib import asynccontextmanager

from fastapi import FastAPI, Request
from fastapi.middleware.cors import CORSMiddleware
from fastapi.responses import JSONResponse, StreamingResponse
from pydantic import ValidationError

from core.config import get_settings
from core.agents.graph import generate_recipes, stream_recipes
from core.ratelimit import RateLimitResult, create_rate_limiter, hash_ip
from core.retrieval import embed
from core.schemas import MAX_BODY_BYTES, GenerateRequest
from core.vision import MAX_IMAGE_BYTES, InvalidImageError, detect_image_type, detect_ingredients

logging.basicConfig(level=logging.INFO, format="%(levelname)s %(name)s: %(message)s")
log = logging.getLogger("api")

settings = get_settings()

@asynccontextmanager
async def lifespan(app: FastAPI):
    """Load the embedding model once at startup, so the first user does not wait."""
    try:
        embed(["warm up"])
        log.info("Embedding model loaded")
    except Exception as err:  # search falls back to free generation anyway
        log.warning("Could not preload embedding model: %s", err)
    yield


app = FastAPI(
    lifespan=lifespan,
    title="Code a Cuisine API",
    version="0.3.0",
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

photo_limiter = create_rate_limiter(
    redis_url=settings.redis_url,
    per_ip_daily=settings.ratelimit_photo_per_ip_daily,
    per_ip_burst=settings.ratelimit_photo_per_ip_burst,
    global_daily=settings.ratelimit_photo_global_daily,
    prefix="photo",
)

BASE_HEADERS = {"X-Content-Type-Options": "nosniff", "Cache-Control": "no-store"}
GENERATION_FAILED = "Could not generate recipes right now. Please try again."


def error_response(status: int, message: str, headers: dict | None = None, **extra) -> JSONResponse:
    return JSONResponse({"error": message, **extra}, status_code=status, headers={**BASE_HEADERS, **(headers or {})})


def first_error_message(err: ValidationError) -> str:
    msg = err.errors()[0].get("msg", "Invalid request.")
    return msg.removeprefix("Value error, ")


@app.get("/health")
def health() -> dict[str, str]:
    """Simple liveness check for local testing, Docker and the reverse proxy."""
    return {"status": "ok"}


async def check_request(request: Request) -> tuple[GenerateRequest, RateLimitResult] | JSONResponse:
    """Shared checks for both generate endpoints: header, size, JSON, schema, rate limit."""
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
    return payload, limit


@app.post("/generate")
async def generate(request: Request) -> JSONResponse:
    """All recipes at once (JSON). Kept for compatibility and simple clients."""
    checked = await check_request(request)
    if isinstance(checked, JSONResponse):
        return checked
    payload, limit = checked

    try:
        result = await generate_recipes(payload)
    except Exception:
        log.exception("Recipe generation failed")
        return error_response(502, GENERATION_FAILED)

    return JSONResponse(
        result.model_dump(exclude_none=True),
        headers={**BASE_HEADERS, "X-RateLimit-Remaining": str(limit.remaining)},
    )


def sse(event: str, data: dict) -> str:
    """One Server-Sent Event."""
    return f"event: {event}\ndata: {json.dumps(data, ensure_ascii=False)}\n\n"


@app.post("/generate/stream")
async def generate_stream(request: Request):
    """Same as /generate, but streams progress as Server-Sent Events:
    `step` after every agent, `revision` when recipes go back to the chef,
    then `result` (the recipes) or `error`."""
    checked = await check_request(request)
    if isinstance(checked, JSONResponse):
        return checked
    payload, limit = checked

    async def events():
        try:
            async for event, data in stream_recipes(payload):
                yield sse(event, data)
        except Exception:
            log.exception("Recipe generation failed (stream)")
            yield sse("error", {"error": GENERATION_FAILED})

    headers = {
        **BASE_HEADERS,
        "X-RateLimit-Remaining": str(limit.remaining),
        "X-Accel-Buffering": "no",  # tell proxies not to buffer the stream
    }
    return StreamingResponse(events(), media_type="text/event-stream", headers=headers)


@app.post("/detect-ingredients")
async def detect_ingredients_endpoint(request: Request) -> JSONResponse:
    """Fridge photo (raw JPEG/PNG/WebP body) -> {"ingredients": [{name, quantity, unit}]}.
    The image is processed in memory only and never stored."""
    if request.headers.get("x-cac-client") != "web":
        return error_response(403, "Forbidden")
    declared = request.headers.get("content-length", "0")
    if declared.isdigit() and int(declared) > MAX_IMAGE_BYTES:
        return error_response(413, "The image is too large.")
    if not get_settings().openrouter_api_key:
        return error_response(500, "OPENROUTER_API_KEY is not configured")

    data = await request.body()
    try:
        detect_image_type(data)  # cheap check before spending rate limit or LLM money
    except InvalidImageError as err:
        return error_response(413 if len(data) > MAX_IMAGE_BYTES else 415, str(err))

    client_ip = request.client.host if request.client else "unknown"
    limit = await photo_limiter.check(hash_ip(client_ip))
    if not limit.ok:
        return error_response(429, limit.error, {"Retry-After": str(limit.retry_after)}, scope=limit.scope)

    try:
        result = await detect_ingredients(data)
    except Exception:
        log.exception("Ingredient detection failed")
        return error_response(502, "Could not read the photo right now. Please try again or add the ingredients by hand.")
    finally:
        del data  # do not keep the image around longer than needed

    body = result.model_dump()
    if not result.ingredients:
        body["message"] = "No food found in this photo. Try a closer, brighter photo."
    return JSONResponse(body, headers={**BASE_HEADERS, "X-RateLimit-Remaining": str(limit.remaining)})
