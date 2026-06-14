"""
SysDock CLI.

Commands
--------
sysdock             Open the live terminal dashboard (default — no subcommand needed)
sysdock dash        Live terminal dashboard (like htop)
sysdock start       Start the metrics HTTP server (port 5010)
sysdock status      One-shot status snapshot
sysdock check       Verify all dependencies
sysdock install     Install as systemd service
sysdock uninstall   Remove systemd service
"""

from __future__ import annotations

import json
import os
import subprocess
import sys

import click
from rich import box
from rich.console import Console
from rich.panel import Panel
from rich.table import Table
from rich.text import Text

from sysdock import __version__ as VERSION
from sysdock.core.errors import ExitCode, SysdockError
from sysdock.core.logging import get_logger, setup_logging

console = Console()
log = get_logger(__name__)

TOOL_NAME = "SysDock"


# ─── CLI group ────────────────────────────────────────────────────────────────


@click.group(invoke_without_command=True)
@click.version_option(VERSION, prog_name=TOOL_NAME)
@click.option(
    "--log-level",
    default="INFO",
    show_default=True,
    type=click.Choice(["DEBUG", "INFO", "WARNING", "ERROR", "CRITICAL"], case_sensitive=False),
    help="Logging verbosity.",
)
@click.option("--json-logs", is_flag=True, help="Emit logs as JSON, one object per line.")
@click.pass_context
def cli(ctx, log_level, json_logs):
    """
    \b
    SysDock — cross-platform monitoring agent with live Docker metrics.
    Type 'sysdock' to open the dashboard, or 'sysdock COMMAND --help'.
    """
    setup_logging(level=log_level, json_logs=json_logs)
    # If no subcommand given, auto-launch the dashboard (like htop)
    if ctx.invoked_subcommand is None:
        from sysdock.display.dashboard import run_dashboard

        run_dashboard()


# ─── dash ─────────────────────────────────────────────────────────────────────


@cli.command()
@click.option(
    "--refresh", default=3.0, show_default=True, help="Refresh interval in seconds (min 2.0)"
)
def dash(refresh):
    """Open the live terminal dashboard. Press Ctrl+C to exit."""
    from sysdock.display.dashboard import run_dashboard

    run_dashboard(refresh=refresh)


# ─── start ────────────────────────────────────────────────────────────────────


@cli.command()
@click.option("--host", default="0.0.0.0", show_default=True, help="Bind address")
@click.option("--port", default=5010, show_default=True, help="Port to listen on")
@click.option("--verbose", is_flag=True, help="Debug logging")
def start(host, port, verbose):
    """Start the metrics HTTP server on PORT."""
    if verbose:
        setup_logging(level="DEBUG")

    console.print(
        Panel.fit(
            f"[bold cyan]{TOOL_NAME}[/bold cyan]\n"
            "[dim]Metrics server starting on "
            f"[green]http://{host}:{port}/[/green][/dim]\n"
            "[dim]Press Ctrl+C to stop[/dim]",
            border_style="cyan",
        )
    )
    from sysdock.server import run_server

    run_server(host=host, port=port)


# ─── status ───────────────────────────────────────────────────────────────────


@cli.command()
@click.option("--json", "as_json", is_flag=True, help="Raw JSON output of the full snapshot.")
@click.option("--top", default=10, show_default=True, help="Number of top processes to show.")
@click.option("--no-docker", is_flag=True, help="Skip Docker collection.")
def status(as_json, top, no_docker):
    """Print a one-shot snapshot of the system from the shared core."""
    from sysdock.core.snapshot import SnapshotProvider

    provider = SnapshotProvider(top_n=max(1, top), enable_docker=not no_docker)
    snap = provider.get(force=True)

    if as_json:
        click.echo(json.dumps(snap.to_dict(), indent=2, default=str))
        return

    _render_snapshot(snap, top)


def _fmt_bytes(num: float) -> str:
    value = float(num)
    for unit in ("B", "K", "M", "G", "T", "P"):
        if abs(value) < 1024.0:
            return f"{value:.0f}{unit}" if unit == "B" else f"{value:.1f}{unit}"
        value /= 1024.0
    return f"{value:.1f}E"


