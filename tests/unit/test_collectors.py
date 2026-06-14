"""Live smoke + sanity tests for the psutil collectors.

These run on every CI OS (the per-OS live smoke test). They assert structure and
value bounds rather than exact numbers, which vary by host.
"""

from __future__ import annotations

from sysdock.core.collectors.cpu import CpuCollector
from sysdock.core.collectors.disk import DiskCollector
from sysdock.core.collectors.host import HostCollector, _human_uptime
from sysdock.core.collectors.memory import MemoryCollector
from sysdock.core.collectors.network import NetworkCollector
from sysdock.core.collectors.processes import ProcessCollector


def test_cpu_sample_bounds_and_static():
    c = CpuCollector()
    c.prime()
    s = c.collect()
    assert 0.0 <= s.total_percent <= 100.0 * max(1, s.logical_cores)
    assert s.logical_cores >= 1
    assert s.model
    for core in s.per_core_percent:
        assert 0.0 <= core <= 100.0


def test_memory_sample_is_sane():
    s = MemoryCollector().collect()
    assert s.total > 0
    assert 0.0 <= s.percent <= 100.0
    assert s.used <= s.total
    assert 0.0 <= s.swap_percent <= 100.0


def test_disk_partitions_have_bounded_percent():
    s = DiskCollector().collect()
    # At least one partition on any real host.
    assert s.partitions
    for p in s.partitions:
        assert 0.0 <= p.percent <= 100.0
        assert p.mountpoint


def test_disk_io_rates_non_negative_after_two_samples():
    c = DiskCollector()
    c.collect()
    s = c.collect()
    if s.io is not None:
        assert s.io.read_bytes_per_s >= 0
        assert s.io.write_bytes_per_s >= 0


def test_network_interfaces_and_rates():
    c = NetworkCollector()
    c.collect()
    s = c.collect()
    assert s.interfaces  # loopback exists everywhere
    for nic in s.interfaces:
        assert nic.tx_bytes_per_s >= 0
        assert nic.rx_bytes_per_s >= 0


def test_processes_sorted_and_capped():
    c = ProcessCollector(top_n=5)
    c.prime()
    s = c.collect()
    assert s.count > 0
    assert len(s.top_by_cpu) <= 5
    cpus = [p.cpu_percent for p in s.top_by_cpu]
    assert cpus == sorted(cpus, reverse=True)


def test_host_sample():
    s = HostCollector().collect()
    assert s.hostname
    assert s.os
    assert s.uptime_seconds >= 0


def test_human_uptime_formatting():
    assert _human_uptime(0) == "0d 0h 0m"
    assert _human_uptime(90061) == "1d 1h 1m"
