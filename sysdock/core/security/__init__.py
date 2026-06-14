"""Security panel — the signature, capability-gated, cross-OS feature.

`SecurityCollector` dispatches to the Linux/macOS/Windows backend at runtime and
assembles the normalized :class:`SecuritySample`. Because the underlying commands
are comparatively expensive (journald, the unified log, PowerShell), the
collector caches its result for ``ttl`` seconds — so when the shared snapshot
timer ticks every couple of seconds the security panel is served from cache and
only re-runs commands occasionally.

Every backend call is wrapped so a missing tool, denied permission, or
unparseable output yields a typed "unavailable" section — never an exception.
"""

from __future__ import annotations

import time
from typing import Any, Callable, TypeVar

from sysdock.core import capabilities as caps_mod
from sysdock.core.logging import get_logger
from sysdock.core.security.ports import collect_open_ports
from sysdock.core.security.schema import (
    FailedAuthLog,
    FirewallStatus,
    IntrusionStatus,
    OpenPorts,
    SecuritySample,
)

log = get_logger(__name__)

DEFAULT_TTL = 20.0

T = TypeVar("T")


class SecurityCollector:
    def __init__(self, *, ttl: float = DEFAULT_TTL, platform: str | None = None) -> None:
        self.ttl = ttl
        self._platform = platform or caps_mod.current_platform()
        self._backend = self._load_backend(self._platform)
        self._cache: SecuritySample | None = None
        self._cached_at: float = 0.0

    @staticmethod
    def _load_backend(platform: str) -> Any:
        if platform == caps_mod.PLATFORM_LINUX:
            from sysdock.core.security import linux

            return linux
        if platform == caps_mod.PLATFORM_MACOS:
            from sysdock.core.security import macos

            return macos
        if platform == caps_mod.PLATFORM_WINDOWS:
            from sysdock.core.security import windows

            return windows
        return None

    def prime(self) -> None:
        """Run the first (potentially slow) collection off the timed path."""
        self.collect()

    def _guard(self, name: str, fn: Callable[[], T], default: T) -> T:
        try:
            return fn()
        except Exception as exc:
            log.warning("security.%s failed: %s", name, exc)
            return default

    def collect(self) -> SecuritySample:
        now = time.monotonic()
        if self._cache is not None and (now - self._cached_at) < self.ttl:
            return self._cache

        sample = SecuritySample(platform=self._platform, collected_at=time.time())
        # Ports are portable (psutil) and available on every platform.
        sample.open_ports = self._guard(
            "open_ports", collect_open_ports, OpenPorts(available=False, reason="error")
        )

        backend = self._backend
        if backend is None:
            reason = f"security backend not available on {self._platform}"
            sample.firewall = FirewallStatus(available=False, reason=reason)
            sample.failed_auth = FailedAuthLog(available=False, reason=reason)
            sample.intrusion = IntrusionStatus(available=False, reason=reason)
        else:
            sample.firewall = self._guard(
                "firewall",
                backend.collect_firewall,
                FirewallStatus(available=False, reason="collector error"),
            )
            sample.failed_auth = self._guard(
                "failed_auth",
                backend.collect_failed_auth,
                FailedAuthLog(available=False, reason="collector error"),
            )
            sample.intrusion = self._guard(
                "intrusion",
                backend.collect_intrusion,
                IntrusionStatus(available=False, reason="collector error"),
            )

        self._cache = sample
        self._cached_at = now
        return sample
