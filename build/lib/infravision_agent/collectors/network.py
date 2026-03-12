"""
Network collector: interfaces, RX/TX rates, connections, DNS.
Primary: psutil. Fallback: /proc/net/dev + /proc/net/tcp.
Python 3.6+. All Linux distributions.
"""
from __future__ import annotations

import os
import socket
import subprocess
import time
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


# ── /proc/net/dev reader ─────────────────────────────────────────────────────

def _proc_net_dev():
    stats = {}
    try:
        with open("/proc/net/dev") as f:
            for line in f.readlines()[2:]:
                if ":" not in line:
                    continue
                iface, data = line.split(":", 1)
                iface = iface.strip()
                nums  = data.split()
                if len(nums) < 16:
                    continue
                stats[iface] = {
                    "rx_bytes":   int(nums[0]),  "rx_packets": int(nums[1]),
                    "rx_errors":  int(nums[2]),  "rx_drop":    int(nums[3]),
                    "tx_bytes":   int(nums[8]),  "tx_packets": int(nums[9]),
                    "tx_errors":  int(nums[10]), "tx_drop":    int(nums[11]),
                }
    except Exception:
        pass
    return stats


def _iface_is_up(iface):
    try:
        path = "/sys/class/net/{}/operstate".format(iface)
        with open(path) as f:
            return f.read().strip() == "up"
    except Exception:
        return False


def _iface_addresses():
    addrs = {}
    out, rc = _run(["ip", "-o", "addr"])
    if rc == 0 and out:
        for line in out.strip().split("\n"):
            cols = line.split()
            if len(cols) < 4:
                continue
            iface  = cols[1]
            family = cols[2]
            ip     = cols[3].split("/")[0]
            if iface not in addrs:
                addrs[iface] = []
            addrs[iface].append({"type": family, "address": ip})
    return addrs


# ── Interfaces ───────────────────────────────────────────────────────────────

def get_interfaces():
    if _HAS_PSUTIL:
        try:
            before = _psutil.net_io_counters(pernic=True)
            time.sleep(0.5)
            after  = _psutil.net_io_counters(pernic=True)
            addrs  = _psutil.net_if_addrs()
            stats  = _psutil.net_if_stats()
            dt     = 0.5
            result = []
            for iface in after:
                if iface == "lo":
                    continue
                a  = after[iface]
                b  = before.get(iface, a)
                st = stats.get(iface)
                ip_list = []
                for addr in addrs.get(iface, []):
                    if addr.family == socket.AF_INET:
                        ip_list.append({"type": "ipv4", "address": addr.address,
                                        "netmask": addr.netmask})
                    elif addr.family == socket.AF_INET6:
                        ip_list.append({"type": "ipv6", "address": addr.address})
                result.append({
                    "interface":        iface,
                    "is_up":            st.isup if st else False,
                    "speed_mbps":       st.speed if st else 0,
                    "mtu":              st.mtu   if st else 0,
                    "addresses":        ip_list,
                    "bytes_recv_total": a.bytes_recv,
                    "bytes_sent_total": a.bytes_sent,
                    "rx_mb_s":  round((a.bytes_recv   - b.bytes_recv)   / dt / 1024 ** 2, 3),
                    "tx_mb_s":  round((a.bytes_sent   - b.bytes_sent)   / dt / 1024 ** 2, 3),
                    "rx_pkts_s":round((a.packets_recv - b.packets_recv) / dt, 1),
                    "tx_pkts_s":round((a.packets_sent - b.packets_sent) / dt, 1),
                    "errors_in":  a.errin,
                    "errors_out": a.errout,
                    "drop_in":    a.dropin,
                    "drop_out":   a.dropout,
                })
            return result
        except Exception:
            pass

    # Fallback: /proc/net/dev
    before  = _proc_net_dev()
    time.sleep(0.5)
    after   = _proc_net_dev()
    dt      = 0.5
    addrs   = _iface_addresses()
    result  = []
    for iface, a in after.items():
        if iface == "lo":
            continue
        b = before.get(iface, a)
        result.append({
            "interface":        iface,
            "is_up":            _iface_is_up(iface),
            "speed_mbps":       0,
            "mtu":              0,
            "addresses":        addrs.get(iface, []),
            "bytes_recv_total": a["rx_bytes"],
            "bytes_sent_total": a["tx_bytes"],
            "rx_mb_s":   round((a["rx_bytes"]   - b["rx_bytes"])   / dt / 1024 ** 2, 3),
            "tx_mb_s":   round((a["tx_bytes"]   - b["tx_bytes"])   / dt / 1024 ** 2, 3),
            "rx_pkts_s": round((a["rx_packets"] - b["rx_packets"]) / dt, 1),
            "tx_pkts_s": round((a["tx_packets"] - b["tx_packets"]) / dt, 1),
            "errors_in":  a["rx_errors"],
            "errors_out": a["tx_errors"],
            "drop_in":    a["rx_drop"],
            "drop_out":   a["tx_drop"],
        })
    return result


