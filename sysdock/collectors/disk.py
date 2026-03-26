"""
Disk collector: partitions, usage, I/O stats, df output.
Primary: psutil + /proc/diskstats. Fallback: df CLI.
Python 3.6+. All Linux distributions.
"""
from __future__ import annotations

import os
import subprocess
import time
from datetime import datetime

try:
    import psutil as _psutil
    _HAS_PSUTIL = True
except ImportError:
    _psutil = None
    _HAS_PSUTIL = False


def _run(cmd, timeout=10):
    try:
        r = subprocess.run(cmd, capture_output=True, text=True, timeout=timeout)
        return r.stdout, r.returncode
    except Exception:
        return "", -1


# ── df output ────────────────────────────────────────────────────────────────

def get_df_output():
    out, rc = _run(["df", "-h"])
    if rc == 0 and out:
        return out.strip()
    out, rc = _run(["df", "-h", "/"])
    return out.strip() if rc == 0 else "df not available"


# ── Partitions ───────────────────────────────────────────────────────────────

def get_disk_partitions():
    partitions = []

    if _HAS_PSUTIL:
        try:
            for part in _psutil.disk_partitions(all=False):
                if not part.mountpoint:
                    continue
                try:
                    usage = _psutil.disk_usage(part.mountpoint)
                    partitions.append({
                        "device":     part.device,
                        "mountpoint": part.mountpoint,
                        "fstype":     part.fstype,
                        "total_gb":   round(usage.total / 1024 ** 3, 2),
                        "used_gb":    round(usage.used  / 1024 ** 3, 2),
                        "free_gb":    round(usage.free  / 1024 ** 3, 2),
                        "percent":    usage.percent,
                    })
                except (PermissionError, OSError, FileNotFoundError):
                    continue
            if partitions:
                return partitions
        except Exception:
            pass

    # Fallback: parse /proc/mounts + statvfs
    try:
        seen = set()
        with open("/proc/mounts") as f:
            for line in f:
                parts_m = line.split()
                if len(parts_m) < 3:
                    continue
                device, mountpoint, fstype = parts_m[0], parts_m[1], parts_m[2]
                # Skip non-real filesystems
                if fstype in ("proc", "sysfs", "devpts", "devtmpfs", "cgroup",
                              "cgroup2", "pstore", "debugfs", "securityfs",
                              "tmpfs", "hugetlbfs", "mqueue", "fusectl"):
                    continue
                if mountpoint in seen:
                    continue
                seen.add(mountpoint)
                try:
                    st = os.statvfs(mountpoint)
                    total = st.f_frsize * st.f_blocks
                    free  = st.f_frsize * st.f_bfree
                    avail = st.f_frsize * st.f_bavail
                    used  = total - free
                    if total == 0:
                        continue
                    partitions.append({
                        "device":     device,
                        "mountpoint": mountpoint,
                        "fstype":     fstype,
                        "total_gb":   round(total / 1024 ** 3, 2),
                        "used_gb":    round(used  / 1024 ** 3, 2),
                        "free_gb":    round(avail / 1024 ** 3, 2),
                        "percent":    round(100.0 * used / total, 1),
                    })
                except (OSError, PermissionError):
                    continue
    except Exception:
        pass

    # Last resort: df -B1 parsing
    if not partitions:
        out, rc = _run(["df", "-B1"])
        if rc == 0:
            for line in out.strip().split("\n")[1:]:
                cols = line.split()
                if len(cols) < 6:
                    continue
                try:
                    device, total, used, avail, pct_str, mount = (
                        cols[0], int(cols[1]), int(cols[2]), int(cols[3]),
                        cols[4].replace("%", ""), cols[5]
                    )
                    if not device.startswith("/dev"):
                        continue
                    total_b = total
                    if total_b == 0:
                        continue
                    partitions.append({
                        "device":     device,
                        "mountpoint": mount,
                        "fstype":     "unknown",
                        "total_gb":   round(total_b       / 1024 ** 3, 2),
                        "used_gb":    round(used           / 1024 ** 3, 2),
                        "free_gb":    round(avail          / 1024 ** 3, 2),
                        "percent":    float(pct_str) if pct_str.replace(".", "").isdigit() else 0.0,
                    })
                except (ValueError, IndexError):
                    continue

    return partitions


# ── Disk I/O ─────────────────────────────────────────────────────────────────

def _read_diskstats():
    stats = {}
    try:
        with open("/proc/diskstats") as f:
            for line in f:
                p = line.split()
                if len(p) < 14:
                    continue
                name = p[2]
                # Skip loop, dm, sr, fd devices
                if any(name.startswith(x) for x in ("loop", "dm-", "sr", "fd")):
                    continue
                stats[name] = {
                    "read_ios":     int(p[3]),
                    "read_sectors": int(p[5]),
                    "write_ios":    int(p[7]),
                    "write_sectors":int(p[9]),
                }
    except Exception:
        pass
    return stats


def get_disk_io():
    if _HAS_PSUTIL:
        try:
            before = _psutil.disk_io_counters(perdisk=True)
            time.sleep(0.5)
            after  = _psutil.disk_io_counters(perdisk=True)
            dt     = 0.5
            result = {}
            for disk in after:
                if any(disk.startswith(x) for x in ("loop", "dm-", "sr")):
                    continue
                b = before.get(disk, after[disk])
                a = after[disk]
                result[disk] = {
                    "read_mb_s":  round((a.read_bytes  - b.read_bytes)  / dt / 1024 ** 2, 3),
                    "write_mb_s": round((a.write_bytes - b.write_bytes) / dt / 1024 ** 2, 3),
                    "read_iops":  round((a.read_count  - b.read_count)  / dt, 1),
                    "write_iops": round((a.write_count - b.write_count) / dt, 1),
                }
            return result
        except Exception:
            pass

    # Fallback: /proc/diskstats
    before = _read_diskstats()
    time.sleep(0.5)
    after  = _read_diskstats()
    dt     = 0.5
    result = {}
    for disk, a in after.items():
        b = before.get(disk)
        if not b:
            continue
        result[disk] = {
            "read_mb_s":  round((a["read_sectors"]  - b["read_sectors"])  * 512 / dt / 1024 ** 2, 3),
            "write_mb_s": round((a["write_sectors"] - b["write_sectors"]) * 512 / dt / 1024 ** 2, 3),
            "read_iops":  round((a["read_ios"]      - b["read_ios"])      / dt, 1),
            "write_iops": round((a["write_ios"]     - b["write_ios"])     / dt, 1),
        }
    return result


# ── Inodes ───────────────────────────────────────────────────────────────────

def get_inode_usage():
    out, rc = _run(["df", "-i"])
    if rc != 0 or not out:
        return []
    result = []
    for line in out.strip().split("\n")[1:]:
        cols = line.split()
        if len(cols) >= 6:
            result.append({
                "device":       cols[0],
                "inodes_total": cols[1],
                "inodes_used":  cols[2],
                "inodes_free":  cols[3],
                "inodes_pct":   cols[4],
                "mountpoint":   cols[5],
            })
    return result


# ── Collect ───────────────────────────────────────────────────────────────────

def collect_all():
    return {
        "df_output":    get_df_output(),
        "partitions":   get_disk_partitions(),
        "io":           get_disk_io(),
        "inodes":       get_inode_usage(),
        "collected_at": datetime.utcnow().isoformat() + "Z",
    }
