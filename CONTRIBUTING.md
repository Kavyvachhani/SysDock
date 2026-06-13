# Contributing to SysDock

Thanks for your interest in SysDock. This guide covers local setup and the
quality gate every change must pass.

## Development setup

```bash
python -m venv .venv
source .venv/bin/activate           # Windows: .venv\Scripts\activate
pip install -e ".[dev,docker]"
pre-commit install
```

## The quality gate

CI runs these on Linux, macOS, and Windows; run them locally before pushing:

```bash
ruff check .            # lint
ruff format .           # format
mypy                    # type check (strict on sysdock/core)
pytest --cov            # tests + coverage
```

`pre-commit` runs the lint/format/type hooks automatically on commit.

## Project principles

These are non-negotiable; PRs that violate them will be asked to change:

1. **Capability-gate everything platform-specific.** If a feature is
   unavailable, show a clean "not available" state — never crash. Detection
   lives in `sysdock/core/capabilities.py`.
2. **Subprocess safety.** All external commands go through
   `sysdock.core.proc.run` — argument lists, no shell, always a timeout, tolerant
   of missing binaries and non-zero exits. Never interpolate dynamic values into
   a command. See [SECURITY.md](SECURITY.md).
3. **No unhandled exception reaches the user.** The CLI error boundary turns
   failures into a clean message + structured log line + correct exit code.
4. **One core, three surfaces.** TUI, web, and the native wrapper read the same
   data; no forked collection logic.
5. **Honest docs.** No overclaiming. Keep the platform support matrix accurate.

## Commits and changelog

- Keep commits focused; reference the phase or issue where relevant.
- Add a `CHANGELOG.md` entry under `[Unreleased]` (Keep a Changelog format).

## Tests

- Platform-specific parsing must be unit-tested against recorded fixtures so the
  macOS/Windows paths are testable on any runner.
- New code in `sysdock/core` is expected to carry meaningful coverage.
