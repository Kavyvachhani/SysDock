"""
InfraVision Agent — Single-Port Live JSON Server
================================================
ALL system metrics served from ONE port (default 5010).

Endpoints
---------
GET /           Complete live JSON snapshot — every section, every metric
GET /stream     Server-Sent Events: pushes fresh JSON every N seconds
GET /health     Quick liveness probe

Usage
-----
Start via CLI:
    infravision start --port 5010

Or from Python:
    from infravision_agent.server import run_server
    run_server(port=5010)

Curl examples:
    curl http://ec2-ip:5010/
    curl -N http://ec2-ip:5010/stream
    curl http://ec2-ip:5010/health
"""
from __future__ import annotations

import json
import logging
import socket
import sys
import threading
import time
from datetime import datetime, timezone
from urllib.parse import parse_qs, urlparse

# ThreadingHTTPServer ships with Python 3.7+; polyfill for 3.6
if sys.version_info >= (3, 7):
    from http.server import BaseHTTPRequestHandler, ThreadingHTTPServer as _Base
else:
    from http.server import BaseHTTPRequestHandler, HTTPServer
    from socketserver import ThreadingMixIn
    class _Base(ThreadingMixIn, HTTPServer):
        daemon_threads = True

from infravision_agent.collectors import (
    system      as _sys,
    disk        as _disk,
    processes   as _proc,
    network     as _net,
    docker_collector as _docker,
    security    as _sec,
)

log = logging.getLogger("infravision.server")

AGENT_VERSION   = "1.0.0"
STREAM_INTERVAL = 5   # seconds between SSE pushes

# How often each collector refreshes in the background (seconds)
_REFRESH = {
    "system":    5,
    "processes": 5,
    "network":   5,
    "disk":      15,
    "docker":    10,
    "security":  30,
}

_COLLECTORS = {
    "system":    _sys.collect_all,
    "disk":      _disk.collect_all,
    "processes": _proc.collect_all,
    "network":   _net.collect_all,
    "docker":    _docker.collect_all,
    "security":  _sec.collect_all,
}


# ─── Shared live snapshot ─────────────────────────────────────────────────────

class _Snapshot:
    """Thread-safe store written by background collector threads."""

    def __init__(self):
        self._data    = {}    # section → dict
        self._updated = {}    # section → float (unix timestamp)
        self._lock    = threading.RLock()

    def put(self, key, value):
        with self._lock:
            self._data[key]    = value
            self._updated[key] = time.time()

    def ready(self):
        with self._lock:
            return all(k in self._data for k in ("system", "disk", "processes"))

    def get_all(self):
        with self._lock:
            out = {k: v for k, v in self._data.items()}
            out["_meta"] = {
                "agent_version": AGENT_VERSION,
                "hostname": (
                    self._data.get("system", {})
                               .get("hostname", {})
                               .get("hostname", _hostname())
                ),
                "snapshot_at":  _now(),
                "sections_age": {
                    k: round(time.time() - v, 1)
                    for k, v in self._updated.items()
                },
                "python":    "{}.{}.{}".format(*sys.version_info[:3]),
                "collectors": list(_COLLECTORS.keys()),
            }
            return out


_snap      = _Snapshot()
_stop_flag = threading.Event()


def _hostname():
    try:
        return socket.gethostname()
    except Exception:
        return "unknown"


def _now():
    try:
        return datetime.now(timezone.utc).isoformat()
    except Exception:
        return datetime.utcnow().isoformat() + "Z"


# ─── Background collector threads ─────────────────────────────────────────────

def _loop(key, fn, interval):
    while not _stop_flag.is_set():
        try:
            _snap.put(key, fn())
        except Exception as exc:
            _snap.put(key, {"error": str(exc), "collected_at": _now()})
            log.warning("[%s] error: %s", key, exc)
        _stop_flag.wait(interval)


def _start():
    _stop_flag.clear()
    for key, fn in _COLLECTORS.items():
        t = threading.Thread(target=_loop, args=(key, fn, _REFRESH[key]),
                             name="iv-col-" + key, daemon=True)
        t.start()
    log.info("Waiting for initial collection (max 25s)…")
    deadline = time.time() + 25
    while not _snap.ready() and time.time() < deadline:
        time.sleep(0.2)
    log.info("Ready.")


def _stop():
    _stop_flag.set()


# ─── HTTP handler ─────────────────────────────────────────────────────────────

