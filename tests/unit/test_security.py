"""Security backend tests — parsers fixture-tested for all three OSes.

Parsing is pure, so the Linux/macOS/Windows code paths are all verified here
regardless of the runner's OS. The dispatcher and live ports collector are also
exercised for clean degradation.
"""

from __future__ import annotations

from sysdock.core import capabilities as caps
from sysdock.core.security import SecurityCollector, linux, macos, windows
from sysdock.core.security.ports import collect_open_ports

# ── Linux ─────────────────────────────────────────────────────────────────────

UFW_ACTIVE = """Status: active

Logging: on (low)
Default: deny (incoming), allow (outgoing), disabled (routed)
New profiles: skip

To                         Action      From
--                         ------      ----
22/tcp                     ALLOW IN    Anywhere
"""

IPTABLES = """-P INPUT DROP
-P FORWARD DROP
-A INPUT -i lo -j ACCEPT
-A INPUT -p tcp -m tcp --dport 22 -j ACCEPT
"""

NFT = """table inet filter {
\tchain input {
\t\ttype filter hook input priority 0; policy drop;
\t\tiif "lo" accept
\t}
}
"""

FAIL2BAN_STATUS = """Status
|- Number of jail:\t2
`- Jail list:\tsshd, nginx-http-auth
"""

FAIL2BAN_JAIL = """Status for the jail: sshd
|- Filter
|  |- Currently failed:\t1
|  `- File list:\t/var/log/auth.log
`- Actions
   |- Currently banned:\t2
   |- Total banned:\t5
   `- Banned IP list:\t192.168.1.10 10.0.0.5
"""

AUTH_LOG = """Jan 10 10:00:01 host sshd[123]: Failed password for invalid user admin from 1.2.3.4 port 51234 ssh2
Jan 10 10:00:05 host sshd[124]: Failed password for root from 5.6.7.8 port 4444 ssh2
Jan 10 10:00:09 host sshd[125]: Accepted password for ok from 9.9.9.9 port 22 ssh2
Jan 10 10:00:11 host sshd[126]: Invalid user oracle from 7.7.7.7
"""


def test_parse_ufw_active():
    fw = linux.parse_ufw(UFW_ACTIVE)
    assert fw.available and fw.enabled is True
    assert fw.backend == "ufw"
    assert fw.default_policy == "deny"


def test_parse_ufw_inactive():
    fw = linux.parse_ufw("Status: inactive\n")
    assert fw.enabled is False


def test_parse_iptables_policy_and_rules():
    fw = linux.parse_iptables(IPTABLES)
    assert fw.backend == "iptables"
    assert fw.default_policy == "deny"
    assert fw.enabled is True


def test_parse_iptables_accept_no_rules_is_disabled():
    fw = linux.parse_iptables("-P INPUT ACCEPT\n")
    assert fw.enabled is False
    assert fw.default_policy == "allow"


def test_parse_nft_input_drop():
    fw = linux.parse_nft(NFT)
    assert fw.backend == "nftables"
    assert fw.enabled is True
    assert fw.default_policy == "deny"


def test_parse_nft_empty():
    fw = linux.parse_nft("")
    assert fw.enabled is False


def test_parse_auth_log_extracts_user_and_source():
    events = linux.parse_auth_log(AUTH_LOG)
    # 3 failures (2 Failed password + 1 Invalid user); the Accepted line ignored.
    assert len(events) == 3
    # newest first
    assert events[0].user == "oracle"
    assert events[0].source == "7.7.7.7"
    assert any(e.user == "admin" and e.source == "1.2.3.4" for e in events)


def test_parse_fail2ban():
    assert linux.parse_fail2ban_jails(FAIL2BAN_STATUS) == ["sshd", "nginx-http-auth"]
    blocks = linux.parse_fail2ban_jail(FAIL2BAN_JAIL, "sshd")
    ips = {b.source for b in blocks}
    assert ips == {"192.168.1.10", "10.0.0.5"}
    assert all(b.jail == "sshd" for b in blocks)


# ── macOS ─────────────────────────────────────────────────────────────────────


def test_parse_alf_enabled():
    fw = macos.parse_alf_state("Firewall is enabled. (State = 1)")
    assert fw.backend == "alf" and fw.enabled is True
    assert fw.default_policy == "deny"


def test_parse_alf_disabled():
    fw = macos.parse_alf_state("Firewall is disabled. (State = 0)")
    assert fw.enabled is False


def test_parse_pfctl_enabled():
    fw = macos.parse_pfctl("Status: Enabled for 0 days 01:02:03\n")
    assert fw.backend == "pf" and fw.enabled is True


def test_parse_macos_auth():
    text = (
        "2026-06-14 10:00:01.123+0000 localhost sshd[1]: "
        "Failed password for invalid user admin from 1.2.3.4 port 5000 ssh2\n"
        "2026-06-14 10:00:02.000+0000 localhost loginwindow[2]: some unrelated line\n"
    )
    events = macos.parse_macos_auth(text)
    assert len(events) == 1
    assert events[0].source == "1.2.3.4"


def test_macos_intrusion_is_cleanly_unavailable():
    intr = macos.collect_intrusion()
    assert intr.available is False
    assert "Linux-only" in intr.reason


