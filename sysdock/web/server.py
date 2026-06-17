"""Self-contained web server for SysDock (stdlib only — no web framework).

Serves the built-in dashboard, a JSON snapshot API, a live SSE stream, an
optional Prometheus text endpoint, and a health probe — all reading from the one
shared :class:`SnapshotProvider`, so N clients never trigger N collections.

Security (see SECURITY.md and :mod:`sysdock.web.auth`):
* binds 127.0.0.1 by default; a non-loopback bind requires a bearer token,
* rate-limited per client IP, served from a TTL cache,
* strict security headers, no wildcard CORS, tokens never in URLs or logs.
"""

from __future__ import annotations

import contextlib
import json
import threading
from dataclasses import dataclass
from http.server import BaseHTTPRequestHandler, ThreadingHTTPServer
from importlib import resources
from typing import Any

from sysdock.core.logging import get_logger
from sysdock.core.snapshot import SnapshotProvider
from sysdock.web import auth
from sysdock.web.metrics import render_metrics
from sysdock.web.ratelimit import RateLimiter

log = get_logger(__name__)

_STATIC_FILES = {
    "/": ("index.html", "text/html; charset=utf-8"),
    "/index.html": ("index.html", "text/html; charset=utf-8"),
    "/app.js": ("app.js", "application/javascript; charset=utf-8"),
    "/style.css": ("style.css", "text/css; charset=utf-8"),
}

_SECURITY_HEADERS = {
    "Content-Security-Policy": (
        "default-src 'self'; base-uri 'none'; frame-ancestors 'none'; "
        "object-src 'none'; form-action 'none'"
    ),
    "X-Content-Type-Options": "nosniff",
    "X-Frame-Options": "DENY",
    "Referrer-Policy": "no-referrer",
    "Cross-Origin-Opener-Policy": "same-origin",
}


@dataclass
class WebConfig:
    host: str = auth.DEFAULT_HOST
    port: int = auth.DEFAULT_PORT
    token: str | None = None  # required when not loopback
    require_auth: bool = False
    enable_metrics: bool = True
    stream_interval: float = 2.0


def _read_static(name: str) -> bytes:
    return (resources.files("sysdock.web") / "static" / name).read_bytes()


def make_handler(
    provider: SnapshotProvider, config: WebConfig, limiter: RateLimiter
) -> type[BaseHTTPRequestHandler]:
    class Handler(BaseHTTPRequestHandler):
        server_version = "SysDock"
        protocol_version = "HTTP/1.1"

        # Never log headers/tokens; one terse debug line at most.
        def log_message(self, fmt: str, *args: Any) -> None:
            log.debug("web %s", self.path.split("?")[0])

        def _client(self) -> str:
            return self.client_address[0] if self.client_address else "unknown"

        def _send_headers(self, status: int, content_type: str, length: int) -> None:
            self.send_response(status)
            self.send_header("Content-Type", content_type)
            self.send_header("Content-Length", str(length))
            self.send_header("Cache-Control", "no-store")
            for key, value in _SECURITY_HEADERS.items():
                self.send_header(key, value)
            self.end_headers()

        def _send(self, status: int, body: bytes, content_type: str) -> None:
            self._send_headers(status, content_type, len(body))
            self.wfile.write(body)

        def _json(self, obj: Any, status: int = 200) -> None:
            self._send(
                status, json.dumps(obj, default=str).encode(), "application/json; charset=utf-8"
            )

        def _authorized(self) -> bool:
            if not config.require_auth:
                return True
            return auth.check_bearer(self.headers.get("Authorization"), config.token or "")

        def do_GET(self) -> None:  # noqa: N802 (stdlib API)
            try:
                self._route()
            except (BrokenPipeError, ConnectionResetError):
                return
            except Exception:
                log.exception("web handler error")
                with contextlib.suppress(Exception):
                    self._json({"error": "internal error"}, 500)

        def _route(self) -> None:
            path = self.path.split("?", 1)[0].rstrip("/") or "/"

            if not limiter.allow(self._client()):
                self._json({"error": "rate limited"}, 429)
                return

            # /health is the only unauthenticated endpoint (no sensitive data).
            if path == "/health":
                self._json({"status": "ok"})
                return

            if not self._authorized():
                self.send_response(401)
                self.send_header("WWW-Authenticate", 'Bearer realm="SysDock"')
                self.send_header("Content-Length", "0")
                for key, value in _SECURITY_HEADERS.items():
                    self.send_header(key, value)
                self.end_headers()
                return

            if path in _STATIC_FILES:
                name, ctype = _STATIC_FILES[path]
                try:
                    self._send(200, _read_static(name), ctype)
                except FileNotFoundError:
                    self._json({"error": "not found"}, 404)
                return
            if path == "/api/snapshot":
                self._json(provider.get().to_dict())
                return
            if path == "/api/stream":
                self._stream()
                return
            if path == "/metrics":
                if not config.enable_metrics:
                    self._json({"error": "metrics disabled"}, 404)
                    return
                body = render_metrics(provider.get()).encode()
                self._send(200, body, "text/plain; version=0.0.4; charset=utf-8")
                return
            self._json({"error": "not found"}, 404)

        def _stream(self) -> None:
            self.send_response(200)
            self.send_header("Content-Type", "text/event-stream; charset=utf-8")
            self.send_header("Cache-Control", "no-store")
            self.send_header("Connection", "keep-alive")
            for key, value in _SECURITY_HEADERS.items():
                self.send_header(key, value)
            self.end_headers()
            stop = getattr(self.server, "_stop_event", None)
            try:
                while stop is None or not stop.is_set():
                    payload = json.dumps(provider.get().to_dict(), default=str)
                    self.wfile.write(f"data: {payload}\n\n".encode())
                    self.wfile.flush()
                    if stop is not None and stop.wait(config.stream_interval):
                        break
            except (BrokenPipeError, ConnectionResetError, OSError):
                pass

    return Handler


