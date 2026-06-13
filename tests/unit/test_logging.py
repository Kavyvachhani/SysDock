"""Structured-logging and secret-redaction tests."""

from __future__ import annotations

import json
import logging

from sysdock.core import logging as slog


def test_redact_bearer_token():
    out = slog.redact("Authorization: Bearer abc123.def-456")
    assert "abc123" not in out
    assert "REDACTED" in out


def test_redact_key_value_secrets():
    assert "hunter2" not in slog.redact("password=hunter2")
    assert "s3cr3t" not in slog.redact("token: s3cr3t")
    assert "AKIA999" not in slog.redact("api_key=AKIA999")


def test_redact_leaves_innocent_text_alone():
    assert slog.redact("listening on 127.0.0.1:5010") == "listening on 127.0.0.1:5010"


def test_setup_logging_is_idempotent():
    slog.setup_logging(level="INFO")
    slog.setup_logging(level="DEBUG")
    root = logging.getLogger(slog.ROOT_LOGGER_NAME)
    # Re-configuring must not stack duplicate handlers.
    assert len(root.handlers) == 1
    assert root.level == logging.DEBUG


def test_unknown_level_falls_back_to_info():
    slog.setup_logging(level="NONSENSE")
    assert logging.getLogger(slog.ROOT_LOGGER_NAME).level == logging.INFO


def test_get_logger_namespaces_under_root():
    assert slog.get_logger("foo").name == "sysdock.foo"
    assert slog.get_logger("sysdock.bar").name == "sysdock.bar"
    assert slog.get_logger().name == "sysdock"


def test_json_formatter_emits_valid_json_with_extras():
    record = logging.makeLogRecord(
        {
            "name": "sysdock.test",
            "levelname": "INFO",
            "msg": "started",
            "port": 5010,
        }
    )
    line = slog._JsonFormatter().format(record)
    parsed = json.loads(line)
    assert parsed["msg"] == "started"
    assert parsed["port"] == 5010
    assert parsed["logger"] == "sysdock.test"


def test_redacting_filter_scrubs_message_in_place():
    record = logging.makeLogRecord({"msg": "token=supersecret", "levelname": "INFO"})
    slog._RedactingFilter().filter(record)
    assert "supersecret" not in record.getMessage()
