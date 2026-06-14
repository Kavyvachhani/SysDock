"""Normalized GPU schema (vendor-agnostic).

One shape across NVIDIA / AMD / Intel / Apple. When no supported GPU is present
the sample is ``available=False`` with a reason and an empty device list — the
UI simply hides the panel; it is never an error.
"""

from __future__ import annotations

from dataclasses import dataclass, field


@dataclass
class GpuProcess:
    pid: int
    name: str = ""
    used_memory: int = 0  # bytes of GPU memory


@dataclass
class GpuDevice:
    vendor: str  # nvidia / amd / intel / apple
    index: int
    name: str
    util_percent: float | None = None  # None when the OS won't expose it sudoless
    mem_used: int | None = None  # bytes
    mem_total: int | None = None  # bytes
    mem_percent: float | None = None
    temp_c: float | None = None
    power_w: float | None = None
    processes: list[GpuProcess] = field(default_factory=list)


@dataclass
class GpuSample:
    available: bool = False
    reason: str = ""
    devices: list[GpuDevice] = field(default_factory=list)
