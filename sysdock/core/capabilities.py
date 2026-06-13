"""Host capability detection.

Everything platform-specific consults this module before acting. Detection is
cheap (PATH lookups and a couple of filesystem probes — no privileged commands
are run here) and **pure with respect to its inputs**: :func:`detect` accepts an
optional ``system`` override and ``which`` callable so the Linux, macOS, and
Windows code paths can all be unit-tested on any CI runner.

A capability that is absent is never an error — surfaces render a clean
"Not available on <OS>" state based on what they find here.
"""

from __future__ import annotations

import os
import platform
import sys
from dataclasses import asdict, dataclass, field
from typing import Callable, Optional

from sysdock.core import proc

PLATFORM_LINUX = "linux"
PLATFORM_MACOS = "macos"
PLATFORM_WINDOWS = "windows"
PLATFORM_UNKNOWN = "unknown"

# macOS Application Firewall control binary — not on PATH, probed by path.
_SOCKETFILTERFW = "/usr/libexec/ApplicationFirewall/socketfilterfw"

WhichFn = Callable[[str], Optional[str]]


def current_platform() -> str:
    """Normalise ``sys.platform`` / ``os.name`` to one of the PLATFORM_* names."""
    if sys.platform.startswith("linux"):
        return PLATFORM_LINUX
    if sys.platform == "darwin":
        return PLATFORM_MACOS
    if os.name == "nt":
        return PLATFORM_WINDOWS
    return PLATFORM_UNKNOWN


@dataclass(frozen=True)
class Capability:
    """A single detected (or absent) capability."""

    name: str
    available: bool
    detail: str = ""


@dataclass
class Capabilities:
    """The full capability picture for this host.

    Grouped so surfaces can ask "does the firewall view have anything to show?"
    without re-running detection.
    """

    platform: str
    os_release: str
    arch: str
    python_version: str
    elevated: bool
    metrics: list[Capability] = field(default_factory=list)
    firewall: list[Capability] = field(default_factory=list)
    intrusion: list[Capability] = field(default_factory=list)
    auth_log: list[Capability] = field(default_factory=list)
    gpu: list[Capability] = field(default_factory=list)
    containers: list[Capability] = field(default_factory=list)
    service_manager: list[Capability] = field(default_factory=list)

    def to_dict(self) -> dict[str, object]:
        """A JSON-serialisable view of every capability."""
        return asdict(self)

    def available_in(self, group: str) -> list[Capability]:
        """Return the available capabilities within a named group."""
        items: list[Capability] = getattr(self, group, [])
        return [c for c in items if c.available]


def _is_elevated() -> bool:
    """Best-effort 'are we root/admin?' check that never raises."""
    geteuid = getattr(os, "geteuid", None)
    if callable(geteuid):
        try:
            return bool(geteuid() == 0)
        except OSError:
            return False
    # Windows
    try:
        import ctypes

        return bool(ctypes.windll.shell32.IsUserAnAdmin())  # type: ignore[attr-defined]
    except Exception:
        return False


def _psutil_detail() -> Capability:
    try:
        import psutil

        return Capability("psutil", True, getattr(psutil, "__version__", "unknown"))
    except Exception:
        return Capability("psutil", False, "not installed")


def _docker_caps(which: WhichFn) -> list[Capability]:
    try:
        import docker  # noqa: F401

        sdk = Capability("docker-sdk", True, "python docker SDK present")
    except Exception:
        sdk = Capability("docker-sdk", False, "optional extra not installed")
    cli_path = which("docker")
    cli = Capability("docker-cli", cli_path is not None, cli_path or "binary not on PATH")
    return [sdk, cli]