class _Server(ThreadingHTTPServer):
    daemon_threads = True
    allow_reuse_address = True

    def __init__(self, *args: Any, **kwargs: Any) -> None:
        super().__init__(*args, **kwargs)
        self._stop_event = threading.Event()


def build_server(provider: SnapshotProvider, config: WebConfig) -> _Server:
    limiter = RateLimiter()
    handler = make_handler(provider, config, limiter)
    return _Server((config.host, config.port), handler)


def run_web(
    *,
    host: str = auth.DEFAULT_HOST,
    port: int = auth.DEFAULT_PORT,
    token: str | None = None,
    regenerate_token: bool = False,
    enable_metrics: bool = True,
    no_auth: bool = False,
) -> None:
    """Start the web server (blocks until interrupted)."""
    from rich.console import Console
    from rich.panel import Panel

    console = Console(stderr=True)
    loopback = auth.is_loopback(host)
    require_auth = not loopback and not no_auth

    if require_auth:
        token = token or auth.load_or_create_token(regenerate=regenerate_token)
    elif not loopback and no_auth:
        console.print(
            "[bold red]WARNING:[/bold red] --no-auth on a non-loopback bind exposes "
            "system data with NO authentication. Use only behind a trusted network."
        )

    provider = SnapshotProvider()
    provider.start()
    config = WebConfig(
        host=host,
        port=port,
        token=token,
        require_auth=require_auth,
        enable_metrics=enable_metrics,
    )
    server = build_server(provider, config)

    url = f"http://{host}:{port}/"
    if require_auth:
        console.print(
            Panel.fit(
                f"[bold]SysDock web[/bold] serving on [cyan]{url}[/cyan]\n\n"
                f"[yellow]Exposed on a non-loopback address — authentication is ON.[/yellow]\n"
                f"Bearer token (shown once):\n  [bold green]{token}[/bold green]\n\n"
                f"[dim]Use:  curl -H 'Authorization: Bearer {token}' {url}api/snapshot[/dim]\n"
                f"[dim]Put TLS in front via a reverse proxy; restrict the port at your firewall.[/dim]",
                border_style="yellow",
            )
        )
    else:
        console.print(
            f"[bold]SysDock web[/bold] on [cyan]{url}[/cyan]  "
            f"[dim](localhost only; no auth needed)[/dim]"
        )

    try:
        server.serve_forever()
    except KeyboardInterrupt:
        pass
    finally:
        server._stop_event.set()
        provider.stop()
        server.shutdown()
        server.server_close()
