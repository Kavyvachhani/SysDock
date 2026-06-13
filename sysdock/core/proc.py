"""The single audited subprocess helper.

Every external command in SysDock — including the privileged security backends
— goes through :func:`run`. The rules this module enforces (see principle 5 in
the project brief):

* **No shell, ever.** Arguments are passed as a list; ``shell=False`` always.
  Passing a ``str`` is rejected, so a dynamic value can never be word-split or
  interpreted by a shell.
* **Always a timeout.** A hung binary can never hang SysDock.
* **Tolerant.** A missing binary, a non-zero exit, or a timeout returns a
  :class:`ProcResult` describing what happened — it never raises.
* **Untrusted output.** Bytes are decoded defensively; callers must parse the
  text as untrusted input.

Because nothing here interpolates values into a command string, this helper is
safe to hand externally-influenced *arguments* (e.g. a jail name) — they are
delivered to ``execve`` as discrete argv entries, not re-parsed.
"""

from __future__ import annotations

import shutil
import subprocess
import time
from collections.abc import Mapping, Sequence
from dataclasses import dataclass

# Sentinel returncodes for conditions where the process never ran or was killed.
RC_NOT_FOUND = 127  # binary not found (matches shell convention)
RC_TIMEOUT = 124  # timed out (matches GNU coreutils `timeout`)
RC_ERROR = -1  # other OS-level failure launching the process

DEFAULT_TIMEOUT = 5.0


@dataclass(frozen=True)
class ProcResult:
    """Outcome of a subprocess invocation. Never partial, never raises."""

    args: tuple[str, ...]
    returncode: int
    stdout: str
    stderr: str
    timed_out: bool
    found: bool
    duration_s: float

    @property
    def ok(self) -> bool:
        """True only if the binary existed, did not time out, and exited 0."""
        return self.found and not self.timed_out and self.returncode == 0


def which(binary: str) -> str | None:
    """Return the resolved path of ``binary`` on PATH, or ``None`` if absent."""
    return shutil.which(binary)


def run(
    args: Sequence[str],
    *,
    timeout: float = DEFAULT_TIMEOUT,
    input_text: str | None = None,
    env: Mapping[str, str] | None = None,
    cwd: str | None = None,
    check_path: bool = True,
) -> ProcResult:
    """Run ``args`` safely and return a :class:`ProcResult`.

    Args:
        args: The command as a list, e.g. ``["ufw", "status"]``. A bare string
            is rejected to make shell injection structurally impossible.
        timeout: Hard wall-clock limit in seconds. Required (has a default).
        input_text: Optional stdin to feed the process.
        env: Optional environment overrides (the child's full environment).
        cwd: Optional working directory.
        check_path: If True (default), resolve ``args[0]`` on PATH up front so a
            missing binary is reported as ``found=False`` without spawning.

    This function never raises for command-level failures; inspect
    :attr:`ProcResult.ok`, ``returncode``, ``found`` and ``timed_out``.
    """
    if isinstance(args, (str, bytes)):
        raise TypeError(
            "proc.run() requires a list of arguments, not a string; "
            "passing a string would invite shell-style word splitting."
        )
    argv = [str(a) for a in args]
    if not argv:
        raise ValueError("proc.run() requires at least one argument (the binary).")

    args_tuple = tuple(argv)

    if check_path and which(argv[0]) is None:
        return ProcResult(
            args=args_tuple,
            returncode=RC_NOT_FOUND,
            stdout="",
            stderr="",
            timed_out=False,
            found=False,
            duration_s=0.0,
        )

    start = time.monotonic()
    try:
        completed = subprocess.run(  # noqa: S603 - args is a validated list, shell=False
            argv,
            capture_output=True,
            text=True,
            timeout=timeout,
            input=input_text,
            env=dict(env) if env is not None else None,
            cwd=cwd,
            shell=False,
            errors="replace",
        )
    except FileNotFoundError:
        return ProcResult(args_tuple, RC_NOT_FOUND, "", "", False, False, time.monotonic() - start)
    except subprocess.TimeoutExpired as exc:
        # Surface whatever was captured before the kill.
        out = _as_text(exc.stdout)
        err = _as_text(exc.stderr)
        return ProcResult(args_tuple, RC_TIMEOUT, out, err, True, True, time.monotonic() - start)
    except (OSError, ValueError):
        # PermissionError, ENOEXEC, bad fd, etc. — never propagate to the user.
        return ProcResult(args_tuple, RC_ERROR, "", "", False, True, time.monotonic() - start)

    return ProcResult(
        args=args_tuple,
        returncode=completed.returncode,
        stdout=completed.stdout or "",
        stderr=completed.stderr or "",
        timed_out=False,
        found=True,
        duration_s=time.monotonic() - start,
    )


def _as_text(value: object) -> str:
    """Coerce captured stdout/stderr (str or bytes or None) to text safely."""
    if value is None:
        return ""
    if isinstance(value, bytes):
        return value.decode("utf-8", errors="replace")
    return str(value)