class _Handler(BaseHTTPRequestHandler):

    server_version   = "InfraVision/" + AGENT_VERSION
    protocol_version = "HTTP/1.1"

    def log_message(self, fmt, *args):
        log.debug("%s  %s", self.address_string(), fmt % args)

    # ── CORS preflight ────────────────────────────────────────────────────────
    def do_OPTIONS(self):
        self.send_response(204)
        self._cors()
        self.send_header("Content-Length", "0")
        self.end_headers()

    # ── GET dispatcher ────────────────────────────────────────────────────────
    def do_GET(self):
        try:
            parsed = urlparse(self.path)
            path   = parsed.path.rstrip("/") or "/"
            params = parse_qs(parsed.query)

            if path in ("/", "/metrics"):
                self._full(params)
            elif path == "/stream":
                self._stream(params)
            elif path == "/health":
                self._health()
            else:
                self._json({
                    "error": "Not found: {}".format(path),
                    "hint": "All metrics at  GET :5010/",
                    "endpoints": {
                        "GET /":       "Complete live JSON — all sections in one response",
                        "GET /stream": "Server-Sent Events, pushes JSON every 5s",
                        "GET /health": "Liveness probe",
                    },
                }, 404)
        except (OSError, BrokenPipeError, ConnectionResetError):
            pass
        except Exception as exc:
            log.exception("Handler error")
            try:
                self._json({"error": str(exc)}, 500)
            except Exception:
                pass

    # ── Routes ────────────────────────────────────────────────────────────────

    def _full(self, params):
        pretty = params.get("pretty", ["1"])[0] != "0"
        body   = json.dumps(_snap.get_all(),
                            indent=2 if pretty else None,
                            default=str).encode("utf-8")
        self.send_response(200)
        self._cors()
        self.send_header("Content-Type",   "application/json; charset=utf-8")
        self.send_header("Content-Length", str(len(body)))
        self.send_header("Cache-Control",  "no-cache, no-store")
        self.end_headers()
        self.wfile.write(body)

    def _stream(self, params):
        try:
            interval = float(params.get("interval", [str(STREAM_INTERVAL)])[0])
        except (ValueError, TypeError):
            interval = float(STREAM_INTERVAL)
        interval = max(2.0, min(60.0, interval))

        self.send_response(200)
        self._cors()
        self.send_header("Content-Type",      "text/event-stream; charset=utf-8")
        self.send_header("Cache-Control",     "no-cache")
        self.send_header("Transfer-Encoding", "chunked")
        self.send_header("X-Accel-Buffering", "no")
        self.end_headers()

        log.info("SSE client connected: %s (%.0fs)", self.address_string(), interval)
        try:
            while True:
                body  = json.dumps(_snap.get_all(), default=str)
                msg   = ("data: {}\n\n".format(body)).encode("utf-8")
                chunk = "{:x}\r\n".format(len(msg)).encode() + msg + b"\r\n"
                self.wfile.write(chunk)
                self.wfile.flush()
                time.sleep(interval)
        except (OSError, BrokenPipeError, ConnectionResetError):
            log.info("SSE client disconnected: %s", self.address_string())

    def _health(self):
        sys_d = _snap.get_all().get("system", {})
        body  = json.dumps({
            "status":        "ok",
            "agent_version": AGENT_VERSION,
            "hostname":      sys_d.get("hostname", {}).get("hostname", "?"),
            "uptime":        sys_d.get("uptime",   {}).get("uptime_human", "?"),
            "timestamp":     _now(),
            "port":          5010,
            "collectors":    list(_COLLECTORS.keys()),
        }, indent=2).encode("utf-8")
        self.send_response(200)
        self._cors()
        self.send_header("Content-Type",   "application/json; charset=utf-8")
        self.send_header("Content-Length", str(len(body)))
        self.end_headers()
        self.wfile.write(body)

    # ── Helpers ───────────────────────────────────────────────────────────────

    def _cors(self):
        self.send_header("Access-Control-Allow-Origin",  "*")
        self.send_header("Access-Control-Allow-Methods", "GET, OPTIONS")
        self.send_header("Access-Control-Allow-Headers", "Content-Type")
        self.send_header("X-Agent", "infravision/" + AGENT_VERSION)

    def _json(self, data, status=200):
        body = json.dumps(data, indent=2, default=str).encode("utf-8")
        self.send_response(status)
        self._cors()
        self.send_header("Content-Type",   "application/json; charset=utf-8")
        self.send_header("Content-Length", str(len(body)))
        self.end_headers()
        self.wfile.write(body)


# ─── Public API ───────────────────────────────────────────────────────────────

def run_server(host="0.0.0.0", port=5010):
    """Start the metrics server. Blocks until Ctrl-C."""
    _start()

    server = _Base((host, port), _Handler)
    server.daemon_threads = True

    display = host if host != "0.0.0.0" else _hostname()
    sep = "=" * 58
    log.info(sep)
    log.info("  InfraVision Agent  v%s", AGENT_VERSION)
    log.info("  All metrics  ->  http://%s:%d/", display, port)
    log.info("  Live stream  ->  http://%s:%d/stream", display, port)
    log.info("  Health       ->  http://%s:%d/health", display, port)
    log.info(sep)

    try:
        server.serve_forever()
    except KeyboardInterrupt:
        log.info("Shutting down.")
    finally:
        _stop()
        server.server_close()


def run_server_background(host="0.0.0.0", port=5010):
    """Start the server in a daemon thread. Returns the thread."""
    t = threading.Thread(target=run_server, args=(host, port),
                         name="iv-server-{}".format(port), daemon=True)
    t.start()
    return t
