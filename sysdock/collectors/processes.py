"""
Process collector: process list, summary, listening ports.
Primary: psutil. Fallback: /proc filesystem.
Python 3.6+. All Linux distributions.
"""
from __future__ import annotations

import os
import subprocess
from datetime import datetime

try:
    import psutil as _psutil
    _HAS_PSUTIL = True
except ImportError:
    _psutil = None
    _HAS_PSUTIL = False


def _run(cmd, timeout=8):
    try:
        r = subprocess.run(cmd, capture_output=True, text=True, timeout=timeout)
        return r.stdout, r.returncode
    except Exception:
        return "", -1


# ── Process list ─────────────────────────────────────────────────────────────

def _processes_psutil(limit=20, sort_by="cpu"):
    procs = []
    attrs = ["pid", "name", "username", "status",
             "cpu_percent", "memory_percent", "memory_info",
             "num_threads", "cmdline", "ppid"]
    for proc in _psutil.process_iter(attrs):
        try:
            info = proc.info
            name = info.get("name") or "?"
            if os.name == 'nt' and name == "System Idle Process":
                continue
            if info.get("memory_info") is None:
                continue
            rss_mb = round(info["memory_info"].rss / 1024 ** 2, 1)
            try:
                cmd = " ".join((info.get("cmdline") or [])[:5]) or info.get("name", "?")
            except Exception:
                cmd = info.get("name", "?")
            procs.append({
                "pid":     info["pid"],
                "ppid":    info.get("ppid"),
                "name":    (info.get("name") or "?")[:50],
                "user":    (info.get("username") or "?")[:20],
                "status":  info.get("status", "?"),
                "cpu_pct": round(info.get("cpu_percent") or 0.0, 1),
                "mem_pct": round(info.get("memory_percent") or 0.0, 1),
                "rss_mb":  rss_mb,
                "threads": info.get("num_threads", 0),
                "cmd":     cmd[:80],
            })
        except (_psutil.NoSuchProcess, _psutil.AccessDenied, _psutil.ZombieProcess):
            continue

    key = "cpu_pct" if sort_by == "cpu" else "mem_pct"
    procs.sort(key=lambda x: x[key], reverse=True)
    return procs[:limit] if limit else procs


def _processes_proc(limit=None):
    """Read /proc/<pid>/stat + /proc/<pid>/status directly."""
    procs = []
    try:
        pids = [p for p in os.listdir("/proc") if p.isdigit()]
    except Exception:
        return []

    try:
        with open("/proc/meminfo") as f:
            for line in f:
                if line.startswith("MemTotal:"):
                    mem_total_kb = int(line.split()[1])
                    break
            else:
                mem_total_kb = 1024 * 1024
    except Exception:
        mem_total_kb = 1024 * 1024

    for pid in pids:
        try:
            stat_path = "/proc/{}/stat".format(pid)
            with open(stat_path) as f:
                raw = f.read()

            # Name is between first ( and last )
            i1 = raw.index("(") + 1
            i2 = raw.rindex(")")
            name   = raw[i1:i2]
            fields = raw[i2 + 2:].split()
            state   = fields[0] if fields else "?"
            utime   = int(fields[11]) if len(fields) > 11 else 0
            stime   = int(fields[12]) if len(fields) > 12 else 0
            threads = int(fields[17]) if len(fields) > 17 else 0

            rss_kb, user = 0, "?"
            try:
                with open("/proc/{}/status".format(pid)) as f:
                    for line in f:
                        if line.startswith("VmRSS:"):
                            rss_kb = int(line.split()[1])
                        elif line.startswith("Uid:"):
                            uid = line.split()[1]
                            try:
                                import pwd
                                user = pwd.getpwuid(int(uid)).pw_name
                            except Exception:
                                user = uid
            except Exception:
                pass

            try:
                with open("/proc/{}/cmdline".format(pid), "rb") as f:
                    cmd = f.read().replace(b"\x00", b" ").decode("utf-8", errors="replace").strip()[:80]
            except Exception:
                cmd = name

            mem_pct = round(100.0 * rss_kb / mem_total_kb, 1) if mem_total_kb else 0.0
            procs.append({
                "pid": int(pid), "ppid": None, "name": name[:50], "user": user,
                "status": state, "cpu_pct": float(utime + stime),
                "mem_pct": mem_pct, "rss_mb": round(rss_kb / 1024, 1),
                "threads": threads, "cmd": cmd or name,
            })
        except Exception:
            continue

    procs.sort(key=lambda x: x["cpu_pct"], reverse=True)
    # After sorting by ticks, reset to a relative indicator
    for p in procs:
        p["cpu_pct"] = 0.0  # ticks aren't percentage; psutil needed for that
    return procs[:limit] if limit else procs


