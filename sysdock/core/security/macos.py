"""macOS security backend.

Firewall: the Application Firewall via ``socketfilterfw`` (read-only state, no
sudo), falling back to ``pfctl`` where it is readable. Failed auth: the unified
log (``log show``), bounded by a tight time window and timeout. There is no
fail2ban equivalent, so intrusion is reported as cleanly unavailable.
"""

from __future__ import annotations

import re

from sysdock.core import proc
from sysdock.core.security.schema import (
    FailedAuth,
    FailedAuthLog,
    FirewallStatus,
    IntrusionStatus,
)

SOCKETFILTERFW = "/usr/libexec/ApplicationFirewall/socketfilterfw"
MAX_AUTH_EVENTS = 50

# ── pure parsers ──────────────────────────────────────────────────────────────


def parse_alf_state(text: str) -> FirewallStatus:
    """Parse ``socketfilterfw --getglobalstate``."""
    lowered = text.lower()
    if "state = 1" in lowered or "enabled" in lowered:
        enabled: bool | None = True
    elif "state = 0" in lowered or "disabled" in lowered:
        enabled = False
    else:
        enabled = None
    # The Application Firewall denies unsolicited inbound by default when on.
    return FirewallStatus(
        available=True,
        backend="alf",
        enabled=enabled,
        default_policy="deny" if enabled else "",
    )


def parse_pfctl(text: str) -> FirewallStatus:
    """Parse ``pfctl -s info`` output."""
    enabled = "Status: Enabled" in text
    return FirewallStatus(available=True, backend="pf", enabled=enabled, default_policy="")


_MAC_AUTH = re.compile(
    r"(?:authentication failure|Failed (?:password|to authenticate)).*?"
    r"(?:for\s+(?P<user>\S+))?",
    re.IGNORECASE,
)
_IP = re.compile(r"(\d{1,3}(?:\.\d{1,3}){3})")


def parse_macos_auth(text: str, max_events: int = MAX_AUTH_EVENTS) -> list[FailedAuth]:
    events: list[FailedAuth] = []
    for line in text.splitlines():
        low = line.lower()
        if "fail" not in low or ("authent" not in low and "password" not in low):
            continue
        user = ""
        m = _MAC_AUTH.search(line)
        if m and m.groupdict().get("user"):
            user = m.group("user")
        ip_match = _IP.search(line)
        source = ip_match.group(1) if ip_match else ""
        # Unified-log syslog style starts with an ISO-ish timestamp.
        ts = line[:19].strip()
        events.append(FailedAuth(timestamp=ts, user=user, source=source, raw=line.strip()))
    return list(reversed(events[-max_events:]))


# ── command-running collectors ────────────────────────────────────────────────


def collect_firewall() -> FirewallStatus:
    if proc.which(SOCKETFILTERFW):
        res = proc.run([SOCKETFILTERFW, "--getglobalstate"], timeout=5)
        if res.ok:
            return parse_alf_state(res.stdout)
    if proc.which("pfctl"):
        res = proc.run(["pfctl", "-s", "info"], timeout=5)
        if res.ok:
            return parse_pfctl(res.stdout)
        return FirewallStatus(
            available=False, backend="pf", reason="pfctl present but not readable (needs root)"
        )
    return FirewallStatus(available=False, reason="no readable firewall backend")


def collect_intrusion() -> IntrusionStatus:
    return IntrusionStatus(
        available=False, reason="no intrusion backend on macOS (fail2ban is Linux-only)"
    )


def collect_failed_auth() -> FailedAuthLog:
    if not proc.which("log"):
        return FailedAuthLog(available=False, reason="unified log tool unavailable")
    res = proc.run(
        [
            "log",
            "show",
            "--style",
            "syslog",
            "--last",
            "30m",
            "--predicate",
            'process == "sshd" OR eventMessage CONTAINS[c] "authentication failure"',
        ],
        timeout=8,
    )
    if res.timed_out:
        return FailedAuthLog(available=False, reason="unified log query timed out")
    if not res.ok:
        return FailedAuthLog(available=False, reason="unified log not readable")
    return FailedAuthLog(available=True, events=parse_macos_auth(res.stdout))
