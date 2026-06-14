"""Open/listening ports — portable via psutil, no subprocess.

Lists TCP sockets in LISTEN state plus bound UDP sockets, with the owning
process where the OS lets us see it. Without elevation some OSes hide the PID of
other users' sockets; we degrade to listing the port with an empty process name
rather than failing.
"""

from __future__ import annotations

from sysdock.core.logging import get_logger
from sysdock.core.security.schema import OpenPort, OpenPorts

try:
    import psutil
except ImportError:  # pragma: no cover
    psutil = None

log = get_logger(__name__)


def _proto_name(family: int, type_: int) -> str:
    import socket

    base = "tcp" if type_ == socket.SOCK_STREAM else "udp"
    return base + ("6" if family == socket.AF_INET6 else "")


def collect_open_ports() -> OpenPorts:
    if psutil is None:  # pragma: no cover
        return OpenPorts(available=False, reason="psutil unavailable")

    import socket

    try:
        conns = psutil.net_connections(kind="inet")
    except (psutil.AccessDenied, PermissionError):
        return OpenPorts(available=False, reason="insufficient privileges to enumerate sockets")
    except Exception as exc:
        log.debug("net_connections failed: %s", exc)
        return OpenPorts(available=False, reason=str(exc))

    name_cache: dict[int, str] = {}

    def _name(pid: int | None) -> str:
        if not pid:
            return ""
        if pid in name_cache:
            return name_cache[pid]
        name = ""
        try:
            name = psutil.Process(pid).name()
        except (psutil.NoSuchProcess, psutil.AccessDenied, Exception):
            name = ""
        name_cache[pid] = name
        return name

    ports: list[OpenPort] = []
    for conn in conns:
        try:
            is_tcp = conn.type == socket.SOCK_STREAM
            # TCP: only LISTEN sockets. UDP: any socket with a local bind.
            if is_tcp and conn.status != psutil.CONN_LISTEN:
                continue
            if not conn.laddr:
                continue
            ports.append(
                OpenPort(
                    proto=_proto_name(conn.family, conn.type),
                    address=conn.laddr.ip,
                    port=int(conn.laddr.port),
                    pid=conn.pid,
                    process=_name(conn.pid),
                )
            )
        except Exception as exc:  # pragma: no cover - defensive per-row
            log.debug("port row skipped: %s", exc)
            continue

    ports.sort(key=lambda p: (p.port, p.proto))
    return OpenPorts(available=True, ports=ports)