# ── Windows ─────────────────────────────────────────────────────────────────--

WIN_FW_JSON = (
    '[{"Name":"Domain","Enabled":true,"DefaultInboundAction":"Block"},'
    '{"Name":"Private","Enabled":true,"DefaultInboundAction":"Block"},'
    '{"Name":"Public","Enabled":false,"DefaultInboundAction":"NotConfigured"}]'
)
WIN_FW_SINGLE = '{"Name":"Public","Enabled":true,"DefaultInboundAction":"Allow"}'
WIN_4625 = (
    '[{"Time":"2026-06-14T10:00:00+00:00","User":"administrator","Source":"1.2.3.4"},'
    '{"Time":"2026-06-14T10:01:00+00:00","User":"guest","Source":"5.6.7.8"}]'
)


def test_parse_netfirewall_json():
    fw = windows.parse_netfirewall_json(WIN_FW_JSON)
    assert fw.backend == "windows-firewall"
    assert fw.enabled is True
    assert fw.default_policy == "deny"  # Block on enabled profiles


def test_parse_netfirewall_single_object():
    fw = windows.parse_netfirewall_json(WIN_FW_SINGLE)
    assert fw.enabled is True
    assert fw.default_policy == "allow"


def test_parse_netfirewall_garbage_is_unavailable():
    fw = windows.parse_netfirewall_json("not json")
    assert fw.available is False


def test_parse_netsh_state_on():
    fw = windows.parse_netsh("Domain Profile Settings:\nState                 ON\n")
    assert fw.enabled is True


def test_parse_event_4625():
    events = windows.parse_event_4625(WIN_4625)
    assert len(events) == 2
    assert events[0].user == "administrator"
    assert events[0].source == "1.2.3.4"


def test_parse_event_4625_empty():
    assert windows.parse_event_4625("") == []


def test_windows_intrusion_unavailable():
    assert windows.collect_intrusion().available is False


# ── Ports (portable) + dispatcher ──────────────────────────────────────────────


def test_open_ports_live():
    result = collect_open_ports()
    # Either we enumerated ports, or we degraded cleanly with a reason.
    assert result.available or result.reason
    for p in result.ports:
        assert 0 <= p.port <= 65535
        assert p.proto in ("tcp", "udp", "tcp6", "udp6")


def test_open_ports_parsing_with_mocked_psutil(monkeypatch):
    """Exercise the port-parsing loop deterministically on any OS (macOS hides
    sockets without root, so the live test can't cover this path there)."""
    import socket
    from collections import namedtuple

    from sysdock.core.security import ports as ports_mod

    Addr = namedtuple("Addr", ["ip", "port"])
    Conn = namedtuple("Conn", ["family", "type", "laddr", "raddr", "status", "pid"])

    fake = [
        Conn(socket.AF_INET, socket.SOCK_STREAM, Addr("0.0.0.0", 22), None, "LISTEN", 1000),
        Conn(socket.AF_INET6, socket.SOCK_STREAM, Addr("::", 443), None, "LISTEN", 1001),
        Conn(socket.AF_INET, socket.SOCK_DGRAM, Addr("0.0.0.0", 53), None, "NONE", 1002),
        # A non-listening TCP socket must be excluded.
        Conn(
            socket.AF_INET,
            socket.SOCK_STREAM,
            Addr("1.2.3.4", 5555),
            Addr("9.9.9.9", 80),
            "ESTABLISHED",
            1003,
        ),
    ]

    class FakeProc:
        def __init__(self, pid):
            self._pid = pid

        def name(self):
            return {1000: "sshd", 1001: "nginx", 1002: "systemd-resolved"}.get(self._pid, "?")

    monkeypatch.setattr(ports_mod.psutil, "net_connections", lambda kind="inet": fake)
    monkeypatch.setattr(ports_mod.psutil, "Process", FakeProc)

    result = ports_mod.collect_open_ports()
    assert result.available
    portset = {(p.port, p.proto) for p in result.ports}
    assert (22, "tcp") in portset
    assert (443, "tcp6") in portset
    assert (53, "udp") in portset
    assert 5555 not in {p.port for p in result.ports}  # established excluded
    assert any(p.process == "sshd" for p in result.ports)


def test_collector_dispatches_and_never_raises():
    sample = SecurityCollector(ttl=0.0).collect()
    assert sample.platform in (
        caps.PLATFORM_LINUX,
        caps.PLATFORM_MACOS,
        caps.PLATFORM_WINDOWS,
        caps.PLATFORM_UNKNOWN,
    )
    # Every section is present and typed (never None), available or not.
    assert sample.firewall is not None
    assert sample.open_ports is not None
    assert sample.failed_auth is not None
    assert sample.intrusion is not None


def test_collector_caches_within_ttl():
    c = SecurityCollector(ttl=60.0)
    first = c.collect()
    second = c.collect()
    assert first is second  # served from cache, no re-run


def test_unknown_platform_degrades_cleanly():
    c = SecurityCollector(ttl=0.0, platform=caps.PLATFORM_UNKNOWN)
    sample = c.collect()
    assert sample.firewall.available is False
    assert sample.intrusion.available is False
    # Ports still work (portable) regardless of platform backend.
    assert sample.open_ports is not None
