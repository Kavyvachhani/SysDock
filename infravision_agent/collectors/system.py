"""
System collector — CPU, RAM, swap, load, uptime, hostname, GPU.
Supports: Linux, macOS (Apple Silicon arm64 + x86_64), Windows 11.

Priority chain:
  1. psutil (most accurate, available on all 3 platforms)
  2. /proc filesystem (Linux only)
  3. sysctl (macOS native)
  4. Windows registry / WMI fallback (Windows only)

Python 3.8+. Zero shell=True subprocess calls.
"""
from __future__ import annotations

import os
import sys
import time
import platform
import socket
import subprocess
from datetime import datetime, timedelta

try:
    import psutil as _psutil
    _HAS_PSUTIL = True
except ImportError:
    _psutil = None
    _HAS_PSUTIL = False

# Platform helpers
_IS_LINUX   = sys.platform.startswith("linux")
_IS_MACOS   = sys.platform == "darwin"
_IS_WINDOWS = os.name == "nt"


def _safe(fn, default=None):
    try:
        return fn()
    except Exception:
        return default


def _sysctl(key):
    """Read a macOS sysctl value. Returns stripped string or None."""
    try:
        out = subprocess.check_output(
            ["sysctl", "-n", key], timeout=2, stderr=subprocess.DEVNULL
        )
        return out.decode("utf-8", errors="ignore").strip()
    except Exception:
        return None


def _run(cmd, timeout=5):
    """Run a command list; return (stdout, returncode). Never raises."""
    try:
        r = subprocess.run(
            cmd, capture_output=True, text=True, timeout=timeout
        )
        return r.stdout, r.returncode
    except Exception:
        return "", -1


# ── CPU ──────────────────────────────────────────────────────────────────────

def get_cpu(interval=1.0):
    """
    Return CPU metrics.
    interval: sampling window in seconds (1.0 matches htop).
    interval=None → instant, uses psutil's cached last value.
    """
    result = {
        "model":         "Unknown",
        "physical_cores": 1,
        "logical_cores":  1,
        "usage_total":    0.0,
        "usage_per_core": [],
        "freq_mhz":       None,
        "freq_max_mhz":   None,
        "user_pct":       0.0,
        "system_pct":     0.0,
        "idle_pct":       100.0,
        "iowait_pct":     0.0,
    }

    # ── CPU model string ──────────────────────────────────────────────────
    if _IS_MACOS:
        model = _sysctl("machdep.cpu.brand_string")
        if not model:
            model = _sysctl("hw.model") or platform.processor() or "Apple Silicon"
        result["model"] = model
    elif _IS_LINUX:
        try:
            with open("/proc/cpuinfo") as f:
                for line in f:
                    if "model name" in line:
                        result["model"] = line.split(":", 1)[1].strip()
                        break
        except Exception:
            result["model"] = platform.processor() or "Unknown"
    else:  # Windows
        result["model"] = platform.processor() or "Unknown"

    # ── Core counts ───────────────────────────────────────────────────────
    if _HAS_PSUTIL:
        result["physical_cores"] = _safe(lambda: _psutil.cpu_count(logical=False)) or 1
        result["logical_cores"]  = _safe(lambda: _psutil.cpu_count(logical=True))  or 1
        try:
            result["usage_total"]    = _psutil.cpu_percent(interval=interval)
            result["usage_per_core"] = _psutil.cpu_percent(interval=None, percpu=True)
        except Exception:
            pass
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
    elif _IS_LINUX:
        # /proc/stat fallback (Linux only)
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
        try:
            count = 0
            with open("/proc/cpuinfo") as f:
                for line in f:
                    if line.startswith("processor"):
                        count += 1
            result["logical_cores"] = max(1, count)
        except Exception:
            pass
    elif _IS_MACOS:
        # sysctl fallback on macOS
        lc = _sysctl("hw.logicalcpu")
        pc = _sysctl("hw.physicalcpu")
        if lc:
            result["logical_cores"]  = int(lc)
        if pc:
            result["physical_cores"] = int(pc)

    return result


# ── Memory ───────────────────────────────────────────────────────────────────

