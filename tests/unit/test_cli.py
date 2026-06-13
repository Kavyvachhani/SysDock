"""CLI tests: version, capability report, and the global error boundary."""

from __future__ import annotations

import json

import pytest
from click.testing import CliRunner

from sysdock import __version__
from sysdock import cli as cli_mod
from sysdock.core.errors import CapabilityUnavailable, ExitCode


def test_version_command():
    result = CliRunner().invoke(cli_mod.cli, ["version"])
    assert result.exit_code == 0
    assert __version__ in result.output


def test_version_json():
    result = CliRunner().invoke(cli_mod.cli, ["version", "--json"])
    assert result.exit_code == 0
    payload = json.loads(result.output)
    assert payload["version"] == __version__


def test_check_reports_capabilities():
    result = CliRunner().invoke(cli_mod.cli, ["check"])
    assert result.exit_code == 0
    assert "Capabilities" in result.output


def test_check_json_is_valid():
    result = CliRunner().invoke(cli_mod.cli, ["check", "--json"])
    assert result.exit_code == 0
    payload = json.loads(result.output)
    assert "platform" in payload
    assert "firewall" in payload


def test_error_boundary_renders_clean_message_and_exit_code(monkeypatch, capsys):
    """A deliberately broken backend must yield a clean message + correct exit
    code via main() — never a traceback."""

    def _boom():
        raise CapabilityUnavailable("firewall view not available on this host")

    # Break the capability backend that `check` depends on.
    import sysdock.core.capabilities as caps_mod

    monkeypatch.setattr(caps_mod, "detect", _boom)

    with pytest.raises(SystemExit) as exc:
        cli_mod.main(["check"])
    assert exc.value.code == int(ExitCode.UNAVAILABLE)

    out = capsys.readouterr()
    combined = out.out + out.err
    assert "Error:" in combined
    assert "Traceback" not in combined


def test_error_boundary_handles_unexpected_exception(monkeypatch, capsys):
    def _kaboom():
        raise RuntimeError("totally unexpected")

    import sysdock.core.capabilities as caps_mod

    monkeypatch.setattr(caps_mod, "detect", _kaboom)

    with pytest.raises(SystemExit) as exc:
        cli_mod.main(["check"])
    assert exc.value.code == int(ExitCode.ERROR)

    combined = "".join(capsys.readouterr())
    assert "unexpected error occurred" in combined
    assert "Traceback" not in combined