def _pct_color(value: float | None) -> Text:
    if value is None:
        return Text("?", style="dim")
    v = float(value)
    style = "bold red" if v >= 90 else "bold yellow" if v >= 70 else "bold green"
    return Text(f"{v:.1f}%", style=style)


def _bar(value: float | None, width: int = 16) -> Text:
    """A compact colored usage bar like htop/btop."""
    if value is None:
        return Text("─" * width, style="dim")
    v = max(0.0, min(100.0, float(value)))
    filled = int(round(v / 100.0 * width))
    color = "red" if v >= 90 else "yellow" if v >= 70 else "green"
    bar = Text()
    bar.append("█" * filled, style=color)
    bar.append("░" * (width - filled), style="dim")
    return bar


def _core_cell(index: int, pct: float) -> Text:
    cell = Text()
    cell.append(f"{index:>2} ", style="dim")
    cell.append_text(_bar(pct, width=8))
    cell.append(f" {pct:3.0f}%", style="dim")
    return cell


def _per_core_bars(per_core: list[float], columns: int = 4) -> Table:
    """Render per-core CPU as an aligned grid of small bars."""
    grid = Table.grid(padding=(0, 2))
    for _ in range(columns):
        grid.add_column()
    row: list[Text] = []
    for i, pct in enumerate(per_core):
        row.append(_core_cell(i, pct))
        if len(row) == columns:
            grid.add_row(*row)
            row = []
    if row:
        grid.add_row(*(row + [Text("")] * (columns - len(row))))
    return grid


def _render_snapshot(snap, top: int) -> None:
    host, cpu, mem = snap.host, snap.cpu, snap.memory

    info = Table.grid(padding=(0, 2))
    info.add_column(style="dim")
    info.add_column()
    info.add_row("Host", Text(host.hostname, style="bold"))
    info.add_row("OS", f"{host.os} ({host.arch})")
    info.add_row("Uptime", host.uptime_human)
    if cpu.load_avg:
        info.add_row("Load", " / ".join(f"{x:.2f}" for x in cpu.load_avg))
    info.add_row(
        "CPU",
        Text.assemble(
            _pct_color(cpu.total_percent),
            Text(f"  ({cpu.logical_cores} cores) {cpu.model}", style="dim"),
        ),
    )
    info.add_row(
        "Memory",
        Text.assemble(
            _pct_color(mem.percent),
            Text(f"  {_fmt_bytes(mem.used)} / {_fmt_bytes(mem.total)}", style="dim"),
        ),
    )
    if mem.swap_total:
        info.add_row("Swap", _pct_color(mem.swap_percent))
    info.add_row("Mem", _bar(mem.percent, width=30))
    console.print(Panel(info, title="SysDock — System", border_style="cyan", title_align="left"))

    if cpu.per_core_percent:
        console.print(
            Panel(
                _per_core_bars(cpu.per_core_percent),
                title="Per-core CPU",
                border_style="cyan",
                title_align="left",
            )
        )

    if snap.disk.partitions:
        dt = Table(box=box.ROUNDED, title="Disks", title_style="bold yellow")
        dt.add_column("Mount", style="cyan")
        dt.add_column("FS", style="dim")
        dt.add_column("Used", justify="right")
        dt.add_column("Total", justify="right")
        dt.add_column("%", justify="right")
        for p in snap.disk.partitions:
            dt.add_row(
                p.mountpoint,
                p.fstype,
                _fmt_bytes(p.used),
                _fmt_bytes(p.total),
                _pct_color(p.percent),
            )
        console.print(dt)

    up_nics = [
        n
        for n in snap.network.interfaces
        if n.is_up and (n.rx_bytes_per_s or n.tx_bytes_per_s or n.addresses)
    ]
    if up_nics:
        nt = Table(box=box.ROUNDED, title="Network", title_style="bold green")
        nt.add_column("Interface", style="cyan")
        nt.add_column("IP")
        nt.add_column("RX/s", justify="right")
        nt.add_column("TX/s", justify="right")
        for n in up_nics:
            nt.add_row(
                n.name,
                ", ".join(n.addresses) or "—",
                _fmt_bytes(n.rx_bytes_per_s) + "/s",
                _fmt_bytes(n.tx_bytes_per_s) + "/s",
            )
        console.print(nt)

    if snap.processes.top_by_cpu:
        pt = Table(
            box=box.ROUNDED,
            title=f"Top {min(top, len(snap.processes.top_by_cpu))} processes by CPU "
            f"({snap.processes.count} total)",
            title_style="bold blue",
        )
        pt.add_column("PID", justify="right", style="dim")
        pt.add_column("User", width=12)
        pt.add_column("CPU%", justify="right")
        pt.add_column("MEM%", justify="right")
        pt.add_column("RSS", justify="right")
        pt.add_column("Name")
        for proc_info in snap.processes.top_by_cpu[:top]:
            pt.add_row(
                str(proc_info.pid),
                (proc_info.username or "?")[:12],
                _pct_color(proc_info.cpu_percent),
                _pct_color(proc_info.memory_percent),
                _fmt_bytes(proc_info.rss),
                proc_info.name[:40],
            )
        console.print(pt)

    if snap.docker.available:
        dk = Table(
            box=box.ROUNDED,
            title=f"Docker — {snap.docker.running}/{snap.docker.total} running",
            title_style="bold cyan",
        )
        dk.add_column("Name", style="cyan")
        dk.add_column("Image", style="dim")
        dk.add_column("Status")
        dk.add_column("CPU%", justify="right")
        dk.add_column("MEM", justify="right")
        for c in snap.docker.containers:
            running = c.status == "running"
            s = c.stats
            dk.add_row(
                c.name[:24],
                c.image[:28],
                Text(c.status, style="bold green" if running else "dim"),
                _pct_color(s.cpu_percent) if s else Text("—", style="dim"),
                _fmt_bytes(s.mem_used) if s else Text("—", style="dim"),
            )
        console.print(dk)
    elif snap.docker.reason and "disabled" not in snap.docker.reason:
        console.print(f"[dim]Docker: {snap.docker.reason}[/dim]")

    _render_gpu(snap.gpu)
    _render_security(snap.security)

    if snap.errors:
        console.print(f"[yellow]Collector warnings:[/yellow] {', '.join(snap.errors)}")