def get_memory():
    """
    Cross-platform memory stats.
    Linux: parses /proc/meminfo with htop v3 formula.
    macOS/Windows: uses psutil.
    """
    result = {
        "total_mb": 0, "available_mb": 0, "used_mb": 0, "free_mb": 0,
        "cached_mb": 0, "buffers_mb": 0, "shmem_mb": 0, "percent": 0.0,
        "swap_total_mb": 0, "swap_used_mb": 0, "swap_free_mb": 0, "swap_percent": 0.0,
    }

    # psutil path (works on all platforms natively)
    if _HAS_PSUTIL and not _IS_LINUX:
        try:
            mem  = _psutil.virtual_memory()
            swap = _psutil.swap_memory()
            to_mb = lambda x: round(x / 1024 / 1024, 1)
            return {
                "total_mb":     to_mb(mem.total),
                "available_mb": to_mb(mem.available),
                "used_mb":      to_mb(mem.used),
                "free_mb":      to_mb(mem.free),
                "cached_mb":    to_mb(getattr(mem, "cached", 0) or 0),
                "buffers_mb":   to_mb(getattr(mem, "buffers", 0) or 0),
                "shmem_mb":     0,
                "percent":      mem.percent,
                "swap_total_mb": to_mb(swap.total),
                "swap_used_mb":  to_mb(swap.used),
                "swap_free_mb":  to_mb(swap.free),
                "swap_percent":  swap.percent,
            }
        except Exception:
            pass

    # Linux — exact htop v3 formula
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
        page_cache   = info.get("Cached",       0)
        sreclaimable = info.get("SReclaimable", 0)
        shmem        = info.get("Shmem",        0)

        cache_eff = page_cache + sreclaimable - shmem
        used      = max(0, total - free - buffers - cache_eff)
        avail     = info.get("MemAvailable", free + cache_eff + buffers)

        to_mb = lambda kb: round(kb / 1024, 1)
        result["total_mb"]     = to_mb(total)
        result["free_mb"]      = to_mb(free)
        result["buffers_mb"]   = to_mb(buffers)
        result["cached_mb"]    = to_mb(cache_eff)
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
        # Last-resort psutil on Linux
        if _HAS_PSUTIL:
            try:
                mem  = _psutil.virtual_memory()
                swap = _psutil.swap_memory()
                to_mb = lambda x: round(x / 1024 / 1024, 1)
                result.update({
                    "total_mb": to_mb(mem.total), "available_mb": to_mb(mem.available),
                    "used_mb": to_mb(mem.used), "free_mb": to_mb(mem.free),
                    "percent": mem.percent,
                    "swap_total_mb": to_mb(swap.total), "swap_used_mb": to_mb(swap.used),
                    "swap_free_mb": to_mb(swap.free), "swap_percent": swap.percent,
                })
            except Exception:
                pass
    return result


# ── Load ─────────────────────────────────────────────────────────────────────

def get_load():
    """Load average — available on Linux and macOS, zero on Windows."""
    cores = 1
    if _HAS_PSUTIL:
        cores = _safe(lambda: _psutil.cpu_count(logical=True)) or 1

    if _IS_WINDOWS:
        # Windows has no load average; approximate via CPU percent
        if _HAS_PSUTIL:
            try:
                u = _psutil.cpu_percent(interval=None) / 100.0 * cores
                return {"load1": round(u, 2), "load5": round(u, 2), "load15": round(u, 2),
                        "load1_normalized": round(u / cores, 2)}
            except Exception:
                pass
        return {"load1": 0.0, "load5": 0.0, "load15": 0.0, "load1_normalized": 0.0}

    try:
        if hasattr(os, "getloadavg"):
            l1, l5, l15 = os.getloadavg()
            return {
                "load1": round(l1, 2), "load5": round(l5, 2), "load15": round(l15, 2),
                "load1_normalized": round(l1 / cores, 2),
            }
    except Exception:
        pass

    try:
        with open("/proc/loadavg") as f:
            parts = f.read().split()
        l1, l5, l15 = float(parts[0]), float(parts[1]), float(parts[2])
        return {
            "load1": round(l1, 2), "load5": round(l5, 2), "load15": round(l15, 2),
            "load1_normalized": round(l1 / cores, 2),
        }
    except Exception:
        return {"load1": 0.0, "load5": 0.0, "load15": 0.0, "load1_normalized": 0.0}


