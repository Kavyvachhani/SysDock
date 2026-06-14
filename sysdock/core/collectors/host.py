"""Host/static info — hostname, OS, kernel, arch, boot time, uptime.

Static facts (hostname, OS string) are detected once and cached; only uptime is
recomputed each tick.
"""

from __future__ import annotations

import platform
import socket
import time
from dataclasses import dataclass

from sysdock.core.logging import get_logger

try:
    import psutil
except ImportError:  # pragma: no cover
    psutil = None

log = get_logger(__name__)


@dataclass
class HostSample:
    hostname: str = "unknown"
    os: str = "unknown"
    kernel: str = ""
    arch: str = ""
    python_version: str = ""
    boot_time: float | None = None
    uptime_seconds: int = 0
    uptime_human: str = "unknown"


def _human_uptime(seconds: int) -> str:
    days, rem = divmod(seconds, 86400)
    hours, rem = divmod(rem, 3600)
    minutes = rem // 60
    return f"{days}d {hours}h {minutes}m"


class HostCollector:
    def __init__(self) -> None:
        self._static: dict[str, str] | None = None

    def _static_info(self) -> dict[str, str]:
        if self._static is not None:
            return self._static
        try:
            hostname = socket.gethostname()
        except OSError:
            hostname = "unknown"
        system = platform.system()
        if system == "Darwin":
            ver = platform.mac_ver()[0]
            os_name = f"macOS {ver}" if ver else "macOS"
        elif system == "Windows":
            os_name = f"Windows {platform.release()}"
        else:
            os_name = self._linux_pretty_name() or system or "unknown"
        self._static = {
            "hostname": hostname,
            "os": os_name,
            "kernel": platform.release(),
            "arch": platform.machine(),
            "python_version": platform.python_version(),
        }
        return self._static

    @staticmethod
    def _linux_pretty_name() -> str | None:
        for path in ("/etc/os-release", "/usr/lib/os-release"):
            try:
                with open(path) as fh:
                    for line in fh:
                        if line.startswith("PRETTY_NAME="):
                            return line.split("=", 1)[1].strip().strip('"')
            except OSError:
                continue
        return None

    def collect(self) -> HostSample:
        static = self._static_info()
        boot: float | None = None
        uptime = 0
        if psutil is not None:
            try:
                boot = float(psutil.boot_time())
                uptime = max(0, int(time.time() - boot))
            except Exception as exc:
                log.debug("boot_time failed: %s", exc)
        return HostSample(
            hostname=static["hostname"],
            os=static["os"],
            kernel=static["kernel"],
            arch=static["arch"],
            python_version=static["python_version"],
            boot_time=boot,
            uptime_seconds=uptime,
            uptime_human=_human_uptime(uptime) if uptime else "unknown",
        )
