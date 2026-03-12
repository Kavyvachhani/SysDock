#!/usr/bin/env python3
"""
SysDock — Self-Test Suite
Run this on your Linux / EC2 instance to verify everything works before pushing to PyPI.

Usage:
    python3 test_sysdock.py
    python3 test_sysdock.py --quick     # skip slow tests (no 1s CPU wait)
    python3 test_sysdock.py --docker    # also run Docker tests
"""
from __future__ import annotations
import sys
import os
import json
import argparse
import traceback

# ── colour helpers ─────────────────────────────────────────────────────────
OK   = "\033[1;32m[PASS]\033[0m"
FAIL = "\033[1;31m[FAIL]\033[0m"
SKIP = "\033[1;33m[SKIP]\033[0m"
INFO = "\033[0;36m[INFO]\033[0m"

_results = []

def check(name, fn, skip=False):
    if skip:
        print("{} {}".format(SKIP, name))
        _results.append((name, "skip"))
        return None
    try:
        result = fn()
        print("{} {}".format(OK, name))
        _results.append((name, "pass"))
        return result
    except AssertionError as e:
        print("{} {}  →  {}".format(FAIL, name, e))
        _results.append((name, "fail"))
        return None
    except Exception as e:
        print("{} {}  →  {}".format(FAIL, name, e))
        _results.append((name, "fail"))
        return None


def section(title):
    print("\n\033[1;36m── {} {}\033[0m".format(title, "─" * (50 - len(title))))


def summary():
    total = len(_results)
    passed = sum(1 for _, s in _results if s == "pass")
    failed = sum(1 for _, s in _results if s == "fail")
    skipped = sum(1 for _, s in _results if s == "skip")
    print("\n" + "═" * 55)
    print("  SysDock Test Results: {} passed, {} failed, {} skipped / {} total".format(
          passed, failed, skipped, total))
    print("═" * 55)
    if failed:
        print("\n\033[1;31mFailed tests:\033[0m")
        for name, st in _results:
            if st == "fail":
                print("  ✗ {}".format(name))
    return failed == 0


# ══════════════════════════════════════════════════════════
# TESTS
# ══════════════════════════════════════════════════════════

