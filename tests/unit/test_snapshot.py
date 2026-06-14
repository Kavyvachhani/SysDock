"""Snapshot provider: TTL cache, request coalescing, timer, and perf ceiling."""

from __future__ import annotations

import json
import os
import threading
import time

from sysdock.core.snapshot import Snapshot, SnapshotProvider

# Generous ceiling so it holds on slow CI runners while still catching gross
# regressions. Override with SYSDOCK_BENCH_CEILING_MS.
_CEILING_MS = float(os.environ.get("SYSDOCK_BENCH_CEILING_MS", "1500"))


def _provider() -> SnapshotProvider:
    # Docker/security/GPU are exercised in their own test modules; disabling them
    # here keeps these snapshot tests fast and focused on cache/coalescing/perf.
    return SnapshotProvider(ttl=5.0, enable_docker=False, enable_security=False, enable_gpu=False)


def test_get_returns_full_snapshot_and_serialises():
    snap = _provider().get(force=True)
    assert isinstance(snap, Snapshot)
    payload = json.dumps(snap.to_dict(), default=str)
    data = json.loads(payload)
    for key in ("host", "cpu", "memory", "disk", "network", "processes", "docker"):
        assert key in data
    assert data["cpu"]["logical_cores"] >= 1


def test_ttl_cache_serves_without_recollecting():
    p = _provider()
    p.get()
    p.get()
    p.get()
    assert p.collection_count == 1


def test_force_bypasses_cache():
    p = _provider()
    p.get()
    p.get(force=True)
    assert p.collection_count == 2


def test_concurrent_reads_cause_single_collection():
    p = _provider()
    p.prime()
    real_collect = p._collect
    calls: list[int] = []

    def slow_collect() -> Snapshot:
        calls.append(1)
        time.sleep(0.3)
        return real_collect()

    p._collect = slow_collect  # type: ignore[method-assign]

    results: list[Snapshot] = []
    barrier = threading.Barrier(10)

    def worker() -> None:
        barrier.wait()
        results.append(p.get(force=True))

    threads = [threading.Thread(target=worker) for _ in range(10)]
    for t in threads:
        t.start()
    for t in threads:
        t.join()

    # 10 concurrent readers, exactly one underlying collection.
    assert len(calls) == 1
    assert p.collection_count == 1
    assert len(results) == 10


def test_background_timer_refreshes_then_stops():
    p = SnapshotProvider(
        ttl=0.0, interval=0.1, enable_docker=False, enable_security=False, enable_gpu=False
    )
    p.start()
    time.sleep(0.45)
    p.stop()
    count_after_stop = p.collection_count
    assert count_after_stop >= 2
    time.sleep(0.25)
    # No further collections once stopped.
    assert p.collection_count == count_after_stop


def test_single_collection_under_ceiling():
    p = _provider()
    p.prime()
    durations = []
    for _ in range(3):
        snap = p.get(force=True)
        durations.append(snap.collection_ms)
    median = sorted(durations)[len(durations) // 2]
    assert median < _CEILING_MS, f"collection median {median}ms exceeded ceiling {_CEILING_MS}ms"
