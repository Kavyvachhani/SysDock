"""Disk collector — per-partition usage plus delta-based global I/O rates.

The partition list is enumerated occasionally (it rarely changes) and cached;
usage is read each tick. Global I/O counters are converted to per-second rates
using the elapsed monotonic time between samples.
"""

from __future__ import annotations

import time
from dataclasses import dataclass, field

from sysdock.core.logging import get_logger

try:
    import psutil
except ImportError:  # pragma: no cover
    psutil = None

log = get_logger(__name__)

# How long a cached partition list stays valid (seconds).
_PARTITION_TTL = 30.0


@dataclass
class DiskPartition:
    device: str
    mountpoint: str
    fstype: str
    total: int = 0
    used: int = 0
    free: int = 0
    percent: float = 0.0


@dataclass
class DiskIO:
    read_bytes: int = 0
    write_bytes: int = 0
    read_bytes_per_s: float = 0.0
    write_bytes_per_s: float = 0.0


@dataclass
class DiskSample:
    partitions: list[DiskPartition] = field(default_factory=list)
    io: DiskIO | None = None


class DiskCollector:
    def __init__(self) -> None:
        self._partitions_cache: list[tuple[str, str, str]] = []
        self._partitions_at: float = 0.0
        self._prev_io: tuple[float, int, int] | None = None  # (ts, read, write)

    def _partition_list(self) -> list[tuple[str, str, str]]:
        now = time.monotonic()
        if self._partitions_cache and now - self._partitions_at < _PARTITION_TTL:
            return self._partitions_cache
        result: list[tuple[str, str, str]] = []
        if psutil is not None:
            try:
                for part in psutil.disk_partitions(all=False):
                    result.append((part.device, part.mountpoint, part.fstype))
            except Exception as exc:
                log.debug("disk_partitions failed: %s", exc)
        self._partitions_cache = result
        self._partitions_at = now
        return result

    def _io(self) -> DiskIO | None:
        if psutil is None:
            return None
        try:
            counters = psutil.disk_io_counters()
        except Exception as exc:  # pragma: no cover - platform dependent
            log.debug("disk_io_counters failed: %s", exc)
            return None
        if counters is None:
            return None
        now = time.monotonic()
        read_b = int(counters.read_bytes)
        write_b = int(counters.write_bytes)
        read_rate = write_rate = 0.0
        if self._prev_io is not None:
            prev_ts, prev_r, prev_w = self._prev_io
            dt = now - prev_ts
            if dt > 0:
                read_rate = max(0.0, (read_b - prev_r) / dt)
                write_rate = max(0.0, (write_b - prev_w) / dt)
        self._prev_io = (now, read_b, write_b)
        return DiskIO(
            read_bytes=read_b,
            write_bytes=write_b,
            read_bytes_per_s=round(read_rate, 1),
            write_bytes_per_s=round(write_rate, 1),
        )

    def collect(self) -> DiskSample:
        partitions: list[DiskPartition] = []
        for device, mountpoint, fstype in self._partition_list():
            part = DiskPartition(device=device, mountpoint=mountpoint, fstype=fstype)
            if psutil is not None:
                try:
                    usage = psutil.disk_usage(mountpoint)
                    part.total = int(usage.total)
                    part.used = int(usage.used)
                    part.free = int(usage.free)
                    part.percent = round(float(usage.percent), 1)
                except (PermissionError, OSError) as exc:
                    # Unreadable mount (e.g. permission-denied) — keep it listed
                    # with zeroed usage rather than dropping or crashing.
                    log.debug("disk_usage(%s) failed: %s", mountpoint, exc)
            partitions.append(part)
        return DiskSample(partitions=partitions, io=self._io())
