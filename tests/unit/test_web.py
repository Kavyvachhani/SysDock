"""Web layer tests: auth model, rate limiting, metrics, and the live server."""

from __future__ import annotations

import json
import threading
import urllib.error
import urllib.request
from contextlib import contextmanager

import pytest

from sysdock.core.snapshot import SnapshotProvider
from sysdock.web import auth
from sysdock.web.ratelimit import RateLimiter
from sysdock.web.server import WebConfig, build_server

# ── auth ──────────────────────────────────────────────────────────────────────


@pytest.mark.parametrize(
    "host,expected",
    [
        ("127.0.0.1", True),
        ("::1", True),
        ("localhost", True),
        ("127.5.5.5", True),
        ("0.0.0.0", False),
        ("192.168.1.10", False),
        ("::", False),
    ],
)
def test_is_loopback(host, expected):
    assert auth.is_loopback(host) is expected


def test_check_bearer():
    tok = auth.generate_token()
    assert auth.check_bearer(f"Bearer {tok}", tok) is True
    assert auth.check_bearer(f"bearer {tok}", tok) is True
    assert auth.check_bearer(f"Bearer {tok}x", tok) is False
    assert auth.check_bearer("Basic xyz", tok) is False
    assert auth.check_bearer(None, tok) is False
    assert auth.check_bearer(f"Bearer {tok}", "") is False


def test_generate_token_is_unguessable():
    a, b = auth.generate_token(), auth.generate_token()
    assert a != b
    assert len(a) >= 32


# ── rate limiter ────────────────────────────────────────────────────────────--


def test_rate_limiter_blocks_over_limit():
    rl = RateLimiter(max_requests=3, window_seconds=100)
    assert [rl.allow("ip", now=0) for _ in range(3)] == [True, True, True]
    assert rl.allow("ip", now=0) is False  # 4th over the limit


def test_rate_limiter_window_resets():
    rl = RateLimiter(max_requests=1, window_seconds=10)
    assert rl.allow("ip", now=0) is True
    assert rl.allow("ip", now=5) is False
    assert rl.allow("ip", now=20) is True  # window passed


def test_rate_limiter_per_client():
    rl = RateLimiter(max_requests=1, window_seconds=10)
    assert rl.allow("a", now=0) is True
    assert rl.allow("b", now=0) is True  # different client unaffected


# ── metrics ─────────────────────────────────────────────────────────────────--


def test_render_metrics_contains_expected_series():
    from sysdock.web.metrics import render_metrics

    snap = SnapshotProvider(enable_docker=False, enable_security=False, enable_gpu=False).get(
        force=True
    )
    text = render_metrics(snap)
    assert "sysdock_cpu_percent" in text
    assert "sysdock_memory_percent" in text
    assert "# TYPE sysdock_cpu_percent gauge" in text
    assert text.endswith("\n")


# ── live server ─────────────────────────────────────────────────────────────--


@contextmanager
def running_server(config: WebConfig):
    provider = SnapshotProvider(enable_docker=False, enable_security=False, enable_gpu=False)
    config.host = "127.0.0.1"
    config.port = 0  # ephemeral
    server = build_server(provider, config)
    port = server.server_address[1]
    thread = threading.Thread(target=server.serve_forever, daemon=True)
    thread.start()
    try:
        yield f"http://127.0.0.1:{port}"
    finally:
        server._stop_event.set()
        server.shutdown()
        server.server_close()


def _get(url, token=None):
    req = urllib.request.Request(url)
    if token:
        req.add_header("Authorization", f"Bearer {token}")
    return urllib.request.urlopen(req, timeout=5)  # noqa: S310 (localhost test)


def test_loopback_serves_without_auth():
    with running_server(WebConfig(require_auth=False)) as base:
        with _get(base + "/health") as r:
            assert r.status == 200
            assert json.loads(r.read())["status"] == "ok"
        with _get(base + "/api/snapshot") as r:
            assert r.status == 200
            data = json.loads(r.read())
            assert "cpu" in data and "memory" in data
        with _get(base + "/") as r:
            body = r.read().decode()
            assert "SysDock" in body
            # Security headers present.
            assert r.headers["X-Content-Type-Options"] == "nosniff"
            assert r.headers["X-Frame-Options"] == "DENY"
            assert "Content-Security-Policy" in r.headers
            # No wildcard CORS.
            assert r.headers.get("Access-Control-Allow-Origin") is None
        with _get(base + "/metrics") as r:
            assert r.status == 200
            assert "sysdock_cpu_percent" in r.read().decode()


def test_remote_requires_auth():
    token = auth.generate_token()
    with running_server(WebConfig(require_auth=True, token=token)) as base:
        # No token -> 401.
        with pytest.raises(urllib.error.HTTPError) as exc:
            _get(base + "/api/snapshot")
        assert exc.value.code == 401
        # /health stays open (no sensitive data).
        with _get(base + "/health") as r:
            assert r.status == 200
        # Correct token -> 200.
        with _get(base + "/api/snapshot", token=token) as r:
            assert r.status == 200
        # Wrong token -> 401.
        with pytest.raises(urllib.error.HTTPError) as exc:
            _get(base + "/api/snapshot", token="wrong")
        assert exc.value.code == 401


def test_rate_limit_returns_429(monkeypatch):
    import sysdock.web.server as server_mod

    # Force a tiny limit by patching the limiter the server builds.
    orig = server_mod.RateLimiter
    monkeypatch.setattr(
        server_mod, "RateLimiter", lambda *a, **k: orig(max_requests=3, window_seconds=100)
    )
    with running_server(WebConfig(require_auth=False)) as base:
        codes = []
        for _ in range(6):
            try:
                with _get(base + "/health") as r:
                    codes.append(r.status)
            except urllib.error.HTTPError as e:
                codes.append(e.code)
        assert 429 in codes