def _render_gpu(gpu) -> None:
    # Absent vendor => hide the panel entirely (never an error).
    if not gpu.available or not gpu.devices:
        return
    gt = Table(box=box.ROUNDED, title="GPU", title_style="bold bright_magenta")
    gt.add_column("Vendor", style="dim")
    gt.add_column("Name")
    gt.add_column("Util", justify="right")
    gt.add_column("Load", justify="left")
    gt.add_column("VRAM", justify="right")
    gt.add_column("Temp", justify="right")
    gt.add_column("Power", justify="right")
    for d in gpu.devices:
        vram = "—"
        if d.mem_total:
            used = _fmt_bytes(d.mem_used) if d.mem_used is not None else "?"
            vram = f"{used} / {_fmt_bytes(d.mem_total)}"
        gt.add_row(
            d.vendor,
            d.name,
            _pct_color(d.util_percent),
            _bar(d.util_percent, width=12),
            vram,
            f"{d.temp_c:.0f}°C" if d.temp_c is not None else "—",
            f"{d.power_w:.0f}W" if d.power_w is not None else "—",
        )
    console.print(gt)


def _avail(available: bool, reason: str) -> Text:
    if available:
        return Text("available", style="bold green")
    return Text(f"unavailable — {reason}", style="dim")


def _render_security(sec) -> None:
    fw = sec.firewall
    grid = Table.grid(padding=(0, 2))
    grid.add_column(style="dim")
    grid.add_column()
    if fw.available:
        state = "enabled" if fw.enabled else "disabled" if fw.enabled is False else "unknown"
        style = "bold green" if fw.enabled else "bold red" if fw.enabled is False else "yellow"
        detail = fw.backend + (f", default {fw.default_policy}" if fw.default_policy else "")
        grid.add_row(
            "Firewall",
            Text.assemble(Text(state, style=style), Text(f"  ({detail})", style="dim")),
        )
    else:
        grid.add_row("Firewall", _avail(False, fw.reason))

    op = sec.open_ports
    if op.available:
        listening = ", ".join(sorted({f"{p.port}/{p.proto}" for p in op.ports})[:12]) or "none"
        grid.add_row("Open ports", Text(f"{len(op.ports)} listening: {listening}"))
    else:
        grid.add_row("Open ports", _avail(False, op.reason))

    fa = sec.failed_auth
    grid.add_row(
        "Failed auth",
        Text(f"{len(fa.events)} recent") if fa.available else _avail(False, fa.reason),
    )

    intr = sec.intrusion
    if intr.available:
        banned = sum(1 for b in intr.blocks if b.source)
        jails = len({b.jail for b in intr.blocks})
        grid.add_row("Intrusion", Text(f"{banned} banned across {jails} jail(s)"))
    else:
        grid.add_row("Intrusion", _avail(False, intr.reason))

    console.print(
        Panel(grid, title="SysDock — Security", border_style="magenta", title_align="left")
    )

    if fa.available and fa.events:
        at = Table(box=box.ROUNDED, title="Recent failed auth", title_style="bold magenta")
        at.add_column("When", style="dim")
        at.add_column("User")
        at.add_column("Source")
        for ev in fa.events[:8]:
            at.add_row(ev.timestamp or "?", ev.user or "?", ev.source or "?")
        console.print(at)


