# Changelog

All notable changes to SysDock are documented here.

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
- **Zero SmartScreen warnings**: build manifest and authenticode metadata embedded in Windows EXE
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
