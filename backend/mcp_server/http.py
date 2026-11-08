"""Remote MCP server over Streamable HTTP (own service in docker-compose).

Same tools as the local stdio server (mcp_server/server.py), plus:
- API key: every request to /mcp needs `Authorization: Bearer <key>` (or `X-API-Key`).
  Keys come from MCP_API_KEYS (comma-separated). No keys configured = fail closed.
- Rate limit per API key (daily + burst) and a global daily cap, with Redis if set.
- DNS-rebinding protection: only the configured Host headers are accepted.
- Stateless: no server-side sessions, so restarts and scaling are trivial.

Run (from backend/):
    MCP_API_KEYS=dev-key uv run uvicorn mcp_server.http:app --port 8001
"""

import hmac
import json
import logging
from contextlib import asynccontextmanager

from mcp.server.transport_security import TransportSecuritySettings
from starlette.requests import Request
from starlette.responses import JSONResponse

from core.config import get_settings
from core.ratelimit import create_rate_limiter, hash_ip
from core.retrieval import embed
from mcp_server.server import mcp

logging.basicConfig(level=logging.INFO, format="%(levelname)s %(name)s: %(message)s")
log = logging.getLogger("mcp_http")

MCP_PATH = "/mcp"


def _csv(value: str) -> list[str]:
    return [v.strip() for v in value.split(",") if v.strip()]


def bearer_token(headers: dict[bytes, bytes]) -> str:
    auth = headers.get(b"authorization", b"").decode("latin-1").strip()
    if auth.lower().startswith("bearer "):
        return auth[7:].strip()
    return headers.get(b"x-api-key", b"").decode("latin-1").strip()


def key_is_valid(token: str, keys: list[str]) -> bool:
    # compare_digest: no timing side channel; check all keys every time
    return bool(token) and any([hmac.compare_digest(token.encode(), k.encode()) for k in keys])


class ApiKeyAndRateLimit:
    """ASGI middleware for the MCP endpoint (works with streaming responses)."""

    def __init__(self, app, keys: list[str], limiter):
        self.app = app
        self.keys = keys
        self.limiter = limiter

    async def __call__(self, scope, receive, send):
        if scope["type"] != "http" or not scope["path"].startswith(MCP_PATH):
            return await self.app(scope, receive, send)

        headers = dict(scope.get("headers") or [])
        if not self.keys:
            return await self._reject(send, 503, "MCP access is not configured on this server.")
        token = bearer_token(headers)
        if not key_is_valid(token, self.keys):
            return await self._reject(send, 401, "Missing or invalid API key. Send 'Authorization: Bearer <key>'.")

        limit = await self.limiter.check(hash_ip(f"mcp-key:{token}"))
        if not limit.ok:
            return await self._reject(send, 429, limit.error, {"retry-after": str(limit.retry_after)})
        return await self.app(scope, receive, send)

    @staticmethod
    async def _reject(send, status: int, message: str, extra_headers: dict | None = None):
        body = json.dumps({"error": message}).encode()
        headers = [(b"content-type", b"application/json"), (b"content-length", str(len(body)).encode())]
        headers += [(k.encode(), v.encode()) for k, v in (extra_headers or {}).items()]
        await send({"type": "http.response.start", "status": status, "headers": headers})
        await send({"type": "http.response.body", "body": body})


@mcp.custom_route("/health", methods=["GET"])
async def health(_: Request) -> JSONResponse:
    return JSONResponse({"status": "ok"})


def build_app():
    s = get_settings()
    starlette_app = mcp.streamable_http_app(
        streamable_http_path=MCP_PATH,
        stateless_http=True,
        json_response=True,
        transport_security=TransportSecuritySettings(
            enable_dns_rebinding_protection=True,
            allowed_hosts=_csv(s.mcp_allowed_hosts),
            allowed_origins=_csv(s.mcp_allowed_origins),
        ),
    )

    inner_lifespan = starlette_app.router.lifespan_context

    @asynccontextmanager
    async def lifespan(app):
        try:
            embed(["warm up"])  # load the embedding model once, not on the first tool call
        except Exception as err:
            log.warning("Could not preload embedding model: %s", err)
        if not _csv(s.mcp_api_keys):
            log.warning("MCP_API_KEYS is empty: all /mcp requests will be rejected")
        async with inner_lifespan(app):
            yield

    starlette_app.router.lifespan_context = lifespan

    limiter = create_rate_limiter(
        redis_url=s.redis_url,
        per_ip_daily=s.mcp_ratelimit_per_key_daily,
        per_ip_burst=s.mcp_ratelimit_per_key_burst,
        global_daily=s.mcp_ratelimit_global_daily,
        prefix="mcp",
    )
    return ApiKeyAndRateLimit(starlette_app, _csv(s.mcp_api_keys), limiter)


app = build_app()
