"""GPU panel — capability-gated, multi-vendor, never an error.

`GpuCollector` probes NVIDIA, AMD, Intel, and Apple backends, aggregating every
device found (a host may have more than one vendor). When nothing supported is
present, the sample is ``available=False`` and the UI hides the panel. Backend
probes are cached on a TTL so the shared snapshot timer doesn't shell out every
tick, and every backend is wrapped so a failure can never crash the snapshot.
"""

from __future__ import annotations

import time
from typing import Callable

from sysdock.core.gpu import amd, apple, intel, nvidia
from sysdock.core.gpu.schema import GpuDevice, GpuSample
from sysdock.core.logging import get_logger

log = get_logger(__name__)

DEFAULT_TTL = 5.0

# (vendor label, collect callable)
_BACKENDS: list[tuple[str, Callable[[], list[GpuDevice]]]] = [
    ("nvidia", nvidia.collect),
    ("amd", amd.collect),
    ("intel", intel.collect),
    ("apple", apple.collect),
]


class GpuCollector:
    def __init__(self, *, ttl: float = DEFAULT_TTL) -> None:
        self.ttl = ttl
        self._cache: GpuSample | None = None
        self._cached_at: float = 0.0

    def prime(self) -> None:
        """Run the first probe off the timed path."""
        self.collect()

    def collect(self) -> GpuSample:
        now = time.monotonic()
        if self._cache is not None and (now - self._cached_at) < self.ttl:
            return self._cache

        devices: list[GpuDevice] = []
        for vendor, fn in _BACKENDS:
            try:
                devices.extend(fn())
            except Exception as exc:
                log.warning("gpu backend %s failed: %s", vendor, exc)

        if devices:
            sample = GpuSample(available=True, devices=devices)
        else:
            sample = GpuSample(available=False, reason="no supported GPU detected")

        self._cache = sample
        self._cached_at = now
        return sample