# ─── check ────────────────────────────────────────────────────────────────────


@cli.command()
@click.option("--json", "as_json", is_flag=True, help="Raw JSON output of detected capabilities.")
def check(as_json):
    """Report detected capabilities for this host and OS."""
    from sysdock.core import capabilities as caps_mod

    caps = caps_mod.detect()

    if as_json:
        click.echo(json.dumps(caps.to_dict(), indent=2, default=str))
        return

    header = Table.grid(padding=(0, 2))
    header.add_column(style="dim")
    header.add_column()
    header.add_row("Platform", Text(caps.platform, style="bold"))
    header.add_row("OS release", caps.os_release or "?")
    header.add_row("Architecture", caps.arch or "?")
    header.add_row("Python", caps.python_version)
    header.add_row(
        "Elevated", Text("yes", style="yellow") if caps.elevated else Text("no", style="green")
    )
    console.print(
        Panel(header, title=f"{TOOL_NAME} — Capabilities", border_style="cyan", title_align="left")
    )

    groups = [
        ("Metrics", caps.metrics),
        ("Firewall", caps.firewall),
        ("Intrusion", caps.intrusion),
        ("Auth log", caps.auth_log),
        ("GPU", caps.gpu),
        ("Containers", caps.containers),
        ("Service manager", caps.service_manager),
    ]
    t = Table(box=box.ROUNDED, show_header=True, header_style="bold")
    t.add_column("Group", style="bold cyan", width=16)
    t.add_column("Capability", width=20)
    t.add_column("Status", justify="center", width=14)
    t.add_column("Detail", style="dim")
    for group_name, items in groups:
        if not items:
            t.add_row(
                group_name,
                Text("—", style="dim"),
                Text("n/a here", style="dim"),
                "not applicable on this OS",
            )
            continue
        for i, cap in enumerate(items):
            status = (
                Text("✓ available", style="bold green")
                if cap.available
                else Text("✗ unavailable", style="dim yellow")
            )
            t.add_row(group_name if i == 0 else "", cap.name, status, cap.detail)
    console.print(t)


def _get_bin_path():
    if getattr(sys, "frozen", False):
        return sys.executable
    if os.name == "nt":
        return sys.executable + " -m sysdock"
    bin_path = subprocess.run(["which", "sysdock"], capture_output=True, text=True).stdout.strip()
    if not bin_path:
        return sys.executable + " -m sysdock"
    return bin_path


def _get_user_home():
    """Get the real user's home directory even if running via sudo"""
    sudo_user = os.environ.get("SUDO_USER")
    if sudo_user:
        return os.path.expanduser(f"~{sudo_user}")
    return os.path.expanduser("~")


# ─── install-desktop ──────────────────────────────────────────────────────────