def _gpu_caps(system: str, which: WhichFn, arch: str) -> list[Capability]:
    caps: list[Capability] = []
    nvidia = which("nvidia-smi")
    caps.append(Capability("nvidia", nvidia is not None, nvidia or "nvidia-smi not found"))
    if system == PLATFORM_LINUX:
        rocm = which("rocm-smi")
        caps.append(Capability("amd", rocm is not None, rocm or "rocm-smi not found"))
        intel = which("intel_gpu_top")
        caps.append(Capability("intel", intel is not None, intel or "intel_gpu_top not found"))
    if system == PLATFORM_MACOS:
        apple = arch.lower() in ("arm64", "aarch64")
        caps.append(
            Capability(
                "apple", apple, "Apple Silicon" if apple else "Intel Mac (no integrated metrics)"
            )
        )
    return caps


def _firewall_caps(system: str, which: WhichFn) -> list[Capability]:
    caps: list[Capability] = []
    if system == PLATFORM_LINUX:
        for name in ("ufw", "nft", "iptables"):
            path = which(name)
            caps.append(Capability(name, path is not None, path or "not found"))
    elif system == PLATFORM_MACOS:
        sfw = os.path.exists(_SOCKETFILTERFW)
        caps.append(Capability("socketfilterfw", sfw, _SOCKETFILTERFW if sfw else "not present"))
        pfctl = which("pfctl")
        caps.append(Capability("pf", pfctl is not None, pfctl or "pfctl not found"))
    elif system == PLATFORM_WINDOWS:
        for name in ("netsh", "powershell"):
            path = which(name)
            caps.append(Capability(name, path is not None, path or "not found"))
    return caps


def _intrusion_caps(system: str, which: WhichFn) -> list[Capability]:
    if system == PLATFORM_LINUX:
        f2b = which("fail2ban-client")
        return [Capability("fail2ban", f2b is not None, f2b or "not installed")]
    return []


def _auth_log_caps(system: str, which: WhichFn) -> list[Capability]:
    caps: list[Capability] = []
    if system == PLATFORM_LINUX:
        journal = which("journalctl")
        caps.append(Capability("journald", journal is not None, journal or "journalctl not found"))
        for path in ("/var/log/auth.log", "/var/log/secure"):
            if os.path.exists(path):
                caps.append(Capability("auth-log-file", True, path))
                break
        else:
            caps.append(Capability("auth-log-file", False, "no auth.log/secure"))
    elif system == PLATFORM_MACOS:
        log_bin = which("log")
        caps.append(Capability("unified-log", log_bin is not None, log_bin or "log not found"))
    elif system == PLATFORM_WINDOWS:
        ps = which("powershell")
        caps.append(Capability("security-event-log", ps is not None, ps or "powershell not found"))
    return caps


def _service_caps(system: str, which: WhichFn) -> list[Capability]:
    if system == PLATFORM_LINUX:
        systemd = os.path.exists("/run/systemd/system")
        return [
            Capability(
                "systemd", systemd, "/run/systemd/system" if systemd else "not booted with systemd"
            )
        ]
    if system == PLATFORM_MACOS:
        launchctl = which("launchctl")
        return [Capability("launchd", launchctl is not None, launchctl or "launchctl not found")]
    if system == PLATFORM_WINDOWS:
        sc = which("sc")
        return [Capability("windows-service", sc is not None, sc or "sc not found")]
    return []


def detect(
    *,
    system: str | None = None,
    which: WhichFn | None = None,
    arch: str | None = None,
) -> Capabilities:
    """Detect what this host supports.

    Args:
        system: Override the detected platform (one of the PLATFORM_* names).
            Lets tests exercise the macOS/Windows paths on a Linux runner.
        which: Override the PATH-lookup function (defaults to :func:`proc.which`).
        arch: Override the machine architecture string.
    """
    system = system or current_platform()
    which = which or proc.which
    arch = arch or platform.machine()

    return Capabilities(
        platform=system,
        os_release=platform.release(),
        arch=arch,
        python_version=platform.python_version(),
        elevated=_is_elevated(),
        metrics=[_psutil_detail()],
        firewall=_firewall_caps(system, which),
        intrusion=_intrusion_caps(system, which),
        auth_log=_auth_log_caps(system, which),
        gpu=_gpu_caps(system, which, arch),
        containers=_docker_caps(which),
        service_manager=_service_caps(system, which),
    )