# ── Connection counts ────────────────────────────────────────────────────────

def get_connection_counts():
    if _HAS_PSUTIL:
        try:
            conns  = _psutil.net_connections(kind="inet")
            counts = {"total": len(conns), "established": 0, "time_wait": 0,
                      "close_wait": 0, "listen": 0, "fin_wait": 0, "udp": 0}
            for c in conns:
                s = c.status
                if s == "ESTABLISHED": counts["established"] += 1
                elif s == "TIME_WAIT": counts["time_wait"]   += 1
                elif s == "CLOSE_WAIT":counts["close_wait"]  += 1
                elif s == "LISTEN":    counts["listen"]       += 1
                elif "FIN" in s:       counts["fin_wait"]     += 1
                elif s == "NONE":      counts["udp"]          += 1
            return counts
        except Exception:
            pass

    # Fallback: /proc/net/tcp
    state_names = {
        "01": "ESTABLISHED", "02": "SYN_SENT",  "03": "SYN_RECV",
        "04": "FIN_WAIT1",   "05": "FIN_WAIT2", "06": "TIME_WAIT",
        "07": "CLOSE",       "08": "CLOSE_WAIT","09": "LAST_ACK",
        "0A": "LISTEN",      "0B": "CLOSING",
    }
    counts = {"total": 0, "established": 0, "time_wait": 0,
              "close_wait": 0, "listen": 0, "fin_wait": 0, "udp": 0}
    for path in ("/proc/net/tcp", "/proc/net/tcp6"):
        try:
            with open(path) as f:
                for line in f.readlines()[1:]:
                    cols = line.split()
                    if len(cols) < 4:
                        continue
                    state = state_names.get(cols[3].upper(), "UNKNOWN")
                    counts["total"] += 1
                    if state == "ESTABLISHED": counts["established"] += 1
                    elif state == "TIME_WAIT": counts["time_wait"]   += 1
                    elif state == "CLOSE_WAIT":counts["close_wait"]  += 1
                    elif state == "LISTEN":    counts["listen"]       += 1
                    elif "FIN" in state:       counts["fin_wait"]     += 1
        except Exception:
            pass
    try:
        with open("/proc/net/udp") as f:
            counts["udp"] = max(0, len(f.readlines()) - 1)
    except Exception:
        pass
    return counts


# ── DNS ──────────────────────────────────────────────────────────────────────

def get_dns_info():
    nameservers = []
    for path in ("/etc/resolv.conf", "/run/systemd/resolve/resolv.conf"):
        try:
            with open(path) as f:
                for line in f:
                    line = line.strip()
                    if line.startswith("nameserver"):
                        parts = line.split()
                        if len(parts) >= 2:
                            nameservers.append(parts[1])
            if nameservers:
                break
        except Exception:
            continue
    return {"nameservers": nameservers}


# ── Collect ───────────────────────────────────────────────────────────────────

def collect_all():
    return {
        "interfaces":   get_interfaces(),
        "connections":  get_connection_counts(),
        "dns":          get_dns_info(),
        "collected_at": datetime.utcnow().isoformat() + "Z",
    }