@cli.command(name="install-desktop")
def install_desktop():
    """Create a desktop/app menu shortcut for SysDock (run without sudo!)."""
    is_windows = os.name == "nt"
    is_mac = sys.platform == "darwin"
    bin_path = _get_bin_path()

    try:
        if is_windows:
            script = f'''
$WshShell = New-Object -comObject WScript.Shell
$Shortcut = $WshShell.CreateShortcut("$env:APPDATA\\Microsoft\\Windows\\Start Menu\\Programs\\SysDock.lnk")
$Shortcut.TargetPath = "{sys.executable}"
$Shortcut.Arguments = "-m sysdock dash"
$Shortcut.WindowStyle = 1
$Shortcut.IconLocation = "{sys.executable},0"
$Shortcut.Description = "SysDock Monitoring Agent"
$Shortcut.Save()
'''
            subprocess.run(["powershell", "-Command", script], capture_output=True, check=True)
            console.print("[bold green]✓  Created Start Menu shortcut: SysDock[/bold green]")

        elif is_mac:
            app_dir = os.path.join(_get_user_home(), "Applications", "SysDock.app")
            os.makedirs(os.path.join(app_dir, "Contents", "MacOS"), exist_ok=True)
            os.makedirs(os.path.join(app_dir, "Contents", "Resources"), exist_ok=True)

            plist_path = os.path.join(app_dir, "Contents", "Info.plist")
            with open(plist_path, "w") as f:
                f.write("""<?xml version="1.0" encoding="UTF-8"?>
<!DOCTYPE plist PUBLIC "-//Apple//DTD PLIST 1.0//EN" "http://www.apple.com/DTDs/PropertyList-1.0.dtd">
<plist version="1.0">
<dict>
    <key>CFBundleExecutable</key>
    <string>SysDock</string>
    <key>CFBundleIdentifier</key>
    <string>io.sysdock.app</string>
    <key>CFBundleName</key>
    <string>SysDock</string>
    <key>CFBundlePackageType</key>
    <string>APPL</string>
    <key>LSMinimumSystemVersion</key>
    <string>10.13</string>
</dict>
</plist>
""")

            script_path = os.path.join(app_dir, "Contents", "MacOS", "SysDock")
            with open(script_path, "w") as f:
                f.write(f'''#!/bin/bash
osascript -e 'tell application "Terminal" to do script "{bin_path} dash"' -e 'tell application "Terminal" to activate'
''')
            os.chmod(script_path, 0o755)
            console.print(f"[bold green]✓  Created App shortcut: {app_dir}[/bold green]")

        else:
            desktop_dir = os.path.join(_get_user_home(), ".local", "share", "applications")
            os.makedirs(desktop_dir, exist_ok=True)
            desktop_path = os.path.join(desktop_dir, "sysdock.desktop")

            with open(desktop_path, "w") as f:
                f.write(f"""[Desktop Entry]
Version=1.0
Name=SysDock
Comment=SysDock Monitoring Dashboard
Exec=x-terminal-emulator -e {bin_path} dash
Terminal=false
Type=Application
Categories=System;Monitor;
""")
            console.print(f"[bold green]✓  Created App menu shortcut: {desktop_path}[/bold green]")

    except Exception as e:
        console.print(f"[red]Failed to create shortcut: {e}[/red]")
        sys.exit(1)


# ─── install ──────────────────────────────────────────────────────────────────