# ── Uptime ───────────────────────────────────────────────────────────────────

def get_uptime():
    if _HAS_PSUTIL:
        try:
            boot_ts    = _psutil.boot_time()
            uptime_sec = time.time() - boot_ts
            td         = timedelta(seconds=int(uptime_sec))
            d          = td.days
            h, r       = divmod(td.seconds, 3600)
            m, s       = divmod(r, 60)
            return {
                "boot_time":      datetime.fromtimestamp(boot_ts).isoformat(),
                "uptime_seconds": int(uptime_sec),
                "uptime_human":   "{}d {}h {}m".format(d, h, m),
            }
        except Exception:
            pass

    if _IS_LINUX:
        try:
            with open("/proc/uptime") as f:
                uptime_sec = float(f.read().split()[0])
            td   = timedelta(seconds=int(uptime_sec))
            d    = td.days
            h, r = divmod(td.seconds, 3600)
            m, _ = divmod(r, 60)
            return {
                "boot_time":      datetime.fromtimestamp(time.time() - uptime_sec).isoformat(),
                "uptime_seconds": int(uptime_sec),
                "uptime_human":   "{}d {}h {}m".format(d, h, m),
            }
        except Exception:
            pass

    if _IS_MACOS:
        try:
            bt = _sysctl("kern.boottime")
            # format: { sec = 1700000000, usec = 0 }
            import re
            m = re.search(r"sec\s*=\s*(\d+)", bt or "")
            if m:
                boot_ts    = float(m.group(1))
                uptime_sec = time.time() - boot_ts
                td         = timedelta(seconds=int(uptime_sec))
                d          = td.days
                h, r       = divmod(td.seconds, 3600)
                mn, _      = divmod(r, 60)
                return {
                    "boot_time":      datetime.fromtimestamp(boot_ts).isoformat(),
                    "uptime_seconds": int(uptime_sec),
                    "uptime_human":   "{}d {}h {}m".format(d, h, mn),
                }
        except Exception:
            pass

    return {"boot_time": None, "uptime_seconds": 0, "uptime_human": "unknown"}


# ── Hostname / OS ─────────────────────────────────────────────────────────────

def get_hostname():
    os_name = "Unknown OS"

    if _IS_WINDOWS:
        os_name = "Windows {}".format(platform.release())
    elif _IS_MACOS:
        ver = platform.mac_ver()
        os_name = "macOS {}".format(ver[0]) if ver[0] else "macOS"
        arch = platform.machine()
        os_name += " ({})".format(arch)
    else:
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

    if os_name == "Unknown OS":
        os_name = _safe(platform.platform) or "Unknown OS"

    try:
        hostname = socket.gethostname()
    except Exception:
        hostname = os.environ.get("HOSTNAME", os.environ.get("COMPUTERNAME", "unknown"))

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
    if _IS_WINDOWS:
        return []  # psutil sensors_temperatures() not reliably available on Windows
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
                    "high":     getattr(e, "high", None),
                    "critical": getattr(e, "critical", None),
                })
        return result
    except Exception:
        return []


# ── GPUs ──────────────────────────────────────────────────────────────────────

