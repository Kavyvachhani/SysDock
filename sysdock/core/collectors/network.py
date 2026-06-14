"""Network collector — per-NIC throughput via delta sampling.

Per-interface byte counters are converted to per-second send/receive rates using
elapsed monotonic time. Interface up/down state and addresses are read each tick
(cheap) but could be cached later if profiling shows it matters.
"""

from __future__ import annotations

import socket
import time
from dataclasses import dataclass, field

from sysdock.core.logging import get_logger

try:
    import psutil
except ImportError:  # pragma: no cover
    psutil = None

log = get_logger(__name__)


@dataclass
class NicSample:
    name: str
    is_up: bool = False
    addresses: list[str] = field(default_factory=list)
    bytes_sent: int = 0
    bytes_recv: int = 0
    tx_bytes_per_s: float = 0.0
    rx_bytes_per_s: float = 0.0


@dataclass
class NetworkSample:
    interfaces: list[NicSample] = field(default_factory=list)


class NetworkCollector:
    def __init__(self) -> None:
        # name -> (ts, bytes_sent, bytes_recv)
        self._prev: dict[str, tuple[float, int, int]] = {}

    def _addresses(self) -> dict[str, list[str]]:
        result: dict[str, list[str]] = {}
        if psutil is None:
            return result
        try:
            for name, addrs in psutil.net_if_addrs().items():
                ips: list[str] = []
                for addr in addrs:
                    if addr.family in (socket.AF_INET, socket.AF_INET6):
                        ips.append(addr.address)
                result[name] = ips
        except Exception as exc:  # pragma: no cover
            log.debug("net_if_addrs failed: %s", exc)
        return result

    def _up_states(self) -> dict[str, bool]:
        result: dict[str, bool] = {}
        if psutil is None:
            return result
        try:
            for name, stats in psutil.net_if_stats().items():
                result[name] = bool(stats.isup)
        except Exception as exc:  # pragma: no cover
            log.debug("net_if_stats failed: %s", exc)
        return result

    def collect(self) -> NetworkSample:
        if psutil is None:  # pragma: no cover
            return NetworkSample()
        try:
            per_nic = psutil.net_io_counters(pernic=True)
        except Exception as exc:
            log.debug("net_io_counters failed: %s", exc)
            return NetworkSample()

        addresses = self._addresses()
        up_states = self._up_states()
        now = time.monotonic()
        interfaces: list[NicSample] = []

        for name, counters in per_nic.items():
            sent = int(counters.bytes_sent)
            recv = int(counters.bytes_recv)
            tx_rate = rx_rate = 0.0
            prev = self._prev.get(name)
            if prev is not None:
                prev_ts, prev_sent, prev_recv = prev
                dt = now - prev_ts
                if dt > 0:
                    tx_rate = max(0.0, (sent - prev_sent) / dt)
                    rx_rate = max(0.0, (recv - prev_recv) / dt)
            self._prev[name] = (now, sent, recv)
            interfaces.append(
                NicSample(
                    name=name,
                    is_up=up_states.get(name, False),
                    addresses=addresses.get(name, []),
                    bytes_sent=sent,
                    bytes_recv=recv,
                    tx_bytes_per_s=round(tx_rate, 1),
                    rx_bytes_per_s=round(rx_rate, 1),
                )
            )

        # Drop stale interfaces that disappeared, so state can't grow unbounded.
        live = set(per_nic.keys())
        self._prev = {k: v for k, v in self._prev.items() if k in live}

        interfaces.sort(key=lambda nic: nic.name)
        return NetworkSample(interfaces=interfaces)
