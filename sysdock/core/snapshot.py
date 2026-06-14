"""The one shared snapshot every surface reads.

`SnapshotProvider` owns a single instance of each collector and produces a
`Snapshot`. It guarantees the property the whole performance budget hinges on:

* **TTL cache.** Reads within ``ttl`` seconds of the last collection return the
  cached snapshot — no work.
* **Request coalescing.** If a collection is already in flight, concurrent
  callers wait for and share its result instead of each starting their own. N
  concurrent HTTP clients therefore cause **one** collection, not N. (This is the
  amplification bug that plagued glances.)
* **Optional timer.** `start()` keeps the snapshot warm on an interval so the
  TUI, SSE stream, and `/metrics` all read fresh-but-shared data.

The TUI, web API, and Prometheus endpoint (added in later phases) all read from
one provider — there is no forked collection logic.
"""

from __future__ import annotations

import threading
import time
from dataclasses import asdict, dataclass, field
from datetime import datetime, timezone
from typing import Any

from sysdock.core.collectors.cpu import CpuCollector, CpuSample
from sysdock.core.collectors.disk import DiskCollector, DiskSample
from sysdock.core.collectors.docker import DockerCollector, DockerSample
from sysdock.core.collectors.host import HostCollector, HostSample
from sysdock.core.collectors.memory import MemoryCollector, MemorySample
from sysdock.core.collectors.network import NetworkCollector, NetworkSample
from sysdock.core.collectors.processes import ProcessCollector, ProcessSample
from sysdock.core.logging import get_logger

log = get_logger(__name__)

DEFAULT_TTL = 1.0
DEFAULT_INTERVAL = 2.0


@dataclass
class Snapshot:
    collected_at: float
    collected_at_iso: str
    host: HostSample
    cpu: CpuSample
    memory: MemorySample
    disk: DiskSample
    network: NetworkSample
    processes: ProcessSample
    docker: DockerSample
    collection_ms: float = 0.0
    errors: dict[str, str] = field(default_factory=dict)

    def to_dict(self) -> dict[str, Any]:
        """A JSON-serialisable view of the whole snapshot."""
        return asdict(self)


class SnapshotProvider:
    """Thread-safe, TTL-cached, request-coalescing snapshot source."""

    def __init__(
        self,
        *,
        ttl: float = DEFAULT_TTL,
        interval: float = DEFAULT_INTERVAL,
        top_n: int = 15,
        enable_docker: bool = True,
    ) -> None:
        self.ttl = ttl
        self.interval = interval
        self._host = HostCollector()
        self._cpu = CpuCollector()
        self._memory = MemoryCollector()
        self._disk = DiskCollector()
        self._network = NetworkCollector()
        self._processes = ProcessCollector(top_n=top_n)
        self._docker = DockerCollector() if enable_docker else None

        self._snapshot: Snapshot | None = None
        self._collected_at: float = 0.0
        self._collection_count = 0

        self._lock = threading.Lock()
        self._collecting = False
        self._done = threading.Event()
        self._primed = False

        self._timer_thread: threading.Thread | None = None
        self._stop = threading.Event()

    # ── priming ───────────────────────────────────────────────────────────────

    def prime(self) -> None:
        """Seed delta baselines so the first real collection is accurate.

        Runs the cheap seeding reads and a brief settle so a cold one-shot
        (``sysdock status``) still returns sensible CPU/process percentages.
        """
        if self._primed:
            return
        self._cpu.prime()
        self._processes.prime()
        if self._docker is not None:
            self._docker.prime()
        time.sleep(0.1)
        self._primed = True

    # ── collection ──────────────────────────────────────────────────────────--

    def _collect(self) -> Snapshot:
        start = time.monotonic()
        errors: dict[str, str] = {}

        def _safe(name: str, fn: Any, default: Any) -> Any:
            try:
                return fn()
            except Exception as exc:  # defensive: one collector can't break the snapshot
                log.warning("collector %s failed: %s", name, exc)
                errors[name] = str(exc)
                return default

        host = _safe("host", self._host.collect, HostSample())
        cpu = _safe("cpu", self._cpu.collect, CpuSample(total_percent=0.0))
        memory = _safe("memory", self._memory.collect, MemorySample())
        disk = _safe("disk", self._disk.collect, DiskSample())
        network = _safe("network", self._network.collect, NetworkSample())
        processes = _safe("processes", self._processes.collect, ProcessSample())
        if self._docker is not None:
            docker = _safe("docker", self._docker.collect, DockerSample(reason="collector error"))
        else:
            docker = DockerSample(available=False, reason="docker disabled")

        now = time.time()
        return Snapshot(
            collected_at=now,
            collected_at_iso=datetime.fromtimestamp(now, tz=timezone.utc).isoformat(),
            host=host,
            cpu=cpu,
            memory=memory,
            disk=disk,
            network=network,
            processes=processes,
            docker=docker,
            collection_ms=round((time.monotonic() - start) * 1000, 2),
            errors=errors,
        )

    def get(self, *, force: bool = False) -> Snapshot:
        """Return the latest snapshot, collecting only if stale.

        Concurrent callers that arrive while a collection is in flight wait for
        and share that single collection rather than triggering their own.
        """
        if not self._primed:
            self.prime()

        with self._lock:
            cached = self._snapshot
            fresh = (
                cached is not None
                and not force
                and (time.monotonic() - self._collected_at) < self.ttl
            )
            if fresh and cached is not None:
                return cached

            if self._collecting:
                # Someone else is collecting — wait for them and share the result.
                done = self._done
                wait = True
            else:
                self._collecting = True
                self._done = threading.Event()
                wait = False

        if wait:
            done.wait(timeout=self.interval + 10.0)
            with self._lock:
                if self._snapshot is not None:
                    return self._snapshot
            # Fell through (collector failed to publish) — collect synchronously.
            return self._collect()

        # We are the designated collector.
        try:
            snapshot = self._collect()
            with self._lock:
                self._snapshot = snapshot
                self._collected_at = time.monotonic()
                self._collection_count += 1
            return snapshot
        finally:
            with self._lock:
                self._collecting = False
                self._done.set()

    @property
    def collection_count(self) -> int:
        """Number of real collections performed (for tests/benchmarks)."""
        return self._collection_count

    # ── background timer ────────────────────────────────────────────────────--

    def start(self) -> None:
        """Begin refreshing the snapshot on a timer in a daemon thread."""
        if self._timer_thread is not None:
            return
        self.prime()
        self._stop.clear()
        self._timer_thread = threading.Thread(
            target=self._run_timer, name="sysdock-snapshot", daemon=True
        )
        self._timer_thread.start()

    def _run_timer(self) -> None:
        while not self._stop.is_set():
            try:
                self.get(force=True)
            except Exception as exc:  # pragma: no cover - defensive
                log.error("snapshot timer collection failed: %s", exc)
            self._stop.wait(self.interval)

    def stop(self) -> None:
        """Stop the background timer."""
        self._stop.set()
        thread = self._timer_thread
        if thread is not None:
            thread.join(timeout=self.interval + 1.0)
        self._timer_thread = None
