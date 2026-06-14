"""CPU collector — per-core delta sampling, frequency, and load average.

CPU percentages are computed the htop way: as a delta between successive reads.
``psutil.cpu_percent(interval=None)`` returns usage since the *previous* call, so
when the snapshot timer calls :meth:`CpuCollector.collect` every couple of
seconds the numbers are accurate and non-blocking. :meth:`prime` seeds the first
delta so a cold one-shot read is still sensible.
"""

from __future__ import annotations

import os
import platform
from dataclasses import dataclass, field

from sysdock.core import proc
from sysdock.core.logging import get_logger

try:
    import psutil
except ImportError:  # pragma: no cover - psutil is a hard dependency
    psutil = None

log = get_logger(__name__)


@dataclass
class CpuSample:
    total_percent: float
    per_core_percent: list[float] = field(default_factory=list)
    physical_cores: int = 0
    logical_cores: int = 0
    model: str = "unknown"
    freq_mhz: float | None = None
    freq_max_mhz: float | None = None
    load_avg: list[float] | None = None  # 1/5/15 min; None where unsupported


class CpuCollector:
    """Stateful CPU collector. Reused across ticks so deltas are meaningful."""

    def __init__(self) -> None:
        self._model: str | None = None
        self._physical: int = 0
        self._logical: int = 0
        self._primed = False

    def prime(self) -> None:
        """Seed the delta baseline so the first real sample is accurate."""
        if psutil is None:
            return
        try:
            psutil.cpu_percent(interval=None)
            psutil.cpu_percent(interval=None, percpu=True)
            self._primed = True
        except Exception as exc:  # pragma: no cover - platform dependent
            log.debug("cpu prime failed: %s", exc)

    def _static(self) -> tuple[str, int, int]:
        if self._model is not None:
            return self._model, self._physical, self._logical
        model = self._detect_model()
        physical = 0
        logical = 0
        if psutil is not None:
            try:
                physical = int(psutil.cpu_count(logical=False) or 0)
                logical = int(psutil.cpu_count(logical=True) or 0)
            except Exception as exc:  # pragma: no cover
                log.debug("cpu_count failed: %s", exc)
        self._model, self._physical, self._logical = model, physical, logical
        return model, physical, logical

    @staticmethod
    def _detect_model() -> str:
        system = platform.system()
        if system == "Linux":
            try:
                with open("/proc/cpuinfo") as fh:
                    for line in fh:
                        if "model name" in line:
                            return line.split(":", 1)[1].strip()
            except OSError:
                pass
        elif system == "Darwin":
            res = proc.run(["sysctl", "-n", "machdep.cpu.brand_string"], timeout=2)
            if res.ok and res.stdout.strip():
                return res.stdout.strip()
        return platform.processor() or platform.machine() or "unknown"

    def _load_avg(self) -> list[float] | None:
        getloadavg = getattr(os, "getloadavg", None)
        if callable(getloadavg):
            try:
                return [round(x, 2) for x in getloadavg()]
            except OSError:
                return None
        return None

    def collect(self) -> CpuSample:
        if psutil is None:  # pragma: no cover
            return CpuSample(total_percent=0.0)

        model, physical, logical = self._static()

        try:
            total = float(psutil.cpu_percent(interval=None))
        except Exception:
            total = 0.0
        try:
            per_core = [float(x) for x in psutil.cpu_percent(interval=None, percpu=True)]
        except Exception:
            per_core = []

        freq_mhz: float | None = None
        freq_max: float | None = None
        try:
            freq = psutil.cpu_freq()
            if freq is not None:
                freq_mhz = round(float(freq.current), 1) if freq.current else None
                freq_max = round(float(freq.max), 1) if freq.max else None
        except Exception as exc:
            log.debug("cpu_freq failed: %s", exc)

        return CpuSample(
            total_percent=round(total, 1),
            per_core_percent=[round(x, 1) for x in per_core],
            physical_cores=physical,
            logical_cores=logical,
            model=model,
            freq_mhz=freq_mhz,
            freq_max_mhz=freq_max,
            load_avg=self._load_avg(),
        )
