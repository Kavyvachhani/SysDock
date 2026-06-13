"""Tests for the audited subprocess helper.

These use ``sys.executable`` so they run identically on Linux, macOS, and
Windows without depending on platform-specific binaries.
"""

from __future__ import annotations

import sys

import pytest

from sysdock.core import proc

PY = sys.executable


def test_run_rejects_string_command():
    with pytest.raises(TypeError):
        proc.run("echo hi")  # type: ignore[arg-type]


def test_run_rejects_empty_command():
    with pytest.raises(ValueError):
        proc.run([])


def test_successful_command():
    res = proc.run([PY, "-c", "print('hello')"])
    assert res.ok
    assert res.found
    assert res.returncode == 0
    assert "hello" in res.stdout
    assert res.duration_s >= 0.0


def test_nonzero_exit_is_not_ok_but_does_not_raise():
    res = proc.run([PY, "-c", "import sys; sys.exit(3)"])
    assert res.found
    assert res.timed_out is False
    assert res.returncode == 3
    assert res.ok is False


def test_missing_binary_is_reported_not_raised():
    res = proc.run(["sysdock-nonexistent-binary-zzz"])
    assert res.found is False
    assert res.returncode == proc.RC_NOT_FOUND
    assert res.ok is False


def test_timeout_is_reported_not_raised():
    res = proc.run([PY, "-c", "import time; time.sleep(5)"], timeout=0.3)
    assert res.timed_out is True
    assert res.returncode == proc.RC_TIMEOUT
    assert res.ok is False


def test_stdin_is_passed_through():
    res = proc.run([PY, "-c", "import sys; sys.stdout.write(sys.stdin.read())"], input_text="piped")
    assert res.ok
    assert "piped" in res.stdout


def test_which_resolves_absolute_path_and_misses_bogus():
    # shutil.which returns an absolute path unchanged if it is executable.
    assert proc.which(sys.executable) is not None
    assert proc.which("sysdock-definitely-not-a-real-binary") is None


def test_stderr_captured():
    res = proc.run([PY, "-c", "import sys; sys.stderr.write('boom')"])
    assert "boom" in res.stderr
