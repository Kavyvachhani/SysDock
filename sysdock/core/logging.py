"""Structured logging for SysDock.

One entry point — :func:`setup_logging` — configures the root ``sysdock``
logger for either human-readable or JSON output, at a chosen level. A redaction
filter strips anything that looks like a bearer token or secret so credentials
never reach logs, error messages, or telemetry (there is no telemetry).

Usage::

    from sysdock.core.logging import setup_logging, get_logger
    setup_logging(level="INFO", json_logs=False)
    log = get_logger(__name__)
    log.info("started", extra={"port": 5010})
"""

from __future__ import annotations

import json
import logging
import re
import sys
from typing import Any

ROOT_LOGGER_NAME = "sysdock"

# Reserved attributes on a LogRecord; anything else is treated as structured
# context and emitted alongside the message.
_RESERVED = frozenset(vars(logging.makeLogRecord({})).keys() | {"message", "asctime", "taskName"})

# Patterns that should never appear in a log line. Matched case-insensitively.
_SECRET_PATTERNS = (
    re.compile(r"(?i)\bbearer\s+[a-z0-9._\-]+"),
    re.compile(r"(?i)(token|secret|password|api[_-]?key)\s*[=:]\s*\S+"),
)
_REDACTED = "***REDACTED***"


def redact(text: str) -> str:
    """Replace anything resembling a secret in ``text`` with a placeholder."""
    for pattern in _SECRET_PATTERNS:
        text = pattern.sub(_REDACTED, text)
    return text


class _RedactingFilter(logging.Filter):
    """Scrub secrets from both the message and structured extras."""

    def filter(self, record: logging.LogRecord) -> bool:
        if isinstance(record.msg, str):
            record.msg = redact(record.msg)
        for key, value in list(record.__dict__.items()):
            if key not in _RESERVED and isinstance(value, str):
                record.__dict__[key] = redact(value)
        return True


class _JsonFormatter(logging.Formatter):
    """Render a log record as a single JSON object per line."""

    def format(self, record: logging.LogRecord) -> str:
        payload: dict[str, Any] = {
            "ts": self.formatTime(record, "%Y-%m-%dT%H:%M:%S%z"),
            "level": record.levelname,
            "logger": record.name,
            "msg": record.getMessage(),
        }
        for key, value in record.__dict__.items():
            if key not in _RESERVED:
                payload[key] = value
        if record.exc_info:
            payload["exc"] = self.formatException(record.exc_info)
        return json.dumps(payload, default=str)


class _TextFormatter(logging.Formatter):
    """Human-readable formatter that appends structured extras."""

    def __init__(self) -> None:
        super().__init__(
            fmt="%(asctime)s %(levelname)-7s %(name)s  %(message)s",
            datefmt="%H:%M:%S",
        )

    def format(self, record: logging.LogRecord) -> str:
        base = super().format(record)
        extras = {k: v for k, v in record.__dict__.items() if k not in _RESERVED}
        if extras:
            base += "  " + " ".join(f"{k}={v}" for k, v in extras.items())
        return base


def setup_logging(level: str = "INFO", *, json_logs: bool = False) -> None:
    """Configure the ``sysdock`` logger. Idempotent — safe to call repeatedly.

    Args:
        level: A standard level name (DEBUG, INFO, WARNING, ERROR, CRITICAL).
            Unknown values fall back to INFO rather than raising.
        json_logs: Emit one JSON object per line instead of human text.
    """
    logger = logging.getLogger(ROOT_LOGGER_NAME)
    numeric = logging.getLevelName(level.upper())
    if not isinstance(numeric, int):
        numeric = logging.INFO
    logger.setLevel(numeric)
    logger.propagate = False

    # Replace any handlers from a previous call so re-configuration is clean.
    for handler in list(logger.handlers):
        logger.removeHandler(handler)

    handler = logging.StreamHandler(stream=sys.stderr)
    handler.setFormatter(_JsonFormatter() if json_logs else _TextFormatter())
    handler.addFilter(_RedactingFilter())
    logger.addHandler(handler)


def get_logger(name: str | None = None) -> logging.Logger:
    """Return a child of the ``sysdock`` logger.

    ``get_logger(__name__)`` yields e.g. ``sysdock.core.capabilities``; a bare
    call returns the root SysDock logger.
    """
    if not name or name == ROOT_LOGGER_NAME:
        return logging.getLogger(ROOT_LOGGER_NAME)
    if name.startswith(ROOT_LOGGER_NAME + "."):
        return logging.getLogger(name)
    return logging.getLogger(f"{ROOT_LOGGER_NAME}.{name}")