def run_tests(quick=False, docker=False):

    # ── 1. Imports ────────────────────────────────────────
    section("1. Package imports")

    check("Import infravision_agent package",
          lambda: __import__("infravision_agent"))

    check("Import system collector",
          lambda: __import__("infravision_agent.collectors.system",
                             fromlist=["collect_all"]))

    check("Import memory collector (get_memory)",
          lambda: __import__("infravision_agent.collectors.system",
                             fromlist=["get_memory"]).get_memory)

    check("Import disk collector",
          lambda: __import__("infravision_agent.collectors.disk",
                             fromlist=["collect_all"]))

    check("Import process collector",
          lambda: __import__("infravision_agent.collectors.processes",
                             fromlist=["collect_all"]))

    check("Import network collector",
          lambda: __import__("infravision_agent.collectors.network",
                             fromlist=["collect_all"]))

    check("Import docker collector",
          lambda: __import__("infravision_agent.collectors.docker_collector",
                             fromlist=["collect_all"]))

    check("Import dashboard",
          lambda: __import__("infravision_agent.display.dashboard",
                             fromlist=["run_dashboard"]))

    check("Import CLI",
          lambda: __import__("infravision_agent.cli", fromlist=["main"]))

    # ── 2. System Collector ───────────────────────────────
    section("2. System collector (CPU, Memory, Load, Uptime)")

    from infravision_agent.collectors import system as _sys

    cpu_data = check("get_cpu() returns dict with expected keys",
        lambda: _assert_keys(_sys.get_cpu(interval=None if quick else 1.0),
                             ["usage_total", "logical_cores", "usage_per_core",
                              "user_pct", "system_pct", "idle_pct"]))

    check("CPU usage_total is 0–100",
          lambda: _assert_range(cpu_data["usage_total"], 0, 100),
          skip=(cpu_data is None))

    check("CPU idle_pct is 0–100",
          lambda: _assert_range(cpu_data["idle_pct"], 0, 100),
          skip=(cpu_data is None))

    check("CPU usage_total + idle_pct <= ~100 (reasonable sum)",
          lambda: _assert_true(
              float(cpu_data["usage_total"]) + float(cpu_data["idle_pct"]) <= 105,
              "cpu_total={} idle={}".format(cpu_data["usage_total"], cpu_data["idle_pct"])),
          skip=(cpu_data is None))

    mem = check("get_memory() returns dict with expected keys",
        lambda: _assert_keys(_sys.get_memory(),
                             ["total_mb", "used_mb", "available_mb",
                              "free_mb", "cached_mb", "buffers_mb", "percent"]))

    check("Memory: total_mb > 0",
          lambda: _assert_true(mem["total_mb"] > 0, "total={}".format(mem["total_mb"])),
          skip=(mem is None))

    check("Memory: used_mb <= total_mb",
          lambda: _assert_true(mem["used_mb"] <= mem["total_mb"],
                               "used={} total={}".format(mem["used_mb"], mem["total_mb"])),
          skip=(mem is None))

    check("Memory: percent matches used/total (within 2%)",
          lambda: _assert_approx(mem["percent"],
                                 100.0 * mem["used_mb"] / mem["total_mb"], tol=2.0),
          skip=(mem is None))

    check("Memory: available_mb reasonably > 0",
          lambda: _assert_true(mem["available_mb"] >= 0,
                               "available={}".format(mem["available_mb"])),
          skip=(mem is None))

    check("Memory: htop formula sanity (used ≤ total - free)",
          lambda: _assert_true(
              mem["used_mb"] <= mem["total_mb"] - mem["free_mb"] + 1,
              "used={} total={} free={}".format(mem["used_mb"], mem["total_mb"], mem["free_mb"])),
          skip=(mem is None))

    check("get_load() returns load1/load5/load15",
        lambda: _assert_keys(_sys.get_load(), ["load1", "load5", "load15"]))

    check("get_uptime() returns uptime_seconds > 0",
        lambda: _assert_true(_sys.get_uptime()["uptime_seconds"] > 0))

    check("get_hostname() returns hostname string",
        lambda: _assert_true(len(_sys.get_hostname()["hostname"]) > 0))

    # ── 3. Disk Collector ─────────────────────────────────
    section("3. Disk collector")
    from infravision_agent.collectors import disk as _disk

    disk_data = check("disk collect_all() returns partitions list",
        lambda: _assert_keys(_disk.collect_all(), ["partitions"]))

    check("At least one partition found",
          lambda: _assert_true(len(disk_data["partitions"]) > 0),
          skip=(disk_data is None))

    if disk_data:
        part = disk_data["partitions"][0]
        check("Root partition has total_gb > 0",
              lambda: _assert_true(part.get("total_gb", 0) > 0,
                                   "total_gb={}".format(part.get("total_gb"))))

    # ── 4. Process Collector ──────────────────────────────
    section("4. Process collector")
    from infravision_agent.collectors import processes as _proc

    proc_data = check("processes collect_all() has top_by_cpu",
        lambda: _assert_keys(_proc.collect_all(), ["top_by_cpu", "summary"]))

    check("At least 5 processes found",
          lambda: _assert_true(len(proc_data["top_by_cpu"]) >= 5),
          skip=(proc_data is None))

    if proc_data and proc_data.get("top_by_cpu"):
        p = proc_data["top_by_cpu"][0]
        check("Process has pid, cpu_pct, mem_pct, rss_mb",
              lambda: _assert_keys(p, ["pid", "cpu_pct", "mem_pct", "rss_mb"]))

    # ── 5. Network Collector ──────────────────────────────
    section("5. Network collector")
    from infravision_agent.collectors import network as _net

    net_data = check("network collect_all() has interfaces",
        lambda: _assert_keys(_net.collect_all(), ["interfaces", "connections"]))

    check("At least one network interface found",
          lambda: _assert_true(len(net_data["interfaces"]) > 0),
          skip=(net_data is None))

    # ── 6. Docker Collector ───────────────────────────────
    section("6. Docker collector")
    from infravision_agent.collectors import docker_collector as _dkr

    dkr_data = check("docker collect_all() returns dict with 'available'",
        lambda: _assert_keys(_dkr.collect_all(), ["available", "containers", "images"]))

    if dkr_data and dkr_data.get("available"):
        print("{} Docker is available — running container checks".format(INFO))

        check("Docker containers list is a list",
              lambda: _assert_true(isinstance(dkr_data["containers"], list)))

        check("Docker images list is a list",
              lambda: _assert_true(isinstance(dkr_data["images"], list)))

        check("Each running container has 'state' field",
              lambda: _assert_true(all("state" in c for c in dkr_data["containers"]),
                                   "Missing 'state' in: {}".format(
                                       [c.get("name") for c in dkr_data["containers"]
                                        if "state" not in c][:3])),
              skip=(len(dkr_data["containers"]) == 0))

        running = [c for c in dkr_data["containers"] if c.get("state") == "running"]
        if running and docker:
            c = running[0]
            check("Running container has stats dict",
                  lambda: _assert_true(isinstance(c.get("stats"), dict),
                                       "stats={}".format(c.get("stats"))))
            check("Running container stats has cpu_pct",
                  lambda: _assert_keys(c.get("stats") or {},
                                       ["cpu_pct", "mem_pct"]))
    else:
        print("{} Docker not available — skipping container checks".format(INFO))

    # ── 7. Full collect_all JSON ──────────────────────────
    section("7. Full JSON snapshot (collect_all on all modules)")

    def _full_snapshot():
        from infravision_agent.collectors import (
            system as s, disk as d, processes as p,
            network as n, docker_collector as dkr,
        )
        snap = {
            "system":    s.collect_all(),
            "disk":      d.collect_all(),
            "processes": p.collect_all(),
            "network":   n.collect_all(),
            "docker":    dkr.collect_all(),
        }
        # Must be JSON-serialisable
        return json.loads(json.dumps(snap, default=str))

    snap = check("Full snapshot is JSON-serialisable", _full_snapshot)

    check("Snapshot has all required sections",
          lambda: _assert_keys(snap, ["system", "disk", "processes", "network", "docker"]),
          skip=(snap is None))

    # ── 8. CLI smoke test ─────────────────────────────────
    section("8. CLI smoke test")
    import subprocess

    check("'sysdock --version' exits 0",
        lambda: _assert_true(
            subprocess.run(["sysdock", "--version"],
                           capture_output=True).returncode == 0,
            "Command not found or non-zero exit"))

    check("'sysdock check' exits 0",
        lambda: _assert_true(
            subprocess.run(["sysdock", "check"],
                           capture_output=True).returncode == 0))

    check("'sysdock status --section system --json' outputs valid JSON",
        lambda: _valid_json(
            subprocess.run(["sysdock", "status", "--section", "system", "--json"],
                           capture_output=True, text=True).stdout))

    check("'sysdock status --section docker --json' outputs valid JSON",
        lambda: _valid_json(
            subprocess.run(["sysdock", "status", "--section", "docker", "--json"],
                           capture_output=True, text=True).stdout))

    return summary()


