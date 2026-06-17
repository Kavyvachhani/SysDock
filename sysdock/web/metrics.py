"""Optional Prometheus-format text exposition.

This is a dependency-free convenience: it renders the shared snapshot in the
Prometheus text format so the metrics *can* be scraped if you want. SysDock does
not depend on Prometheus — the built-in dashboard is fully self-contained.
"""

from __future__ import annotations

from sysdock.core.snapshot import Snapshot

_PREFIX = "sysdock"


def _line(name: str, value: float, labels: dict[str, str] | None = None) -> str:
    if labels:
        label_str = ",".join(f'{k}="{_escape(v)}"' for k, v in labels.items())
        return f"{_PREFIX}_{name}{{{label_str}}} {value}"
    return f"{_PREFIX}_{name} {value}"


def _escape(value: str) -> str:
    return value.replace("\\", "\\\\").replace('"', '\\"').replace("\n", " ")


def render_metrics(snap: Snapshot) -> str:
    """Render a snapshot as Prometheus text exposition."""
    out: list[str] = []

    out.append("# HELP sysdock_cpu_percent Total CPU utilisation percent.")
    out.append("# TYPE sysdock_cpu_percent gauge")
    out.append(_line("cpu_percent", snap.cpu.total_percent))
    for i, core in enumerate(snap.cpu.per_core_percent):
        out.append(_line("cpu_core_percent", core, {"core": str(i)}))

    out.append("# HELP sysdock_memory_percent Memory utilisation percent.")
    out.append("# TYPE sysdock_memory_percent gauge")
    out.append(_line("memory_percent", snap.memory.percent))
    out.append(_line("memory_used_bytes", snap.memory.used))
    out.append(_line("memory_total_bytes", snap.memory.total))
    out.append(_line("swap_percent", snap.memory.swap_percent))

    out.append("# TYPE sysdock_disk_percent gauge")
    for part in snap.disk.partitions:
        labels = {"mount": part.mountpoint}
        out.append(_line("disk_percent", part.percent, labels))
        out.append(_line("disk_used_bytes", part.used, labels))
        out.append(_line("disk_total_bytes", part.total, labels))

    out.append("# TYPE sysdock_net_bytes_per_second gauge")
    for nic in snap.network.interfaces:
        out.append(_line("net_rx_bytes_per_second", nic.rx_bytes_per_s, {"iface": nic.name}))
        out.append(_line("net_tx_bytes_per_second", nic.tx_bytes_per_s, {"iface": nic.name}))

    out.append("# TYPE sysdock_processes_total gauge")
    out.append(_line("processes_total", snap.processes.count))

    if snap.gpu.available:
        out.append("# TYPE sysdock_gpu_util_percent gauge")
        for dev in snap.gpu.devices:
            labels = {"vendor": dev.vendor, "index": str(dev.index)}
            if dev.util_percent is not None:
                out.append(_line("gpu_util_percent", dev.util_percent, labels))
            if dev.mem_used is not None:
                out.append(_line("gpu_mem_used_bytes", dev.mem_used, labels))
            if dev.temp_c is not None:
                out.append(_line("gpu_temp_celsius", dev.temp_c, labels))

    # Firewall as a 0/1 gauge where known.
    fw = snap.security.firewall
    if fw.available and fw.enabled is not None:
        out.append("# TYPE sysdock_firewall_enabled gauge")
        out.append(_line("firewall_enabled", 1 if fw.enabled else 0, {"backend": fw.backend}))
    if snap.security.open_ports.available:
        out.append(_line("open_ports_total", len(snap.security.open_ports.ports)))

    return "\n".join(out) + "\n"
