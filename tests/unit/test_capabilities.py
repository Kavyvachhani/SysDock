"""Capability-detection tests.

Detection is injectable (``system`` + ``which``), so the Linux, macOS, and
Windows code paths are all exercised here regardless of the runner's OS.
"""

from __future__ import annotations

import json

from sysdock.core import capabilities as caps


def _which_none(_name: str) -> None:
    return None


def _which_all(name: str) -> str:
    return f"/usr/bin/{name}"


def test_current_platform_is_known():
    assert caps.current_platform() in {
        caps.PLATFORM_LINUX,
        caps.PLATFORM_MACOS,
        caps.PLATFORM_WINDOWS,
        caps.PLATFORM_UNKNOWN,
    }


def test_detect_is_json_serialisable():
    c = caps.detect()
    # Round-trips cleanly — surfaces serialise this to /api and logs.
    payload = json.dumps(c.to_dict())
    assert "platform" in payload
    assert isinstance(c.elevated, bool)


def test_linux_firewall_backends_present_when_binaries_exist():
    c = caps.detect(system=caps.PLATFORM_LINUX, which=_which_all, arch="x86_64")
    names = {cap.name for cap in c.firewall}
    assert names == {"ufw", "nft", "iptables"}
    assert all(cap.available for cap in c.firewall)
    assert any(cap.name == "fail2ban" and cap.available for cap in c.intrusion)


def test_linux_firewall_unavailable_when_no_binaries():
    c = caps.detect(system=caps.PLATFORM_LINUX, which=_which_none, arch="x86_64")
    assert all(not cap.available for cap in c.firewall)
    # Absent capability is a clean False, never an exception.
    assert c.intrusion[0].available is False


def test_macos_uses_socketfilterfw_and_pf():
    c = caps.detect(system=caps.PLATFORM_MACOS, which=_which_none, arch="arm64")
    names = {cap.name for cap in c.firewall}
    assert "socketfilterfw" in names
    assert "pf" in names
    # No fail2ban concept on macOS.
    assert c.intrusion == []
    # Apple GPU advertised on Apple Silicon.
    assert any(cap.name == "apple" and cap.available for cap in c.gpu)


def test_macos_intel_has_no_apple_gpu():
    c = caps.detect(system=caps.PLATFORM_MACOS, which=_which_none, arch="x86_64")
    assert any(cap.name == "apple" and not cap.available for cap in c.gpu)


def test_windows_firewall_and_service():
    c = caps.detect(system=caps.PLATFORM_WINDOWS, which=_which_all, arch="AMD64")
    names = {cap.name for cap in c.firewall}
    assert "netsh" in names
    assert any(cap.name == "windows-service" for cap in c.service_manager)


def test_available_in_helper():
    c = caps.detect(system=caps.PLATFORM_LINUX, which=_which_all, arch="x86_64")
    assert len(c.available_in("firewall")) == 3
    assert c.available_in("intrusion")[0].name == "fail2ban"


def test_metrics_group_reports_psutil():
    c = caps.detect(system=caps.PLATFORM_LINUX, which=_which_none, arch="x86_64")
    assert c.metrics[0].name == "psutil"
    # psutil is a hard dependency, so it is detected as available in the test env.
    assert c.metrics[0].available is True


def test_containers_group_always_reports_sdk_and_cli():
    c = caps.detect(system=caps.PLATFORM_LINUX, which=_which_all, arch="x86_64")
    names = {cap.name for cap in c.containers}
    assert names == {"docker-sdk", "docker-cli"}
    # docker-cli is available because _which_all resolves every binary.
    assert any(cap.name == "docker-cli" and cap.available for cap in c.containers)


def test_linux_auth_log_detects_journald():
    c = caps.detect(system=caps.PLATFORM_LINUX, which=_which_all, arch="x86_64")
    assert any(cap.name == "journald" and cap.available for cap in c.auth_log)


def test_unknown_platform_has_empty_os_specific_groups():
    c = caps.detect(system=caps.PLATFORM_UNKNOWN, which=_which_none, arch="x86_64")
    assert c.firewall == []
    assert c.service_manager == []
    # Portable groups still populated.
    assert c.metrics and c.containers
