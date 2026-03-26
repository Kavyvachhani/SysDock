"""
Security collector: Falco, SSH events, fail2ban, open ports, last logins.
Reads from Falco container logs, /var/log/auth.log (or /var/log/secure),
fail2ban-client, ss/netstat, journalctl, last.
Everything is try/except — never crashes if a tool is missing.
Python 3.6+, all Linux distros.
"""
from __future__ import annotations

import os
import re
import subprocess
from datetime import datetime


def _run(cmd, timeout=8):
    try:
        r = subprocess.run(cmd, capture_output=True, text=True, timeout=timeout)
        return r.stdout, r.returncode
    except FileNotFoundError:
        return "", 127
    except subprocess.TimeoutExpired:
        return "", 124
    except Exception:
        return "", -1


# ---- UFW (Uncomplicated Firewall) --------------------------------------------

def get_ufw_status():
    result = {
        "installed": False,
        "active":    False,
        "rules":     [],
    }
    
    out, rc = _run(["sudo", "ufw", "status", "numbered"], timeout=5)
    if rc != 0:
        out, rc = _run(["ufw", "status", "numbered"], timeout=5)
        
    if rc != 0:
        return result
        
    result["installed"] = True
    result["active"] = "Status: active" in out
    
    if result["active"]:
        rules = []
        for line in out.split("\n"):
            line = line.strip()
            if not line or line.startswith("Status:") or line.startswith("To"):
                continue
            if "--" in line:
                continue
            if "ALLOW" in line or "DENY" in line:
                rules.append(line)
        result["rules"] = rules[:10]
        
    return result


# ---- SSH auth events -------------------------------------------------------

def get_ssh_auth_events(limit=20):
    log_paths = [
        "/var/log/auth.log",
        "/var/log/secure",
        "/var/log/messages",
    ]
    events = []
    for path in log_paths:
        if not os.path.exists(path):
            continue
        try:
            out, _ = _run(["tail", "-n", "500", path])
            for line in out.split("\n"):
                if any(k in line for k in ["sshd", "sudo", "su:", "Failed", "Accepted", "Invalid", "pam_unix"]):
                    events.append({
                        "raw":  line.strip(),
                        "type": _classify_auth(line),
                    })
            if events:
                break
        except Exception:
            continue

    # fallback: journalctl
    if not events:
        out, rc = _run(["journalctl", "-u", "sshd", "-u", "ssh", "-n", "100", "--no-pager"])
        if rc == 0:
            for line in out.split("\n"):
                if line.strip():
                    events.append({"raw": line.strip(), "type": _classify_auth(line)})

    events.reverse()
    return events[:limit]


def _classify_auth(line):
    if "Failed password" in line or "Invalid user" in line or "FAILED" in line:
        return "ssh_fail"
    if "Accepted password" in line or "Accepted publickey" in line:
        return "ssh_success"
    if "sudo" in line and "COMMAND" in line:
        return "sudo"
    if "session opened" in line:
        return "session_open"
    if "session closed" in line:
        return "session_close"
    return "other"


# ---- fail2ban --------------------------------------------------------------

def get_fail2ban_status():
    result = {"installed": False, "jails": []}
    out, rc = _run(["fail2ban-client", "status"])
    if rc != 0:
        result["error"] = "fail2ban not installed or not running"
        return result

    result["installed"] = True
    result["summary"]   = out.strip()

    for line in out.split("\n"):
        if "Jail list:" in line:
            jails = [j.strip() for j in line.split(":")[-1].split(",") if j.strip()]
            for jail in jails:
                jail_out, jail_rc = _run(["fail2ban-client", "status", jail])
                if jail_rc == 0:
                    result["jails"].append({"name": jail, "output": jail_out.strip()})
    return result


# ---- Open ports ------------------------------------------------------------

def get_open_ports():
    # Try ss first
    out, rc = _run(["ss", "-tlnp"])
    if rc == 0 and out:
        ports = []
        for line in out.strip().split("\n")[1:]:
            parts = line.split()
            if len(parts) >= 4:
                ports.append({
                    "state":         parts[0],
                    "local_address": parts[3],
                    "process":       parts[6] if len(parts) > 6 else "",
                })
        return ports

    # Try netstat
    out, rc = _run(["netstat", "-tlnp"])
    if rc == 0 and out:
        ports = []
        for line in out.strip().split("\n")[2:]:
            parts = line.split()
            if len(parts) >= 4:
                ports.append({
                    "state":         parts[5] if len(parts) > 5 else "",
                    "local_address": parts[3],
                    "process":       parts[6] if len(parts) > 6 else "",
                })
        return ports

    return []


# ---- Kernel/security events ------------------------------------------------

def get_kernel_events(limit=10):
    events = []
    keywords = ["oom", "killed process", "segfault", "kernel panic", "audit", "avc:"]

    # journalctl
    out, rc = _run(["journalctl", "-n", "200", "--no-pager", "-p", "warning"])
    if rc == 0:
        for line in out.split("\n"):
            low = line.lower()
            if any(k in low for k in keywords):
                events.append(line.strip())
        if events:
            return events[-limit:]

    # /var/log/syslog or /var/log/messages
    for log in ("/var/log/syslog", "/var/log/messages"):
        if not os.path.exists(log):
            continue
        try:
            out, _ = _run(["tail", "-n", "500", log])
            for line in out.split("\n"):
                low = line.lower()
                if any(k in low for k in keywords):
                    events.append(line.strip())
            break
        except Exception:
            continue

    return events[-limit:]


# ---- Last logins -----------------------------------------------------------

def get_last_logins(limit=10):
    out, rc = _run(["last", "-n", str(limit), "-F"])
    if rc != 0:
        out, rc = _run(["last", "-n", str(limit)])
    if rc == 0:
        return [l.strip() for l in out.split("\n") if l.strip() and not l.startswith("wtmp")][:limit]
    return []


# ---- Who is logged in now --------------------------------------------------

def get_who():
    out, rc = _run(["who"])
    if rc == 0 and out:
        users = []
        for line in out.strip().split("\n"):
            if line.strip():
                users.append(line.strip())
        return users
    return []


def collect_all():
    return {
        "ufw":            get_ufw_status(),
        "ssh_events":     get_ssh_auth_events(),
        "fail2ban":       get_fail2ban_status(),
        "open_ports":     get_open_ports(),
        "kernel_events":  get_kernel_events(),
        "last_logins":    get_last_logins(),
        "logged_in_now":  get_who(),
        "collected_at":   datetime.utcnow().isoformat() + "Z",
    }
