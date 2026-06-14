"""AMD GPU backend via rocm-smi (JSON output).

``rocm-smi --showuse --showmemuse --showtemp --showpower --json`` emits a dict
keyed by card ("card0", ...). The parser is pure and fixture-tested; the keys
rocm-smi uses have varied across versions, so it matches defensively.
"""

from __future__ import annotations

import json
import re

from sysdock.core import proc
from sysdock.core.gpu.schema import GpuDevice
from sysdock.core.logging import get_logger

log = get_logger(__name__)


def available() -> bool:
    return proc.which("rocm-smi") is not None


def _num(value: object) -> float | None:
    if value is None:
        return None
    m = re.search(r"-?\d+(?:\.\d+)?", str(value))
    return float(m.group()) if m else None


def _find(
    card: dict[str, object], include: tuple[str, ...], exclude: tuple[str, ...] = ()
) -> object:
    for key, val in card.items():
        low = key.lower()
        if all(n in low for n in include) and not any(x in low for x in exclude):
            return val
    return None


def parse_rocm_json(text: str) -> list[GpuDevice]:
    try:
        data = json.loads(text)
    except (json.JSONDecodeError, ValueError):
        return []
    if not isinstance(data, dict):
        return []

    devices: list[GpuDevice] = []
    for idx, (_card_key, card) in enumerate(sorted(data.items())):
        if not isinstance(card, dict):
            continue
        name = str(
            _find(card, ("card series",)) or _find(card, ("card model",)) or f"AMD GPU {idx}"
        )
        util = _num(_find(card, ("gpu", "use")))
        mem_used = _num(_find(card, ("used",), exclude=("%",)))
        mem_total = _num(_find(card, ("total", "memory"), exclude=("used",)))
        temp = _num(_find(card, ("temperature", "edge"))) or _num(_find(card, ("temperature",)))
        power = _num(_find(card, ("average", "power"))) or _num(_find(card, ("power",)))
        mem_pct = (
            round(mem_used / mem_total * 100, 1) if mem_used is not None and mem_total else None
        )
        devices.append(
            GpuDevice(
                vendor="amd",
                index=idx,
                name=name,
                util_percent=util,
                mem_used=int(mem_used) if mem_used is not None else None,
                mem_total=int(mem_total) if mem_total is not None else None,
                mem_percent=mem_pct,
                temp_c=temp,
                power_w=power,
            )
        )
    return devices


def collect() -> list[GpuDevice]:
    if not available():
        return []
    res = proc.run(
        ["rocm-smi", "--showuse", "--showmemuse", "--showtemp", "--showpower", "--json"],
        timeout=6,
    )
    if not res.ok or not res.stdout.strip():
        return []
    return parse_rocm_json(res.stdout)
