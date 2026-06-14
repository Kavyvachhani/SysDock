"""Process collector — process table with delta-based per-process CPU%.

Per-process CPU percentage is a delta since the previous read of the same
``psutil.Process`` object. ``psutil.process_iter`` keeps a module-level cache of
those objects, so repeated calls (and :meth:`prime`) yield meaningful values.
"""

from __future__ import annotations

import contextlib
from dataclasses import dataclass, field

from sysdock.core.logging import get_logger

try:
    import psutil
except ImportError:  # pragma: no cover
    psutil = None

log = get_logger(__name__)

DEFAULT_TOP_N = 15
_ATTRS = ["pid", "name", "username", "memory_percent", "memory_info", "num_threads"]


@dataclass
class ProcessInfo:
    pid: int
    name: str = ""
    username: str = ""
    cpu_percent: float = 0.0
    memory_percent: float = 0.0
    rss: int = 0
    num_threads: int = 0


@dataclass
class ProcessSample:
    count: int = 0
    top_by_cpu: list[ProcessInfo] = field(default_factory=list)


class ProcessCollector:
    def __init__(self, top_n: int = DEFAULT_TOP_N) -> None:
        self.top_n = top_n
        self._logical_cores = 1
        if psutil is not None:
            with contextlib.suppress(Exception):  # pragma: no cover
                self._logical_cores = max(1, int(psutil.cpu_count(logical=True) or 1))

    def prime(self) -> None:
        """Seed per-process CPU deltas so the first real sample is meaningful."""
        if psutil is None:
            return
        for p in psutil.process_iter():
            with contextlib.suppress(psutil.NoSuchProcess, psutil.AccessDenied, Exception):
                p.cpu_percent(None)

    def collect(self) -> ProcessSample:
        if psutil is None:  # pragma: no cover
            return ProcessSample()

        procs: list[ProcessInfo] = []
        count = 0
        for p in psutil.process_iter(_ATTRS):
            count += 1
            try:
                info = p.info
                # cpu_percent is read off the cached object (delta since last read);
                # normalise by core count so a busy core reads <= 100% per process.
                cpu = float(p.cpu_percent(None)) / self._logical_cores
                mem_info = info.get("memory_info")
                rss = int(getattr(mem_info, "rss", 0)) if mem_info else 0
                procs.append(
                    ProcessInfo(
                        pid=int(info.get("pid") or 0),
                        name=info.get("name") or "",
                        username=info.get("username") or "",
                        cpu_percent=round(cpu, 1),
                        memory_percent=round(float(info.get("memory_percent") or 0.0), 1),
                        rss=rss,
                        num_threads=int(info.get("num_threads") or 0),
                    )
                )
            except (psutil.NoSuchProcess, psutil.AccessDenied):
                continue
            except Exception as exc:  # pragma: no cover
                log.debug("process read failed: %s", exc)
                continue

        procs.sort(key=lambda pi: pi.cpu_percent, reverse=True)
        return ProcessSample(count=count, top_by_cpu=procs[: self.top_n])
