"""Error taxonomy and process exit codes.

A single place that maps failure categories to user-facing messages and the
exit code the CLI should return. Nothing here ever prints; the CLI error
boundary (``sysdock.cli``) decides how to render these.
"""

from __future__ import annotations

from enum import IntEnum


class ExitCode(IntEnum):
    """Process exit codes used across the CLI.

    Kept small and stable so scripts and service managers can branch on them.
    """

    OK = 0
    ERROR = 1  # generic, unexpected failure
    USAGE = 2  # the user invoked something incorrectly
    UNAVAILABLE = 3  # a requested capability is not available on this host
    INTERRUPTED = 130  # Ctrl-C / SIGINT (128 + SIGINT)


class SysdockError(Exception):
    """Base class for all errors SysDock raises deliberately.

    Carries a clean, user-facing message and the exit code the CLI should use.
    The error boundary renders ``str(self)`` and returns ``self.exit_code`` —
    no traceback ever reaches the user for one of these.
    """

    exit_code: ExitCode = ExitCode.ERROR

    def __init__(self, message: str, *, hint: str | None = None) -> None:
        super().__init__(message)
        self.message = message
        self.hint = hint


class UsageError(SysdockError):
    """The user asked for something invalid (bad flag, bad argument)."""

    exit_code = ExitCode.USAGE


class CapabilityUnavailable(SysdockError):
    """A requested feature is not available on this host or OS.

    This is an expected, non-crash outcome (e.g. firewall view on a host with
    no supported firewall backend). It maps to a distinct exit code so callers
    can tell "unsupported" apart from "broke".
    """

    exit_code = ExitCode.UNAVAILABLE


class CollectionError(SysdockError):
    """A collector failed in a way we could not degrade past."""

    exit_code = ExitCode.ERROR
