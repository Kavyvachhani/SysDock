"""Bind/auth model for the web server.

Security posture (see SECURITY.md):

* The server binds ``127.0.0.1`` by default — nothing is exposed to the network
  unless the user passes an explicit non-loopback ``--host``.
* When bound to a non-loopback address, a bearer token is **required**; one is
  auto-generated, persisted with ``0600`` perms, and printed **once** with a
  warning. Unauthenticated requests are rejected.
* Token comparison is constant-time. Tokens never appear in URLs or logs.
"""

from __future__ import annotations

import os
import secrets
import stat
from pathlib import Path

from sysdock.core.logging import get_logger

log = get_logger(__name__)

DEFAULT_HOST = "127.0.0.1"
DEFAULT_PORT = 8787
_LOOPBACK = {"127.0.0.1", "::1", "localhost", ""}


def is_loopback(host: str) -> bool:
    """True if ``host`` is a loopback address (not exposed to the network).

    ``0.0.0.0`` / ``::`` bind all interfaces and are therefore NOT loopback.
    """
    h = (host or "").strip().lower()
    if h in _LOOPBACK:
        return True
    return h.startswith("127.")


def generate_token() -> str:
    """A fresh, URL-safe, 256-bit bearer token."""
    return secrets.token_urlsafe(32)


def token_path() -> Path:
    """Per-user config path for the persisted web token."""
    if os.name == "nt":
        base = Path(os.environ.get("APPDATA", Path.home() / "AppData" / "Roaming"))
    else:
        base = Path(os.environ.get("XDG_CONFIG_HOME", Path.home() / ".config"))
    return base / "sysdock" / "web_token"


def load_or_create_token(*, regenerate: bool = False) -> str:
    """Return the persisted token, creating (or regenerating) it if needed.

    The file is written with owner-only (``0600``) permissions.
    """
    path = token_path()
    if not regenerate and path.exists():
        try:
            existing = path.read_text(encoding="utf-8").strip()
            if existing:
                return existing
        except OSError as exc:  # pragma: no cover - unreadable token file
            log.debug("could not read token file: %s", exc)

    token = generate_token()
    try:
        path.parent.mkdir(parents=True, exist_ok=True)
        path.write_text(token, encoding="utf-8")
        os.chmod(path, stat.S_IRUSR | stat.S_IWUSR)  # 0600
    except OSError as exc:  # pragma: no cover - read-only home, etc.
        log.warning("could not persist token (using ephemeral): %s", exc)
    return token


def check_bearer(authorization_header: str | None, expected_token: str) -> bool:
    """Constant-time check of an ``Authorization: Bearer <token>`` header."""
    if not authorization_header or not expected_token:
        return False
    parts = authorization_header.split(None, 1)
    if len(parts) != 2 or parts[0].lower() != "bearer":
        return False
    return secrets.compare_digest(parts[1].strip(), expected_token)
