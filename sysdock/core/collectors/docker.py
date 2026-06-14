"""Docker collector — optional, cross-platform, capability-gated.

Uses the Docker SDK when it is installed and the daemon is reachable. When
either is missing it returns a typed "unavailable" sample with a reason rather
than raising — Docker is an optional extra, never a hard requirement.

The CPU and memory math matches ``docker stats`` exactly:
* CPU%  = (cpu_delta / system_delta) * online_cpus * 100
* Memory = usage - page_cache (inactive_file on cgroups v2, cache on v1)
"""

from __future__ import annotations

import time
from dataclasses import dataclass, field
from typing import Any

from sysdock.core.logging import get_logger

log = get_logger(__name__)

# Cap per-tick stats work: only sample stats for running containers, and bound
# how many we touch so a host with hundreds of containers can't stall the timer.
_MAX_STATS_CONTAINERS = 50

# Don't re-probe an unreachable daemon on every tick (the ping costs seconds);
# back off and retry occasionally so a daemon that starts later is still picked up.
_PROBE_TTL = 30.0


@dataclass
class ContainerStats:
    cpu_percent: float = 0.0
    mem_used: int = 0
    mem_limit: int = 0
    mem_percent: float = 0.0


@dataclass
class Container:
    id: str
    name: str
    image: str
    status: str
    stats: ContainerStats | None = None


@dataclass
class DockerSample:
    available: bool = False
    reason: str = ""
    running: int = 0
    total: int = 0
    containers: list[Container] = field(default_factory=list)


def _parse_cpu(raw: dict[str, Any]) -> float:
    try:
        cpu_stats = raw["cpu_stats"]
        precpu = raw["precpu_stats"]
        cpu_delta = cpu_stats["cpu_usage"]["total_usage"] - precpu["cpu_usage"]["total_usage"]
        system_delta = cpu_stats.get("system_cpu_usage", 0) - precpu.get("system_cpu_usage", 0)
        ncpu = cpu_stats.get("online_cpus") or len(cpu_stats["cpu_usage"].get("percpu_usage", [1]))
        if system_delta > 0 and cpu_delta > 0:
            return round(float((cpu_delta / system_delta) * ncpu * 100.0), 2)
    except (KeyError, TypeError, ZeroDivisionError):
        pass
    return 0.0


def _parse_mem(raw: dict[str, Any]) -> tuple[int, int, float]:
    try:
        mem = raw.get("memory_stats", {})
        usage = int(mem.get("usage", 0))
        limit = int(mem.get("limit", 0))
        stats = mem.get("stats", {})
        cache = int(stats.get("inactive_file", stats.get("cache", 0)))
        used = max(0, usage - cache)
        pct = round(used / limit * 100.0, 2) if limit else 0.0
        return used, limit, pct
    except (KeyError, TypeError, ValueError):
        return 0, 0, 0.0


def parse_stats(raw: dict[str, Any]) -> ContainerStats:
    """Parse a raw Docker stats payload into normalised numbers (pure; tested)."""
    used, limit, pct = _parse_mem(raw)
    return ContainerStats(
        cpu_percent=_parse_cpu(raw),
        mem_used=used,
        mem_limit=limit,
        mem_percent=pct,
    )


class DockerCollector:
    def __init__(self) -> None:
        self._client: Any | None = None
        self._unavailable_reason: str | None = None
        self._sdk_missing = False  # permanent: import can't start succeeding mid-run
        self._last_probe: float = 0.0

    def prime(self) -> None:
        """Do the first (potentially slow) daemon probe off the timed path."""
        self._get_client()

    def _get_client(self) -> Any | None:
        if self._client is not None:
            return self._client
        if self._sdk_missing:
            return None
        # Throttle re-probing an unreachable daemon.
        now = time.monotonic()
        if self._last_probe and now - self._last_probe < _PROBE_TTL:
            return None
        self._last_probe = now
        try:
            import docker
        except ImportError:
            self._sdk_missing = True
            self._unavailable_reason = "docker SDK not installed (pip install sysdock[docker])"
            return None
        try:
            client = docker.from_env(timeout=3)
            client.ping()
        except Exception as exc:
            self._unavailable_reason = f"docker daemon unreachable: {exc}"
            return None
        self._client = client
        self._unavailable_reason = None
        return client

    def collect(self) -> DockerSample:
        client = self._get_client()
        if client is None:
            return DockerSample(available=False, reason=self._unavailable_reason or "unavailable")

        try:
            raw_containers = client.containers.list(all=True)
        except Exception as exc:
            # Daemon went away between ping and list — reset and degrade cleanly.
            self._client = None
            return DockerSample(available=False, reason=f"docker list failed: {exc}")

        containers: list[Container] = []
        running = 0
        stats_budget = _MAX_STATS_CONTAINERS
        for c in raw_containers:
            try:
                attrs = c.attrs
                status = attrs.get("State", {}).get("Status", "unknown")
                entry = Container(
                    id=c.short_id,
                    name=c.name,
                    image=(attrs.get("Config", {}) or {}).get("Image", "?"),
                    status=status,
                )
                if status == "running":
                    running += 1
                    if stats_budget > 0:
                        stats_budget -= 1
                        try:
                            entry.stats = parse_stats(c.stats(stream=False))
                        except Exception as exc:
                            log.debug("stats(%s) failed: %s", c.name, exc)
                containers.append(entry)
            except Exception as exc:  # pragma: no cover
                log.debug("container read failed: %s", exc)
                continue

        containers.sort(key=lambda c: c.name)
        return DockerSample(
            available=True,
            running=running,
            total=len(containers),
            containers=containers,
        )
