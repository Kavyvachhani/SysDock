"""Normalized, cross-OS security schema.

Every surface (TUI, web, Prometheus) reads this one shape regardless of OS. A
capability that isn't present on this host is represented by a section with
``available=False`` and a human ``reason`` — never ``null`` and never a missing
key. This is what lets the security panel render a clean "Not available on
<OS>" state instead of crashing or showing a blank.
"""

from __future__ import annotations

from dataclasses import dataclass, field


@dataclass
class FirewallStatus:
    available: bool = False
    backend: str = ""  # ufw / nftables / iptables / alf / pf / windows-firewall
    enabled: bool | None = None
    default_policy: str = ""  # normalized: deny / allow / reject / ""
    reason: str = ""


@dataclass
class OpenPort:
    proto: str  # tcp / udp / tcp6 / udp6
    address: str
    port: int
    pid: int | None = None
    process: str = ""


@dataclass
class OpenPorts:
    available: bool = False
    reason: str = ""
    ports: list[OpenPort] = field(default_factory=list)


@dataclass
class FailedAuth:
    timestamp: str = ""
    user: str = ""
    source: str = ""  # source IP/host
    raw: str = ""


@dataclass
class FailedAuthLog:
    available: bool = False
    reason: str = ""
    events: list[FailedAuth] = field(default_factory=list)


@dataclass
class IntrusionBlock:
    source: str = ""  # banned IP
    jail: str = ""  # fail2ban jail / rule name
    count: int = 0


@dataclass
class IntrusionStatus:
    available: bool = False
    reason: str = ""
    blocks: list[IntrusionBlock] = field(default_factory=list)


@dataclass
class SecuritySample:
    platform: str = ""
    firewall: FirewallStatus = field(default_factory=FirewallStatus)
    open_ports: OpenPorts = field(default_factory=OpenPorts)
    failed_auth: FailedAuthLog = field(default_factory=FailedAuthLog)
    intrusion: IntrusionStatus = field(default_factory=IntrusionStatus)
    collected_at: float = 0.0
