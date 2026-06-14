"""Docker stats parsing — fixture-tested against a recorded API payload.

Verifies the math matches `docker stats`:
  CPU%  = (cpu_delta / system_delta) * online_cpus * 100
  used  = memory usage - page cache (inactive_file)
"""

from __future__ import annotations

from sysdock.core.collectors import docker as d

# A representative raw payload from the Docker stats API (trimmed to fields used).
RAW = {
    "cpu_stats": {
        "cpu_usage": {"total_usage": 200_000_000},
        "system_cpu_usage": 2_000_000_000,
        "online_cpus": 4,
    },
    "precpu_stats": {
        "cpu_usage": {"total_usage": 100_000_000},
        "system_cpu_usage": 1_500_000_000,
    },
    "memory_stats": {
        "usage": 200 * 1024 * 1024,  # 200 MiB
        "limit": 1024 * 1024 * 1024,  # 1 GiB
        "stats": {"inactive_file": 50 * 1024 * 1024},  # 50 MiB page cache
    },
}


def test_cpu_percent_matches_docker_formula():
    stats = d.parse_stats(RAW)
    # cpu_delta=1e8, sys_delta=5e8, ncpu=4 -> (0.2)*4*100 = 80.0
    assert stats.cpu_percent == 80.0


def test_memory_subtracts_page_cache():
    stats = d.parse_stats(RAW)
    assert stats.mem_used == 150 * 1024 * 1024  # 200 - 50 MiB
    assert stats.mem_limit == 1024 * 1024 * 1024
    assert stats.mem_percent == round(150 / 1024 * 100, 2)


def test_zero_system_delta_yields_zero_cpu():
    raw = {
        "cpu_stats": {"cpu_usage": {"total_usage": 100}, "system_cpu_usage": 100, "online_cpus": 2},
        "precpu_stats": {"cpu_usage": {"total_usage": 50}, "system_cpu_usage": 100},
    }
    assert d.parse_stats(raw).cpu_percent == 0.0


def test_malformed_payload_degrades_to_zero():
    assert d.parse_stats({}).cpu_percent == 0.0
    assert d.parse_stats({}).mem_used == 0


def test_online_cpus_falls_back_to_percpu_length():
    raw = {
        "cpu_stats": {
            "cpu_usage": {"total_usage": 200, "percpu_usage": [1, 1, 1, 1]},
            "system_cpu_usage": 2000,
        },
        "precpu_stats": {"cpu_usage": {"total_usage": 100}, "system_cpu_usage": 1500},
    }
    # ncpu derived from len(percpu_usage)=4 -> (100/500)*4*100 = 80
    assert d.parse_stats(raw).cpu_percent == 80.0


def test_collector_degrades_without_sdk_or_daemon():
    sample = d.DockerCollector().collect()
    # In the test environment there is no daemon; must be a clean unavailable.
    assert sample.available is False
    assert sample.reason
    assert sample.containers == []