@cli.command()
@click.option("--port", default=5010, show_default=True)
@click.option("--host", default="0.0.0.0", show_default=True)
def install(port, host):
    """Install SysDock as a background persistent service (requires admin/root)."""
    is_windows = os.name == "nt"
    is_mac = sys.platform == "darwin"

    if is_windows:
        import ctypes

        if ctypes.windll.shell32.IsUserAnAdmin() == 0:
            console.print("[red]Run as Administrator to install the service.[/red]")
            sys.exit(1)
    else:
        if os.geteuid() != 0:
            console.print("[red]Run as root: sudo sysdock install[/red]")
            sys.exit(1)

    bin_path = _get_bin_path()

    try:
        if is_windows:
            # No shell: the task command is passed to /tr as a single argv entry,
            # so host/port/bin_path are never interpreted by a shell.
            tr_value = f'"{bin_path}" start --host {host} --port {port}'
            subprocess.run(
                [
                    "schtasks",
                    "/create",
                    "/tn",
                    "SysDock",
                    "/tr",
                    tr_value,
                    "/sc",
                    "onstart",
                    "/ru",
                    "SYSTEM",
                    "/rl",
                    "HIGHEST",
                    "/f",
                ],
                check=True,
                capture_output=True,
            )
            subprocess.run(["schtasks", "/run", "/tn", "SysDock"], capture_output=True)
            svc_name = "Task Scheduler: SysDock"

        elif is_mac:
            plist = f"""<?xml version="1.0" encoding="UTF-8"?>
<!DOCTYPE plist PUBLIC "-//Apple//DTD PLIST 1.0//EN" "http://www.apple.com/DTDs/PropertyList-1.0.dtd">
<plist version="1.0">
<dict>
    <key>Label</key>
    <string>io.sysdock.agent</string>
    <key>ProgramArguments</key>
    <array>
        <string>{bin_path}</string>
        <string>start</string>
        <string>--host</string>
        <string>{host}</string>
        <string>--port</string>
        <string>{port}</string>
    </array>
    <key>RunAtLoad</key>
    <true/>
    <key>KeepAlive</key>
    <true/>
    <key>StandardErrorPath</key>
    <string>/var/log/sysdock.log</string>
    <key>StandardOutPath</key>
    <string>/var/log/sysdock.log</string>
</dict>
</plist>"""
            svc_path = "/Library/LaunchDaemons/io.sysdock.agent.plist"
            with open(svc_path, "w") as f:
                f.write(plist)
            subprocess.run(["launchctl", "unload", svc_path], capture_output=True)
            subprocess.run(["launchctl", "load", svc_path], check=True, capture_output=True)
            svc_name = "launchd: io.sysdock.agent"

        else:
            # Linux systemd
            svc = f"""[Unit]
Description=SysDock Monitoring Agent
After=network.target

[Service]
Type=simple
ExecStart={bin_path} start --host {host} --port {port}
Restart=always
RestartSec=10
StandardOutput=journal
StandardError=journal
Environment=PYTHONUNBUFFERED=1

[Install]
WantedBy=multi-user.target
"""
            svc_path = "/etc/systemd/system/sysdock.service"
            with open(svc_path, "w") as f:
                f.write(svc)

            for cmd in [
                ["systemctl", "daemon-reload"],
                ["systemctl", "enable", "sysdock"],
                ["systemctl", "restart", "sysdock"],
            ]:
                subprocess.run(cmd, check=False, capture_output=True)
            svc_name = "systemd: sysdock.service"

        console.print(
            Panel.fit(
                f"[bold green]✓  Installed and started[/bold green]\n\n"
                f"  Service : {svc_name}\n"
                f"  Port    : {port}\n\n"
                f"  [dim]Run 'sysdock uninstall' to remove.[/dim]\n\n"
                f"[yellow]⚠  Open port {port} only from your monitoring server[/yellow]",
                title="SysDock Installation Complete",
                border_style="green",
            )
        )

    except Exception as e:
        console.print(f"[red]Failed to install service: {e}[/red]")
        sys.exit(1)


# ─── uninstall ────────────────────────────────────────────────────────────────


