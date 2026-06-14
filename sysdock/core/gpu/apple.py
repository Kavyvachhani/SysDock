"""Apple Silicon / Apple GPU backend.

Detects the GPU via ``system_profiler SPDisplaysDataType`` (name and core count)
and reports the unified-memory pool as the memory total. Live utilisation on
Apple Silicon is not available without elevation (``powermetrics`` needs sudo;
sudoless IOReport requires fragile private-framework access), so ``util_percent``
is reported as ``None`` rather than guessing — the device is still shown.
"""

from __future__ import annotations

import re

from sysdock.core import capabilities as caps
from sysdock.core.gpu.schema import GpuDevice
from sysdock.core.logging import get_logger

log = get_logger(__name__)


def available() -> bool:
    return caps.current_platform() == caps.PLATFORM_MACOS


def parse_displays(text: str, mem_total: int | None = None) -> list[GpuDevice]:
    """Parse ``system_profiler SPDisplaysDataType`` for the GPU name/cores."""
    name = ""
    cores: int | None = None
    for raw in text.splitlines():
        line = raw.strip()
        if line.startswith("Chipset Model:"):
            name = line.split(":", 1)[1].strip()
        elif line.startswith("Total Number of Cores:"):
            m = re.search(r"\d+", line)
            if m:
                cores = int(m.group())
    if not name:
        return []
    if cores:
        name = f"{name} ({cores}-core GPU)"
    return [
        GpuDevice(
            vendor="apple",
            index=0,
            name=name,
            mem_total=mem_total,
        )
    ]


def _unified_memory() -> int | None:
    res = _sysctl("hw.memsize")
    return int(res) if res and res.isdigit() else None


def _sysctl(key: str) -> str | None:
    from sysdock.core import proc

    r = proc.run(["sysctl", "-n", key], timeout=2)
    return r.stdout.strip() if r.ok else None


def collect() -> list[GpuDevice]:
    if not available():
        return []
    from sysdock.core import proc

    res = proc.run(["system_profiler", "SPDisplaysDataType"], timeout=8)
    if not res.ok or not res.stdout.strip():
        return []
    return parse_displays(res.stdout, mem_total=_unified_memory())
