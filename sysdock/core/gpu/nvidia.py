"""NVIDIA GPU backend via nvidia-ml-py (pynvml).

Every NVML call is guarded: a missing library, absent driver, or per-metric
failure degrades to ``None``/empty rather than raising. Reports utilisation,
VRAM, temperature, power, and per-process GPU memory.
"""

from __future__ import annotations

import contextlib
from typing import Any

from sysdock.core.gpu.schema import GpuDevice, GpuProcess
from sysdock.core.logging import get_logger

log = get_logger(__name__)


def available() -> bool:
    try:
        import pynvml  # noqa: F401
    except ImportError:
        return False
    return True


def collect() -> list[GpuDevice]:
    try:
        import pynvml
    except ImportError:
        return []

    try:
        pynvml.nvmlInit()
    except Exception as exc:
        log.debug("nvmlInit failed (no NVIDIA driver?): %s", exc)
        return []

    devices: list[GpuDevice] = []
    try:
        count = pynvml.nvmlDeviceGetCount()
        for i in range(count):
            devices.append(_read_device(pynvml, i))
    except Exception as exc:
        log.debug("nvml enumerate failed: %s", exc)
    finally:
        with contextlib.suppress(Exception):
            pynvml.nvmlShutdown()
    return devices


def _read_device(pynvml: Any, index: int) -> GpuDevice:
    handle = pynvml.nvmlDeviceGetHandleByIndex(index)
    dev = GpuDevice(vendor="nvidia", index=index, name=_name(pynvml, handle))

    with contextlib.suppress(Exception):
        dev.util_percent = float(pynvml.nvmlDeviceGetUtilizationRates(handle).gpu)
    with contextlib.suppress(Exception):
        mem = pynvml.nvmlDeviceGetMemoryInfo(handle)
        dev.mem_used = int(mem.used)
        dev.mem_total = int(mem.total)
        dev.mem_percent = round(mem.used / mem.total * 100, 1) if mem.total else None
    with contextlib.suppress(Exception):
        dev.temp_c = float(pynvml.nvmlDeviceGetTemperature(handle, pynvml.NVML_TEMPERATURE_GPU))
    with contextlib.suppress(Exception):
        dev.power_w = round(pynvml.nvmlDeviceGetPowerUsage(handle) / 1000.0, 1)
    dev.processes = _processes(pynvml, handle)
    return dev


def _name(pynvml: Any, handle: Any) -> str:
    try:
        name = pynvml.nvmlDeviceGetName(handle)
        return name.decode() if isinstance(name, bytes) else str(name)
    except Exception:
        return "NVIDIA GPU"


def _processes(pynvml: Any, handle: Any) -> list[GpuProcess]:
    procs: list[GpuProcess] = []
    with contextlib.suppress(Exception):
        for p in pynvml.nvmlDeviceGetComputeRunningProcesses(handle):
            used = int(getattr(p, "usedGpuMemory", 0) or 0)
            procs.append(GpuProcess(pid=int(p.pid), used_memory=used))
    return procs
