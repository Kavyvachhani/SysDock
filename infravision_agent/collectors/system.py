"""
System collector: CPU, RAM, swap, load, uptime, hostname.
Primary: psutil. Fallback: direct /proc parsing.
Python 3.6+. All Linux distributions.

CPU accuracy note:
- psutil.cpu_percent() requires two measurements separated by an interval
  to compute a meaningful percentage. We use interval=1.0 which matches htop.
- Memory: we parse /proc/meminfo directly using htop's formula:
    used = total - free - buffers - cached(+SReclaimable)
  This matches the "used" column in htop exactly.
"""
from __future__ import annotations

import os
import time
import platform
import socket
from datetime import datetime, timedelta

try:
    import psutil as _psutil
    _HAS_PSUTIL = True
except ImportError:
    _psutil = None
    _HAS_PSUTIL = False


def _safe(fn, default=None):
    try:
        return fn()
    except Exception:
        return default


# ── CPU ──────────────────────────────────────────────────────────────────────

def get_cpu(interval=1.0):
    """
    Collect CPU metrics.
    interval: sampling window in seconds.  1.0 matches htop's default.
    Set interval=None to return instantly (uses cached value from last call).
    """
    result = {
        "model": "Unknown",
        "physical_cores": 1,
        "logical_cores": 1,
        "usage_total": 0.0,
        "usage_per_core": [],
        "freq_mhz": None,
        "freq_max_mhz": None,
        "user_pct": 0.0,
        "system_pct": 0.0,
        "idle_pct": 100.0,
        "iowait_pct": 0.0,
    }

    # CPU model from /proc/cpuinfo (available everywhere)
    try:
        with open("/proc/cpuinfo") as f:
            for line in f:
                if "model name" in line:
                    result["model"] = line.split(":", 1)[1].strip()
                    break
    except Exception:
        result["model"] = platform.processor() or "Unknown"

    if _HAS_PSUTIL:
        result["physical_cores"] = _safe(lambda: _psutil.cpu_count(logical=False)) or 1
        result["logical_cores"]  = _safe(lambda: _psutil.cpu_count(logical=True))  or 1

        # Use a real interval so the reading matches htop
        # interval=1.0 → blocks for 1 second but gives accurate figures
        # interval=None → instant, uses cached measurement from prior call
        try:
            result["usage_total"]    = _psutil.cpu_percent(interval=interval)
            result["usage_per_core"] = _psutil.cpu_percent(interval=None, percpu=True)
        except Exception:
            result["usage_total"]    = 0.0
            result["usage_per_core"] = []

        freq = _safe(_psutil.cpu_freq)
        if freq:
            result["freq_mhz"]     = round(freq.current, 1)
            result["freq_max_mhz"] = round(freq.max, 1) if freq.max else None

        times = _safe(lambda: _psutil.cpu_times_percent(interval=None))
        if times:
            result["user_pct"]   = getattr(times, "user",   0.0)
            result["system_pct"] = getattr(times, "system", 0.0)
            result["idle_pct"]   = getattr(times, "idle",   0.0)
            result["iowait_pct"] = getattr(times, "iowait", 0.0)
    else:
        # /proc/stat fallback — take two readings 1 second apart
        def _read_stat():
            with open("/proc/stat") as f:
                line = f.readline()
            vals = list(map(float, line.split()[1:]))
            idle  = vals[3] + (vals[4] if len(vals) > 4 else 0)
            total = sum(vals)
            return total, idle, vals

        try:
            t1, idle1, vals1 = _read_stat()
            time.sleep(interval or 0.5)
            t2, idle2, _     = _read_stat()
            dt    = t2 - t1
            didle = idle2 - idle1
            result["idle_pct"]    = round(100.0 * didle / dt, 1) if dt else 100.0
            result["usage_total"] = round(100.0 - result["idle_pct"], 1)
            if len(vals1) > 4 and dt:
                result["iowait_pct"] = round(100.0 * (vals1[4]) / dt, 1)
        except Exception:
            pass

        # core count from /proc/cpuinfo
        try:
            count = 0
            with open("/proc/cpuinfo") as f:
                for line in f:
                    if line.startswith("processor"):
                        count += 1
            result["logical_cores"] = max(1, count)
        except Exception:
            pass

    return result


# ── Memory ───────────────────────────────────────────────────────────────────

