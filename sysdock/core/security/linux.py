"""Linux security backend.

Firewall: ufw, then nftables, then iptables. Intrusion: fail2ban-client.
Failed auth: journald (journalctl) or /var/log/auth.log|secure.

Parsing is split into pure functions (``parse_*``) that take command output and
return schema objects — these are fixture-tested. The collector functions run
the commands through :mod:`sysdock.core.proc` and feed the output to them.
"""

from __future__ import annotations

import re

from sysdock.core import proc
from sysdock.core.security.schema import (
    FailedAuth,
    FailedAuthLog,
    FirewallStatus,
    IntrusionBlock,
    IntrusionStatus,
)

MAX_AUTH_EVENTS = 50

# ── pure parsers ──────────────────────────────────────────────────────────────


def parse_ufw(text: str) -> FirewallStatus:
    enabled = "Status: active" in text
    default_policy = ""
    for line in text.splitlines():
        line = line.strip()
        if line.startswith("Default:"):
            # e.g. "Default: deny (incoming), allow (outgoing), disabled (routed)"
            first = line.split(":", 1)[1].split(",")[0].strip()
            default_policy = first.split()[0].lower() if first else ""
            break
    return FirewallStatus(
        available=True, backend="ufw", enabled=enabled, default_policy=default_policy
    )


def parse_iptables(text: str) -> FirewallStatus:
    """Parse ``iptables -S`` output for the INPUT chain policy and rules."""
    input_policy = ""
    rule_count = 0
    for line in text.splitlines():
        line = line.strip()
        if line.startswith("-P INPUT"):
            input_policy = line.split()[-1].upper()
        elif line.startswith("-A INPUT"):
            rule_count += 1
    policy_map = {"DROP": "deny", "REJECT": "reject", "ACCEPT": "allow"}
    default_policy = policy_map.get(input_policy, input_policy.lower())
    # Consider the firewall "enabled" if the default is restrictive or rules exist.
    enabled = input_policy in ("DROP", "REJECT") or rule_count > 0
    return FirewallStatus(
        available=True, backend="iptables", enabled=enabled, default_policy=default_policy
    )


def parse_nft(text: str) -> FirewallStatus:
    """Parse ``nft list ruleset`` — look for an input hook and its policy."""
    if not text.strip():
        return FirewallStatus(available=True, backend="nftables", enabled=False, default_policy="")
    default_policy = ""
    in_input_hook = False
    for line in text.splitlines():
        stripped = line.strip()
        if "hook input" in stripped:
            in_input_hook = True
        if in_input_hook and "policy" in stripped:
            m = re.search(r"policy\s+(\w+)", stripped)
            if m:
                pol = m.group(1).lower()
                default_policy = {"drop": "deny", "accept": "allow"}.get(pol, pol)
            in_input_hook = False
    return FirewallStatus(
        available=True, backend="nftables", enabled=True, default_policy=default_policy
    )


_AUTH_PATTERNS = [
    re.compile(r"Failed password for (?:invalid user )?(?P<user>\S+) from (?P<src>\S+)"),
    re.compile(r"Invalid user (?P<user>\S+) from (?P<src>\S+)"),
    re.compile(r"authentication failure;.*?ruser=(?P<user>\S*).*?rhost=(?P<src>\S+)"),
]


def parse_auth_log(text: str, max_events: int = MAX_AUTH_EVENTS) -> list[FailedAuth]:
    events: list[FailedAuth] = []
    for line in text.splitlines():
        if (
            "Failed password" not in line
            and "Invalid user" not in line
            and "authentication failure" not in line
        ):
            continue
        user = ""
        source = ""
        for pat in _AUTH_PATTERNS:
            m = pat.search(line)
            if m:
                user = m.groupdict().get("user", "") or ""
                source = m.groupdict().get("src", "") or ""
                break
        # Leading syslog timestamp, best-effort (first 15 chars on classic format).
        ts = line[:15].strip() if len(line) > 15 else ""
        events.append(FailedAuth(timestamp=ts, user=user, source=source, raw=line.strip()))
    # Most recent last in logs; return the tail, newest first.
    return list(reversed(events[-max_events:]))


def parse_fail2ban_jails(text: str) -> list[str]:
    for line in text.splitlines():
        if "Jail list:" in line:
            raw = line.split(":", 1)[1]
            return [j.strip() for j in raw.split(",") if j.strip()]
    return []


def parse_fail2ban_jail(text: str, jail: str) -> list[IntrusionBlock]:
    banned_ips: list[str] = []
    total = 0
    for line in text.splitlines():
        stripped = line.strip()
        if "Banned IP list:" in stripped:
            raw = stripped.split(":", 1)[1]
            banned_ips = [ip.strip() for ip in raw.split() if ip.strip()]
        elif "Currently banned:" in stripped:
            m = re.search(r"(\d+)", stripped)
            if m:
                total = int(m.group(1))
    blocks = [IntrusionBlock(source=ip, jail=jail, count=1) for ip in banned_ips]
    if not blocks and total:
        # Count known but IPs not listed in this output form.
        blocks.append(IntrusionBlock(source="", jail=jail, count=total))
    return blocks


# ── command-running collectors ────────────────────────────────────────────────


def collect_firewall() -> FirewallStatus:
    if proc.which("ufw"):
        res = proc.run(["ufw", "status", "verbose"], timeout=5)
        if res.ok:
            return parse_ufw(res.stdout)
    if proc.which("nft"):
        res = proc.run(["nft", "list", "ruleset"], timeout=5)
        if res.ok:
            return parse_nft(res.stdout)
    if proc.which("iptables"):
        res = proc.run(["iptables", "-S", "INPUT"], timeout=5)
        if res.ok:
            return parse_iptables(res.stdout)
        if res.returncode != proc.RC_NOT_FOUND:
            return FirewallStatus(
                available=False,
                backend="iptables",
                reason="iptables present but not readable (needs root)",
            )
    return FirewallStatus(available=False, reason="no supported firewall backend found")


def collect_intrusion() -> IntrusionStatus:
    if not proc.which("fail2ban-client"):
        return IntrusionStatus(available=False, reason="fail2ban not installed")
    res = proc.run(["fail2ban-client", "status"], timeout=5)
    if not res.ok:
        return IntrusionStatus(
            available=False, reason="fail2ban-client not running or not permitted"
        )
    jails = parse_fail2ban_jails(res.stdout)
    blocks: list[IntrusionBlock] = []
    for jail in jails:
        jres = proc.run(["fail2ban-client", "status", jail], timeout=5)
        if jres.ok:
            blocks.extend(parse_fail2ban_jail(jres.stdout, jail))
    return IntrusionStatus(available=True, blocks=blocks)


def collect_failed_auth() -> FailedAuthLog:
    if proc.which("journalctl"):
        res = proc.run(
            ["journalctl", "-u", "ssh", "-u", "sshd", "-n", "300", "--no-pager", "-q"],
            timeout=6,
        )
        if res.ok and res.stdout.strip():
            return FailedAuthLog(available=True, events=parse_auth_log(res.stdout))
    for path in ("/var/log/auth.log", "/var/log/secure"):
        res = proc.run(["tail", "-n", "500", path], timeout=5)
        if res.ok and res.stdout.strip():
            return FailedAuthLog(available=True, events=parse_auth_log(res.stdout))
    return FailedAuthLog(available=False, reason="no readable auth log (journald/auth.log)")