@cli.command()
def uninstall():
    """Remove the SysDock background service (requires admin/root)."""
    is_windows = os.name == "nt"
    is_mac = sys.platform == "darwin"

    if is_windows:
        import ctypes

        if ctypes.windll.shell32.IsUserAnAdmin() == 0:
            console.print("[red]Run as Administrator to uninstall the service.[/red]")
            sys.exit(1)
    else:
        if os.geteuid() != 0:
            console.print("[red]Run as root: sudo sysdock uninstall[/red]")
            sys.exit(1)

    try:
        if is_windows:
            subprocess.run(["schtasks", "/end", "/tn", "SysDock"], capture_output=True)
            subprocess.run(["schtasks", "/delete", "/tn", "SysDock", "/f"], capture_output=True)
            subprocess.run(["taskkill", "/f", "/im", "SysDock.exe"], capture_output=True)
            subprocess.run(["taskkill", "/f", "/im", "sysdock.exe"], capture_output=True)

        elif is_mac:
            svc_path = "/Library/LaunchDaemons/io.sysdock.agent.plist"
            if os.path.exists(svc_path):
                subprocess.run(["launchctl", "unload", svc_path], capture_output=True)
                os.remove(svc_path)

        else:
            # Linux
            for cmd in [["systemctl", "stop", "sysdock"], ["systemctl", "disable", "sysdock"]]:
                subprocess.run(cmd, capture_output=True)

            svc_path = "/etc/systemd/system/sysdock.service"
            if os.path.exists(svc_path):
                os.remove(svc_path)
                subprocess.run(["systemctl", "daemon-reload"], capture_output=True)

        # Also remove desktop shortcuts
        try:
            home = _get_user_home()
            if is_windows:
                lnk = os.path.expandvars(
                    r"%APPDATA%\Microsoft\Windows\Start Menu\Programs\SysDock.lnk"
                )
                if os.path.exists(lnk):
                    os.remove(lnk)
            elif is_mac:
                for app_path in [
                    os.path.join(home, "Applications", "SysDock.app"),
                    "/Applications/SysDock.app",
                ]:
                    if os.path.exists(app_path):
                        import shutil

                        shutil.rmtree(app_path)
            else:
                desk = os.path.join(home, ".local", "share", "applications", "sysdock.desktop")
                if os.path.exists(desk):
                    os.remove(desk)
        except Exception:
            pass

        console.print(
            Panel.fit(
                "[bold green]✓  SysDock service and shortcuts removed successfully[/bold green]\n\n"
                "[dim]To completely remove the package, run as your normal user:[/dim]\n"
                "  - pipx uninstall sysdock (if installed via pipx)\n"
                "  - or simply delete the executable file.",
                title="SysDock Uninstall",
                border_style="green",
            )
        )
    except Exception as e:
        console.print(f"[red]Failed to uninstall service: {e}[/red]")
        sys.exit(1)


# ─── version ──────────────────────────────────────────────────────────────────


@cli.command()
@click.option("--json", "as_json", is_flag=True, help="Raw JSON output.")
def version(as_json):
    """Print the SysDock version."""
    if as_json:
        click.echo(json.dumps({"name": TOOL_NAME.lower(), "version": VERSION}))
    else:
        click.echo(f"{TOOL_NAME} {VERSION}")


# ─── error boundary ─────────────────────────────────────────────────────────--


def _render_error(message: str, *, hint: str | None = None) -> None:
    """Render a clean, user-facing error — never a traceback."""
    body = f"[bold red]Error:[/bold red] {message}"
    if hint:
        body += f"\n[dim]{hint}[/dim]"
    console.print(Panel.fit(body, border_style="red"))


def main(argv: list[str] | None = None) -> None:
    """CLI entry point and global error boundary.

    No unhandled exception ever reaches the user: deliberate SysDock errors
    render a clean message with the right exit code, Ctrl-C exits 130, and any
    unexpected exception is logged (with traceback at DEBUG) but shown to the
    user as a single friendly line.
    """
    # Ensure logging works even if we fail before the group callback configures it.
    setup_logging()
    try:
        cli.main(args=argv, standalone_mode=True)
    except SysdockError as exc:
        log.error("command failed", extra={"exit_code": int(exc.exit_code)})
        _render_error(exc.message, hint=exc.hint)
        sys.exit(int(exc.exit_code))
    except KeyboardInterrupt:
        console.print("\n[dim]Interrupted.[/dim]")
        sys.exit(int(ExitCode.INTERRUPTED))
    except SystemExit:
        raise  # normal click exit (success or its own handled errors)
    except Exception as exc:  # noqa: BLE001 - top-level boundary; nothing escapes
        # Message at ERROR; the full traceback only at DEBUG so it never lands
        # in front of the user by default (matches the --log-level DEBUG hint).
        log.error("unexpected error: %s", exc)
        log.debug("unexpected error traceback", exc_info=True)
        _render_error(
            f"An unexpected error occurred: {exc}",
            hint="Re-run with --log-level DEBUG for details, "
            "or report it at https://github.com/Kavyvachhani/SysDock/issues",
        )
        sys.exit(int(ExitCode.ERROR))


if __name__ == "__main__":
    main()