def get_memory():
    """
    Parse /proc/meminfo — exact htop v3 formula:
        cache  = Cached + SReclaimable - Shmem
        used   = MemTotal - MemFree - Buffers - cache

    The Shmem subtraction is the key fix: Shmem (shared/tmpfs memory) lives
    inside the Cached counter but is actively used, NOT reclaimable.  Without
    this correction 'used' reads LOWER than htop reports.
    """
    result = {
        "total_mb": 0, "available_mb": 0, "used_mb":  0,   "free_mb":     0,
        "cached_mb": 0, "buffers_mb":  0, "shmem_mb": 0,   "percent":     0.0,
        "swap_total_mb": 0, "swap_used_mb": 0, "swap_free_mb": 0, "swap_percent": 0.0,
    }
    try:
        info = {}
        with open("/proc/meminfo") as f:
            for line in f:
                parts = line.split()
                if len(parts) >= 2:
                    info[parts[0].rstrip(":")] = int(parts[1])

        total        = info.get("MemTotal",     0)
        free         = info.get("MemFree",      0)
        buffers      = info.get("Buffers",      0)
        page_cache   = info.get("Cached",       0)  # page cache only
        sreclaimable = info.get("SReclaimable", 0)  # reclaimable slab
        shmem        = info.get("Shmem",        0)  # shared/tmpfs — subtract!

        # htop v3 exact: buff/cache = page_cache + SReclaimable - Shmem
        cache_eff = page_cache + sreclaimable - shmem
        used      = max(0, total - free - buffers - cache_eff)
        avail     = info.get("MemAvailable", free + cache_eff + buffers)

        to_mb = lambda kb: round(kb / 1024, 1)
        result["total_mb"]     = to_mb(total)
        result["free_mb"]      = to_mb(free)
        result["buffers_mb"]   = to_mb(buffers)
        result["cached_mb"]    = to_mb(cache_eff)   # what htop calls buff/cache
        result["shmem_mb"]     = to_mb(shmem)
        result["available_mb"] = to_mb(avail)
        result["used_mb"]      = to_mb(used)
        result["percent"]      = round(100.0 * used / total, 1) if total else 0.0

        swap_total = info.get("SwapTotal", 0)
        swap_free  = info.get("SwapFree",  0)
        swap_used  = swap_total - swap_free
        result["swap_total_mb"] = to_mb(swap_total)
        result["swap_used_mb"]  = to_mb(swap_used)
        result["swap_free_mb"]  = to_mb(swap_free)
        result["swap_percent"]  = round(100.0 * swap_used / swap_total, 1) if swap_total else 0.0
    except Exception:
        pass
    return result


# ── Load ─────────────────────────────────────────────────────────────────────

def get_load():
    try:
        with open("/proc/loadavg") as f:
            parts = f.read().split()
        l1, l5, l15 = float(parts[0]), float(parts[1]), float(parts[2])
        cores = 1
        if _HAS_PSUTIL:
            cores = _safe(lambda: _psutil.cpu_count(logical=True)) or 1
        else:
            try:
                with open("/proc/cpuinfo") as f:
                    cores = max(1, sum(1 for l in f if l.startswith("processor")))
            except Exception:
                pass
        return {
            "load1": round(l1, 2), "load5": round(l5, 2), "load15": round(l15, 2),
            "load1_normalized": round(l1 / cores, 2),
        }
    except Exception:
        return {"load1": 0.0, "load5": 0.0, "load15": 0.0, "load1_normalized": 0.0}


# ── Uptime ───────────────────────────────────────────────────────────────────

def get_uptime():
    try:
        with open("/proc/uptime") as f:
            uptime_sec = float(f.read().split()[0])
        td   = timedelta(seconds=int(uptime_sec))
        d    = td.days
        h, r = divmod(td.seconds, 3600)
        m, s = divmod(r, 60)
        boot_ts = time.time() - uptime_sec
        return {
            "boot_time":      datetime.fromtimestamp(boot_ts).isoformat(),
            "uptime_seconds": int(uptime_sec),
            "uptime_human":   "{}d {}h {}m {}s".format(d, h, m, s),
        }
    except Exception:
        return {"boot_time": None, "uptime_seconds": 0, "uptime_human": "unknown"}


# ── Hostname / OS ─────────────────────────────────────────────────────────────

def get_hostname():
    os_name = "Unknown Linux"
    for path in ("/etc/os-release", "/usr/lib/os-release"):
        try:
            with open(path) as f:
                for line in f:
                    if line.startswith("PRETTY_NAME="):
                        os_name = line.split("=", 1)[1].strip().strip('"')
                        break
            break
        except Exception:
            continue

    if os_name == "Unknown Linux":
        try:
            os_name = platform.platform()
        except Exception:
            pass

    try:
        hostname = socket.gethostname()
    except Exception:
        hostname = os.environ.get("HOSTNAME", "unknown")

    return {
        "hostname":       hostname,
        "os":             os_name,
        "kernel":         platform.release(),
        "arch":           platform.machine(),
        "python_version": platform.python_version(),
    }


# ── Temperatures ──────────────────────────────────────────────────────────────

def get_temperatures():
    if not _HAS_PSUTIL:
        return []
    try:
        temps = _psutil.sensors_temperatures()
        if not temps:
            return []
        result = []
        for name, entries in temps.items():
            for e in entries:
                result.append({
                    "sensor":   name,
                    "label":    e.label or name,
                    "current":  e.current,
                    "high":     e.high,
                    "critical": e.critical,
                })
        return result
    except Exception:
        return []


# ── Collect ───────────────────────────────────────────────────────────────────

def collect_all():
    return {
        "hostname":     get_hostname(),
        "cpu":          get_cpu(interval=1.0),
        "memory":       get_memory(),
        "load":         get_load(),
        "uptime":       get_uptime(),
        "temperatures": get_temperatures(),
        "collected_at": datetime.utcnow().isoformat() + "Z",
    }