def get_processes(limit=None, sort_by="cpu"):
    if _HAS_PSUTIL:
        return _processes_psutil(limit=limit, sort_by=sort_by)
    return _processes_proc(limit=limit)


# ── Summary ──────────────────────────────────────────────────────────────────

def get_process_summary():
    counts = {"total": 0, "running": 0, "sleeping": 0, "zombie": 0, "stopped": 0}

    if _HAS_PSUTIL:
        try:
            for proc in _psutil.process_iter(["status"]):
                try:
                    counts["total"] += 1
                    s = proc.info["status"]
                    if s == _psutil.STATUS_RUNNING:   counts["running"]  += 1
                    elif s == _psutil.STATUS_ZOMBIE:  counts["zombie"]   += 1
                    elif s == _psutil.STATUS_STOPPED: counts["stopped"]  += 1
                    else:                              counts["sleeping"] += 1
                except Exception:
                    counts["total"] += 1
        except Exception:
            pass
        return counts

    # Fallback: /proc/<pid>/stat
    try:
        for pid in os.listdir("/proc"):
            if not pid.isdigit():
                continue
            try:
                with open("/proc/{}/stat".format(pid)) as f:
                    raw = f.read()
                state = raw[raw.rindex(")") + 2:].split()[0]
                counts["total"] += 1
                if state == "R":   counts["running"]  += 1
                elif state == "Z": counts["zombie"]   += 1
                elif state == "T": counts["stopped"]  += 1
                else:              counts["sleeping"] += 1
            except Exception:
                counts["total"] += 1
    except Exception:
        pass
    return counts


# ── Listening ports ──────────────────────────────────────────────────────────

def get_listening_ports():
    if _HAS_PSUTIL:
        try:
            ports = []
            for c in _psutil.net_connections(kind="inet"):
                if c.status == "LISTEN":
                    ip, port = c.laddr
                    ports.append({
                        "local_address": "{}:{}".format(ip, port),
                        "process": str(c.pid) if getattr(c, 'pid', None) else ""
                    })
            if ports:
                return ports
        except (_psutil.AccessDenied, _psutil.Error, Exception):
            pass

    # Method 1: ss (modern systems)
    out, rc = _run(["ss", "-tlnp"])
    if rc == 0 and out:
        ports = []
        for line in out.strip().split("\n")[1:]:
            cols = line.split()
            if len(cols) >= 4 and cols[0] == "LISTEN":
                ports.append({
                    "local_address": cols[3],
                    "process":       cols[6] if len(cols) > 6 else "",
                })
        if ports:
            return ports

    # Method 2: netstat
    out, rc = _run(["netstat", "-tlnp"])
    if rc == 0 and out:
        ports = []
        for line in out.strip().split("\n")[2:]:
            cols = line.split()
            if len(cols) >= 4 and cols[0] in ("tcp", "tcp6") and "LISTEN" in line:
                ports.append({
                    "local_address": cols[3],
                    "process":       cols[6] if len(cols) > 6 else "",
                })
        if ports:
            return ports

    # Method 3: /proc/net/tcp + /proc/net/tcp6
    ports = []
    for path in ("/proc/net/tcp", "/proc/net/tcp6"):
        try:
            with open(path) as f:
                for line in f.readlines()[1:]:
                    cols = line.split()
                    if len(cols) < 4:
                        continue
                    if int(cols[3], 16) != 10:  # 0x0A = LISTEN
                        continue
                    ip_hex, port_hex = cols[1].rsplit(":", 1)
                    port = int(port_hex, 16)
                    try:
                        n = int(ip_hex, 16)
                        ip = "{}.{}.{}.{}".format(n & 0xFF, (n >> 8) & 0xFF,
                                                   (n >> 16) & 0xFF, (n >> 24) & 0xFF)
                    except Exception:
                        ip = ip_hex
                    ports.append({"local_address": "{}:{}".format(ip, port), "process": ""})
        except Exception:
            pass
    return ports


# ── Collect ───────────────────────────────────────────────────────────────────

def collect_all():
    all_procs = get_processes(limit=None, sort_by="cpu")
    ai_names = ["ollama", "llama-server", "vllm"]
    ai_procs = []
    
    for p in all_procs:
        p_name = p.get("name", "").lower()
        p_cmd = p.get("cmd", "").lower()
        if any(n in p_name or n in p_cmd for n in ai_names):
            ai_procs.append(p)
    
    top_cpu = all_procs[:20]
    top_mem = sorted(all_procs, key=lambda x: x.get("mem_pct", 0), reverse=True)[:10]

    return {
        "summary":         get_process_summary(),
        "top_by_cpu":      top_cpu,
        "top_by_mem":      top_mem,
        "ai_processes":    ai_procs,
        "listening_ports": get_listening_ports(),
        "collected_at":    datetime.utcnow().isoformat() + "Z",
    }