def _detect_nvidia():
    """Try nvidia-smi. Works on Windows, Linux, and macOS (rare)."""
    candidates = ["nvidia-smi"]

    if _IS_WINDOWS:
        # Common NVSMI paths on Windows when not in PATH
        nvsmi_dirs = [
            r"C:\Program Files\NVIDIA Corporation\NVSMI",
            r"C:\Windows\System32",
        ]
        for d in nvsmi_dirs:
            p = os.path.join(d, "nvidia-smi.exe")
            if os.path.exists(p):
                candidates.insert(0, p)
                break

    for cmd in candidates:
        try:
            out_raw = subprocess.check_output(
                [cmd,
                 "--query-gpu=index,name,utilization.gpu,memory.used,memory.total,temperature.gpu",
                 "--format=csv,noheader,nounits"],
                timeout=3,
                stderr=subprocess.DEVNULL,
            )
            out = out_raw.decode("utf-8", errors="ignore").strip()
            if not out:
                continue
            gpus = []
            for line in out.splitlines():
                parts = [p.strip() for p in line.split(",")]
                if len(parts) >= 6:
                    mem_used  = float(parts[3]) if parts[3].replace(".", "").isdigit() else 0.0
                    mem_total = float(parts[4]) if parts[4].replace(".", "").isdigit() else 0.0
                    gpus.append({
                        "id":           parts[0],
                        "name":         parts[1].replace("NVIDIA ", "").replace("GeForce ", "").strip(),
                        "vendor":       "NVIDIA",
                        "gpu_util_pct": float(parts[2]) if parts[2].replace(".", "").isdigit() else 0.0,
                        "mem_used_mb":  mem_used,
                        "mem_total_mb": mem_total,
                        "mem_pct":      round((mem_used / mem_total) * 100, 1) if mem_total else 0.0,
                        "temp_c":       float(parts[5]) if parts[5].replace(".", "").isdigit() else 0.0,
                    })
            if gpus:
                return gpus
        except Exception:
            continue
    return []


def _detect_amd():
    """Try rocm-smi (AMD ROCm, Linux only)."""
    if not _IS_LINUX:
        return []
    try:
        out_raw = subprocess.check_output(
            ["rocm-smi", "--showuse", "--showmemuse", "--showtemp", "--csv"],
            timeout=3, stderr=subprocess.DEVNULL
        )
        out = out_raw.decode("utf-8", errors="ignore").strip()
        if not out:
            return []
        # Very basic parser — first data row after header
        lines = [l for l in out.splitlines() if l and not l.startswith("#")]
        gpus = []
        for i, line in enumerate(lines[1:], 0):
            parts = line.split(",")
            if len(parts) < 3:
                continue
            gpus.append({
                "id":           str(i),
                "name":         "AMD GPU {}".format(i),
                "vendor":       "AMD",
                "gpu_util_pct": _safe(lambda: float(parts[1].strip().rstrip("%"))) or 0.0,
                "mem_used_mb":  0.0,
                "mem_total_mb": 0.0,
                "mem_pct":      0.0,
                "temp_c":       _safe(lambda: float(parts[2].strip().rstrip("c"))) or 0.0,
            })
        return gpus
    except Exception:
        return []


def _detect_apple_metal():
    """Detect Apple GPU on macOS via system_profiler. Returns a single GPU entry."""
    if not _IS_MACOS:
        return []
    try:
        out, rc = _run(["system_profiler", "SPDisplaysDataType"], timeout=5)
        if rc != 0 or not out:
            return []
        # Find GPU model name
        name = "Apple GPU"
        for line in out.splitlines():
            line = line.strip()
            if "Chipset Model:" in line:
                name = line.split(":", 1)[1].strip()
                break
        # Find VRAM
        vram_mb = 0.0
        for line in out.splitlines():
            line = line.strip()
            if "VRAM" in line and ":" in line:
                raw = line.split(":", 1)[1].strip()
                try:
                    num = float("".join(c for c in raw if c.isdigit() or c == "."))
                    if "GB" in raw.upper():
                        vram_mb = num * 1024
                    else:
                        vram_mb = num
                except Exception:
                    pass
                break

        return [{
            "id":           "0",
            "name":         name,
            "vendor":       "Apple",
            "gpu_util_pct": 0.0,   # Metal doesn't expose utilisation without private API
            "mem_used_mb":  0.0,
            "mem_total_mb": vram_mb,
            "mem_pct":      0.0,
            "temp_c":       0.0,
        }]
    except Exception:
        return []


def get_gpu():
    """
    Detect GPUs on any platform.
    Priority: NVIDIA → AMD (Linux) → Apple Metal (macOS).
    Returns list of GPU dicts, or [] if none found.
    """
    gpus = _detect_nvidia()
    if gpus:
        return gpus

    if _IS_LINUX:
        gpus = _detect_amd()
        if gpus:
            return gpus

    if _IS_MACOS:
        gpus = _detect_apple_metal()
        if gpus:
            return gpus

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
        "gpu":          get_gpu(),
        "collected_at": datetime.utcnow().isoformat() + "Z",
    }