# ── helpers ────────────────────────────────────────────────────────────────

def _assert_keys(d, keys):
    assert isinstance(d, dict), "Expected dict, got {}".format(type(d))
    missing = [k for k in keys if k not in d]
    assert not missing, "Missing keys: {}".format(missing)
    return d

def _assert_range(v, lo, hi):
    v = float(v)
    assert lo <= v <= hi, "Value {} not in [{}, {}]".format(v, lo, hi)
    return v

def _assert_approx(a, b, tol=2.0):
    assert abs(float(a) - float(b)) <= tol, "{} != {} (tol {})".format(a, b, tol)

def _assert_true(cond, msg=""):
    assert cond, msg or "Condition is False"

def _valid_json(text):
    try:
        data = json.loads(text)
        _assert_true(isinstance(data, (dict, list)))
        return data
    except Exception as e:
        raise AssertionError("Invalid JSON: {}  (got: {!r})".format(e, text[:200]))


if __name__ == "__main__":
    parser = argparse.ArgumentParser(description="SysDock self-test")
    parser.add_argument("--quick",  action="store_true", help="Skip 1s CPU sampling wait")
    parser.add_argument("--docker", action="store_true", help="Run extra Docker stats tests")
    args = parser.parse_args()

    ok = run_tests(quick=args.quick, docker=args.docker)
    sys.exit(0 if ok else 1)
