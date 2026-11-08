"""Remote MCP server: API key, rate limit, host check (Streamable HTTP, in-process)."""

import pytest
from fastapi.testclient import TestClient

from core.config import get_settings
from mcp_server import http as mcp_http
from mcp_server.http import bearer_token, key_is_valid

INIT = {
    "jsonrpc": "2.0",
    "id": 1,
    "method": "initialize",
    "params": {"protocolVersion": "2025-06-18", "capabilities": {}, "clientInfo": {"name": "test", "version": "1"}},
}
ACCEPT = {"Accept": "application/json, text/event-stream"}


@pytest.fixture
def make_client(monkeypatch):
    monkeypatch.setattr(mcp_http, "embed", lambda texts: [[0.0]])  # no model download in tests
    clients = []

    def make(keys="key-a,key-b", burst="100", hosts="testserver"):
        monkeypatch.setenv("MCP_API_KEYS", keys)
        monkeypatch.setenv("MCP_RATELIMIT_PER_KEY_BURST", burst)
        monkeypatch.setenv("MCP_ALLOWED_HOSTS", hosts)
        get_settings.cache_clear()
        client = TestClient(mcp_http.build_app())
        client.__enter__()  # runs the lifespan (MCP session manager)
        clients.append(client)
        return client

    yield make
    for c in clients:
        c.__exit__(None, None, None)


def post(client, headers):
    return client.post("/mcp", json=INIT, headers={**ACCEPT, **headers})


def test_valid_key_can_initialize(make_client):
    res = post(make_client(), {"Authorization": "Bearer key-b"})
    assert res.status_code == 200
    assert res.json()["result"]["serverInfo"]["name"] == "code-a-cuisine"


def test_x_api_key_header_works_too(make_client):
    assert post(make_client(), {"X-API-Key": "key-a"}).status_code == 200


@pytest.mark.parametrize("headers", [{}, {"Authorization": "Bearer wrong"}, {"Authorization": "Basic key-a"}])
def test_missing_or_wrong_key_is_rejected(make_client, headers):
    res = post(make_client(), headers)
    assert res.status_code == 401 and "API key" in res.json()["error"]


def test_no_keys_configured_fails_closed(make_client):
    res = post(make_client(keys=""), {"Authorization": "Bearer anything"})
    assert res.status_code == 503


def test_rate_limit_per_key(make_client):
    client = make_client(burst="2")
    codes = [post(client, {"Authorization": "Bearer key-a"}).status_code for _ in range(3)]
    assert codes == [200, 200, 429]
    assert post(client, {"Authorization": "Bearer key-b"}).status_code == 200  # other key unaffected


def test_unknown_host_is_rejected(make_client):
    res = post(make_client(hosts="cuisine-api.example.dev"), {"Authorization": "Bearer key-a"})
    assert res.status_code == 421


def test_health_needs_no_key(make_client):
    assert make_client().get("/health").json() == {"status": "ok"}


def test_helpers():
    assert bearer_token({b"authorization": b"Bearer  abc "}) == "abc"
    assert bearer_token({b"x-api-key": b"xyz"}) == "xyz"
    assert bearer_token({}) == ""
    assert key_is_valid("abc", ["x", "abc"]) and not key_is_valid("", ["x"]) and not key_is_valid("ab", ["abc"])
