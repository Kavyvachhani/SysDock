"""Error-taxonomy tests."""

from __future__ import annotations

from sysdock.core.errors import (
    CapabilityUnavailable,
    CollectionError,
    ExitCode,
    SysdockError,
    UsageError,
)


def test_exit_codes_are_stable():
    assert ExitCode.OK == 0
    assert ExitCode.ERROR == 1
    assert ExitCode.USAGE == 2
    assert ExitCode.UNAVAILABLE == 3
    assert ExitCode.INTERRUPTED == 130


def test_base_error_carries_message_and_default_code():
    err = SysdockError("boom")
    assert err.message == "boom"
    assert str(err) == "boom"
    assert err.exit_code == ExitCode.ERROR
    assert err.hint is None


def test_subclasses_map_to_expected_codes():
    assert UsageError("bad flag").exit_code == ExitCode.USAGE
    assert CapabilityUnavailable("no firewall").exit_code == ExitCode.UNAVAILABLE
    assert CollectionError("collector died").exit_code == ExitCode.ERROR


def test_hint_is_preserved():
    err = CapabilityUnavailable("no GPU here", hint="install drivers")
    assert err.hint == "install drivers"
