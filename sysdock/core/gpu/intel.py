"""Intel GPU backend via intel_gpu_top (JSON output).

``intel_gpu_top -J`` streams JSON objects. We capture one sample with a short
timeout and parse the busiest engine as utilisation. intel_gpu_top often needs
elevation; if it isn't readable we simply report no Intel device (the panel
hides) rather than erroring.
"""

from __future__ import annotations

import json

from sysdock.core import proc
from sysdock.core.gpu.schema import GpuDevice
from sysdock.core.logging import get_logger

log = get_logger(__name__)


def available() -> bool:
    return proc.which("intel_gpu_top") is not None


def _first_json_object(text: str) -> str | None:
    """Extract the first complete top-level JSON object from a stream."""
    depth = 0
    start = -1
    for i, ch in enumerate(text):
        if ch == "{":
            if depth == 0:
                start = i
            depth += 1
        elif ch == "}":
            depth -= 1
            if depth == 0 and start != -1:
                return text[start : i + 1]
    return None


def parse_intel_json(text: str) -> list[GpuDevice]:
    blob = _first_json_object(text)
    if not blob:
        return []
    try:
        data = json.loads(blob)
    except (json.JSONDecodeError, ValueError):
        return []
    if not isinstance(data, dict):
        return []

    engines = data.get("engines", {})
    best = None
    if isinstance(engines, dict):
        for eng in engines.values():
            if isinstance(eng, dict) and "busy" in eng:
                busy = eng.get("busy")
                if isinstance(busy, (int, float)):
                    best = busy if best is None else max(best, busy)
    power = None
    pwr = data.get("power", {})
    if isinstance(pwr, dict):
        val = pwr.get("GPU") or pwr.get("Package")
        if isinstance(val, (int, float)):
            power = float(val)

    return [
        GpuDevice(
            vendor="intel",
            index=0,
            name="Intel GPU",
            util_percent=round(float(best), 1) if best is not None else None,
            power_w=power,
        )
    ]


def collect() -> list[GpuDevice]:
    if not available():
        return []
    # -o - writes to stdout; a short run yields one or more samples we can parse.
    res = proc.run(["intel_gpu_top", "-J", "-s", "500", "-o", "-"], timeout=4)
    if res.timed_out and not res.stdout.strip():
        return []
    if not res.stdout.strip():
        return []
    return parse_intel_json(res.stdout)
