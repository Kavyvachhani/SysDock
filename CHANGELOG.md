# Changelog

All notable changes to SysDock are documented here. This project adheres to
[Keep a Changelog](https://keepachangelog.com/en/1.1.0/) and
[Semantic Versioning](https://semver.org/spec/v2.0.0.html).

## [Unreleased]

Hardening toward a production-ready v2.

### Phase 3 — GPU panel (capability-gated, multi-vendor)

#### Added
- `sysdock.core.gpu`: one normalized GPU schema across vendors (util, VRAM,
  temperature, power, per-process GPU memory). When no supported GPU is present
  the panel is hidden — never an error.
- **NVIDIA** via `nvidia-ml-py` (pynvml): utilisation, VRAM, temp, power,
  per-process GPU memory — every NVML call guarded.
- **AMD** via `rocm-smi --json`; **Intel** via `intel_gpu_top -J`; **Apple
  Silicon** via `system_profiler` (name, core count, unified-memory pool). Live
  utilisation on Apple Silicon needs elevation, so it is reported as unknown
  rather than guessed; the device is still shown.
- GPU is folded into the shared snapshot with a TTL cache and runs every backend
  behind a guard, so a broken/abnormal driver can never crash the snapshot.
- New optional extra: `pip install sysdock[gpu]` (pulls nvidia-ml-py).

#### Changed
- `sysdock status` UI: added per-core CPU bars and a GPU panel; memory now shows
  a usage bar.

### Phase 2 — Security panel (the wedge), subprocess-safe

#### Added
- `sysdock.core.security`: one normalized cross-OS schema —
  `firewall` (enabled/default_policy/backend), `open_ports[]`,
  `failed_auth[]`, `intrusion[]`. A capability that isn't present yields a typed
  `available=False` section with a reason — never `null`, never a crash.
- **Linux** backend: ufw → nftables → iptables; fail2ban-client; failed SSH auth
  from journald or `/var/log/auth.log`.
- **macOS** backend: Application Firewall via `socketfilterfw` (no sudo), `pfctl`
  where readable; failed auth from the unified log.
- **Windows** backend: `Get-NetFirewallProfile` (JSON) with `netsh` fallback;
  failed logons from the Security event log (Event ID 4625).
- Open ports are portable via psutil (no subprocess); degrade cleanly where the
  OS requires elevation to enumerate sockets.
- All commands run through `core.proc` (no shell, timeouts, tolerant); every
  parser is pure and **fixture-tested for all three OSes** on any CI runner.
- Security is folded into the shared snapshot with its own short-TTL cache, so it
  doesn't run subprocesses on every tick; `sysdock status` shows a security panel.

### Phase 1 — Portable metrics core + shared snapshot

#### Added
- `sysdock.core.collectors`: portable, psutil-based collectors for CPU
  (per-core, htop-style delta sampling, load avg), virtual+swap memory,
  per-partition disk usage + delta-based I/O rates, per-NIC throughput, the
  process table, host info, and an optional Docker collector.
- `sysdock.core.snapshot.SnapshotProvider`: the one shared snapshot every
  surface reads — timer-collected, **TTL-cached**, and **request-coalescing**
  (N concurrent readers cause a single collection, not N). Static facts (core
  counts, partition/NIC lists) are cached; rates are delta-based.
- Docker collector is cross-platform via the Docker SDK and degrades cleanly to
  a typed "unavailable" when the SDK or daemon is absent; the `docker stats`
  CPU/memory math (page-cache subtracted) is preserved and fixture-tested.
- Performance gate: a single-collection benchmark asserts a ceiling
  (`make bench`, run in CI; override via `SYSDOCK_BENCH_CEILING_MS`).

#### Changed
- `sysdock status` now reads the shared snapshot and emits a full, validated
  JSON document (`--json`); added `--top N` and `--no-docker`. Removed the
  `--section` flag (superseded by the unified snapshot).

### Phase 0 — Foundation & hardening harness

#### Added
- `sysdock.core.proc`: the single audited subprocess helper — argument lists
  only, never a shell, mandatory timeout, tolerant of missing binaries and
  non-zero exits; returns a typed `ProcResult` and never raises on command
  failures.
- `sysdock.core.capabilities`: injectable, cross-platform capability detection
  (firewall, intrusion, auth-log, GPU, containers, service manager). Linux,
  macOS, and Windows paths are all unit-tested on any runner.
- `sysdock.core.logging`: structured logging with `--log-level` and `--json-logs`,
  plus a filter that redacts bearer tokens and secrets from all log output.
- `sysdock.core.errors`: error taxonomy (`SysdockError`, `UsageError`,
  `CapabilityUnavailable`, `CollectionError`) and stable `ExitCode`s.
- Global CLI error boundary: no unhandled exception reaches the user — failures
  render a clean message with the correct exit code; tracebacks only at DEBUG.
- `sysdock check` now reports the detected capability matrix (with `--json`);
  new `sysdock version` command.
- Tooling: ruff (lint+format), mypy (strict on `sysdock/core`), pytest+coverage,
  pre-commit, Dependabot, and a 3-OS GitHub Actions CI matrix (lint/type/test +
  build sanity). Committed dev lockfile (`requirements-dev.txt`).
- `SECURITY.md` (bind/auth model, subprocess safety, disclosure) and
  `CONTRIBUTING.md`.

#### Changed
- Single version source of truth in `sysdock/__init__.py` (now `2.0.0.dev0`);
  the server no longer hardcodes a divergent version.
- Migrated packaging to PEP 621; Python floor raised to **3.9** (CI tests 3.9 and
  3.12). Removed the duplicate, version-drifted `setup.py`.

#### Security
- Removed a `shell=True` subprocess invocation in the Windows service install
  path; the task command is now passed as a single non-shell argv entry.

#### Removed
- Committed macOS AppleDouble (`._*`) metadata files; now git-ignored.

## [1.4.0] - 2026-03-25

### Added
- **Full cross-platform support**: macOS (Apple Silicon M1/M2/M3 native arm64), Windows 11, and Linux
- **macOS GPU detection**: NVIDIA CUDA on macOS, Apple Metal/MPS GPU detection via system_profiler
- **macOS-native CPU model** via sysctl (arm64 and x86_64)
- **macOS load average, uptime, memory** via sysctl fallbacks
- **GPU detection for AMD ROCm** on Linux (rocm-smi fallback)
- **Security collector** now respects platform (safe on macOS/Windows)
- **GitHub Actions multi-arch workflow** with Ubuntu + macOS matrix, produces arm64 .whl and amd64 .whl
- **Automated test suite** covering all collectors on all 3 platforms
- ~~**Zero SmartScreen warnings**: build manifest and authenticode metadata embedded in Windows EXE~~ *(Correction: this claim was inaccurate — the Windows EXE is not code-signed, so SmartScreen does warn. Real signing/notarization is tracked for the Phase 6 installer work.)*
- **Atomic batch data collection** in dashboard background loop — prevents all UI jitter/flapping
- **Panel versioning**: UI only redraws when data version increments, locking the header stable
- `screen=False` mode on Windows to prevent alternate-buffer flickering
- Rich `console.clear()` called once on startup for a clean initial frame

### Changed
- **Version bumped to 1.4.0** across pyproject.toml, setup.py, cli.py, dashboard.py
- **CPU collector** now reads model from `sysctl -n machdep.cpu.brand_string` on macOS
- **GPU collector** first tries `nvidia-smi`, then `rocm-smi`, then Apple Metal  
- **Process collector** skips system-noise processes on macOS (kernel_task) and Windows (System Idle Process)
- **Dashboard _bg_loop**: all collectors run in a single batch, then atomically update state once
- **Header panel** height increased to 4 rows — stable and flicker-free
- Debug borders explicitly set to `False` on all Layout segments
- Improved bar widths in GPU panel for narrow screens

### Fixed
- `os` module import missing in dashboard.py (caused crash in v1.3.0–v1.3.1)
- `_State.update` receiving raw function objects instead of calling them (crash in v1.3.2)
- Duplicate `snapshot()` method in `_State` class
- Windows process list showing "System Idle Process" occupying 99% CPU incorrectly
- UI flickering caused by per-field incremental state updates triggering multiple partial redraws
- Header "flapping" due to layout height=3 being too tight

### Security
- Subprocess calls use `shell=False` throughout (list-based args only)
- No eval/exec usage
- Proper `timeout` on all external process calls
- Error output suppressed to prevent sensitive info leakage in logs

## [1.3.3] - 2026-03-16

### Fixed
- Crash on startup: collectors invoked correctly during initialization
- Batch update exception handling added to background loop

## [1.3.2] - 2026-03-16

### Added
- Atomic batch data collection in background loop
- Layout debug=False enforcement

### Fixed
- Duplicate snapshot() method
- Header flickering

## [1.3.1] - 2026-03-16

### Fixed  
- Missing `os` import (crash in EXE)
- Windows screen buffer flicker (`screen=not is_windows`)

## [1.3.0] - 2026-03-16

### Added
- Dedicated GPU panel (separate from CPU panel)
- Per-GPU: Load, VRAM usage, Temperature

## [1.2.9] - 2026-03-15

### Fixed
- nvidia-smi fallback path on Windows (`C:\Program Files\NVIDIA Corporation\NVSMI\`)
- UI flickering via state versioning

## [1.2.8] - 2026-03-12

### Added
- Initial stable release on PyPI
- Live terminal dashboard with Rich
- CPU, Memory, Disk, Network, Process, Docker panels
- GPU panel (NVIDIA)
- Windows + Linux support
