"""Memory collector — virtual and swap memory via psutil.

psutil already applies the platform-correct "used" calculation (on Linux it
excludes buffers/cache, matching htop closely enough), so we rely on it for
cross-platform consistency rather than re-parsing /proc here.
"""

from __future__ import annotations

from dataclasses import dataclass

from sysdock.core.logging import get_logger

try:
    import psutil
except ImportError:  # pragma: no cover
    psutil = None

log = get_logger(__name__)


@dataclass
class MemorySample:
    total: int = 0
    available: int = 0
    used: int = 0
    free: int = 0
    percent: float = 0.0
    swap_total: int = 0
    swap_used: int = 0
    swap_free: int = 0
    swap_percent: float = 0.0


class MemoryCollector:
    """Stateless memory collector (psutil keeps no cross-call state here)."""

    def collect(self) -> MemorySample:
        if psutil is None:  # pragma: no cover
            return MemorySample()
        sample = MemorySample()
        try:
            vm = psutil.virtual_memory()
            sample.total = int(vm.total)
            sample.available = int(vm.available)
            sample.used = int(vm.used)
            sample.free = int(vm.free)
            sample.percent = round(float(vm.percent), 1)
        except Exception as exc:
            log.debug("virtual_memory failed: %s", exc)
        try:
            sw = psutil.swap_memory()
            sample.swap_total = int(sw.total)
            sample.swap_used = int(sw.used)
            sample.swap_free = int(sw.free)
            sample.swap_percent = round(float(sw.percent), 1)
        except Exception as exc:
            log.debug("swap_memory failed: %s", exc)
        return sample
