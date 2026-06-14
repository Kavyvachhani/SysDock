"""Windows security backend.

Firewall: ``Get-NetFirewallProfile`` (PowerShell, JSON), falling back to
``netsh advfirewall``. Failed logons: Security event log, Event ID 4625, via
``Get-WinEvent`` (requires administrator; degrades cleanly otherwise). There is
no fail2ban equivalent, so intrusion is reported as cleanly unavailable.

All parsing is pure and fixture-tested so these Windows paths are verified on any
CI runner.
"""

from __future__ import annotations

import json
from typing import Any

from sysdock.core import proc
from sysdock.core.logging import get_logger
from sysdock.core.security.schema import (
    FailedAuth,
    FailedAuthLog,
    FirewallStatus,
    IntrusionStatus,
)

log = get_logger(__name__)
MAX_AUTH_EVENTS = 50

_FW_PS = (
    "Get-NetFirewallProfile | Select-Object Name,"
    "@{N='Enabled';E={[bool]$_.Enabled}},"
    "@{N='DefaultInboundAction';E={\"$($_.DefaultInboundAction)\"}} | ConvertTo-Json -Compress"
)
_EVT_PS = (
    "Get-WinEvent -FilterHashtable @{LogName='Security';Id=4625} -MaxEvents 50 -ErrorAction Stop | "
    "Select-Object @{N='Time';E={$_.TimeCreated.ToString('o')}},"
    "@{N='User';E={$_.Properties[5].Value}},"
    "@{N='Source';E={$_.Properties[19].Value}} | ConvertTo-Json -Compress"
)

# ── pure parsers ──────────────────────────────────────────────────────────────


def _as_list(parsed: object) -> list[dict[str, Any]]:
    if isinstance(parsed, list):
        return [p for p in parsed if isinstance(p, dict)]
    if isinstance(parsed, dict):
        return [parsed]
    return []


def parse_netfirewall_json(text: str) -> FirewallStatus:
    try:
        profiles = _as_list(json.loads(text))
    except (json.JSONDecodeError, ValueError):
        return FirewallStatus(
            available=False, backend="windows-firewall", reason="unparseable firewall output"
        )
    if not profiles:
        return FirewallStatus(
            available=False, backend="windows-firewall", reason="no firewall profiles returned"
        )
    any_enabled = False
    actions: list[str] = []
    for prof in profiles:
        if bool(prof.get("Enabled")):
            any_enabled = True
            actions.append(str(prof.get("DefaultInboundAction", "")))
    policy_map = {"Block": "deny", "Allow": "allow", "NotConfigured": ""}
    default_policy = ""
    if "Block" in actions:
        default_policy = "deny"
    elif "Allow" in actions:
        default_policy = "allow"
    elif actions:
        default_policy = policy_map.get(actions[0], "")
    return FirewallStatus(
        available=True,
        backend="windows-firewall",
        enabled=any_enabled,
        default_policy=default_policy,
    )


def parse_netsh(text: str) -> FirewallStatus:
    """Fallback parser for ``netsh advfirewall show allprofiles``."""
    enabled = False
    for line in text.splitlines():
        stripped = line.strip()
        if stripped.lower().startswith("state") and "on" in stripped.lower():
            enabled = True
    return FirewallStatus(
        available=True, backend="windows-firewall", enabled=enabled, default_policy=""
    )


def parse_event_4625(text: str, max_events: int = MAX_AUTH_EVENTS) -> list[FailedAuth]:
    if not text.strip():
        return []
    try:
        rows = _as_list(json.loads(text))
    except (json.JSONDecodeError, ValueError):
        return []
    events: list[FailedAuth] = []
    for row in rows[:max_events]:
        events.append(
            FailedAuth(
                timestamp=str(row.get("Time", "")),
                user=str(row.get("User", "") or ""),
                source=str(row.get("Source", "") or ""),
                raw="",
            )
        )
    return events


# ── command-running collectors ────────────────────────────────────────────────


def _powershell(script: str, timeout: float) -> proc.ProcResult:
    exe = "powershell" if proc.which("powershell") else "pwsh"
    return proc.run(
        [exe, "-NoProfile", "-NonInteractive", "-Command", script],
        timeout=timeout,
    )


def collect_firewall() -> FirewallStatus:
    if proc.which("powershell") or proc.which("pwsh"):
        res = _powershell(_FW_PS, timeout=12)
        if res.ok and res.stdout.strip():
            return parse_netfirewall_json(res.stdout)
    if proc.which("netsh"):
        res = proc.run(["netsh", "advfirewall", "show", "allprofiles"], timeout=8)
        if res.ok and res.stdout.strip():
            return parse_netsh(res.stdout)
    return FirewallStatus(available=False, reason="no readable Windows firewall backend")


def collect_intrusion() -> IntrusionStatus:
    return IntrusionStatus(
        available=False, reason="no intrusion backend on Windows (fail2ban is Linux-only)"
    )


def collect_failed_auth() -> FailedAuthLog:
    if not (proc.which("powershell") or proc.which("pwsh")):
        return FailedAuthLog(available=False, reason="PowerShell unavailable")
    res = _powershell(_EVT_PS, timeout=15)
    if res.timed_out:
        return FailedAuthLog(available=False, reason="Security log query timed out")
    if not res.ok:
        # Most commonly: not running as administrator.
        return FailedAuthLog(
            available=False, reason="Security event log not readable (requires administrator)"
        )
    return FailedAuthLog(available=True, events=parse_event_4625(res.stdout))
