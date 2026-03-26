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
import logging
import os
import subprocess
import sys

import click
from rich.console import Console
from rich.panel import Panel
from rich.table import Table
from rich.text import Text
from rich import box

console = Console()

TOOL_NAME = "SysDock"
VERSION   = "1.4.6"

logging.basicConfig(
    level=logging.INFO,
    format="%(asctime)s  %(levelname)-8s  %(message)s",
    datefmt="%H:%M:%S",
)


# ─── CLI group ────────────────────────────────────────────────────────────────

@click.group(invoke_without_command=True)
@click.version_option(VERSION, prog_name=TOOL_NAME)
@click.pass_context
def cli(ctx):
    """
    \b
    SysDock — Linux / EC2 monitoring agent with live Docker metrics.
    Type 'sysdock' to open the dashboard, or 'sysdock COMMAND --help'.
    """
    # If no subcommand given, auto-launch the dashboard (like htop)
    if ctx.invoked_subcommand is None:
        from sysdock.display.dashboard import run_dashboard
        run_dashboard()


# ─── dash ─────────────────────────────────────────────────────────────────────

@cli.command()
@click.option("--refresh", default=3.0, show_default=True,
              help="Refresh interval in seconds (min 2.0)")
def dash(refresh):
    """Open the live terminal dashboard. Press Ctrl+C to exit."""
    from sysdock.display.dashboard import run_dashboard
    run_dashboard(refresh=refresh)


# ─── start ────────────────────────────────────────────────────────────────────

@cli.command()
@click.option("--host",    default="0.0.0.0", show_default=True, help="Bind address")
@click.option("--port",    default=5010,       show_default=True, help="Port to listen on")
@click.option("--verbose", is_flag=True,       help="Debug logging")
def start(host, port, verbose):
    """Start the metrics HTTP server on PORT."""
    if verbose:
        logging.getLogger().setLevel(logging.DEBUG)

    console.print(Panel.fit(
        "[bold cyan]{tool}[/bold cyan]\n"
        "[dim]Metrics server starting on "
        "[green]http://{host}:{port}/[/green][/dim]\n"
        "[dim]Press Ctrl+C to stop[/dim]".format(tool=TOOL_NAME, host=host, port=port),
        border_style="cyan",
    ))
    from sysdock.server import run_server
    run_server(host=host, port=port)


# ─── status ───────────────────────────────────────────────────────────────────

@cli.command()
@click.option("--json", "as_json", is_flag=True, help="Raw JSON output")
@click.option("--section",
              type=click.Choice(["system", "disk", "processes", "network", "docker", "security", "all"]),
              default="all", show_default=True)
def status(as_json, section):
    """Print a one-shot status snapshot to the terminal."""
    from sysdock.collectors import (
        system as _sys, disk as _disk, processes as _proc,
        network as _net, docker_collector as _docker, security as _sec,
    )
    all_collectors = {
        "system": _sys, "disk": _disk, "processes": _proc,
        "network": _net, "docker": _docker, "security": _sec,
    }
    targets = all_collectors if section == "all" else {section: all_collectors[section]}

    data = {}
    with console.status("[bold cyan]Collecting metrics...[/bold cyan]"):
        for key, mod in targets.items():
            try:
                data[key] = mod.collect_all()
            except Exception as e:
                data[key] = {"error": str(e)}

    if as_json:
        click.echo(json.dumps(data, indent=2, default=str))
        return

    _print_rich(data)


def _pct_color(v):
    if v is None: return Text("?", style="dim")
    v = float(v)
    style = "bold red" if v >= 90 else "bold yellow" if v >= 70 else "bold green"
    return Text("{:.1f}%".format(v), style=style)


def _mb(mb):
    if mb is None: return "?"
    mb = float(mb)
    return "{:.2f}G".format(mb / 1024) if mb >= 1024 else "{:.0f}M".format(mb)


def _print_rich(data):
    if "system" in data:
        s = data["system"]
        t = Table(box=box.ROUNDED, title="System", title_style="bold cyan", show_header=False)
        t.add_column("Key",   style="dim", width=18)
        t.add_column("Value")
        h, cpu, mem, load, up = (
            s.get("hostname", {}), s.get("cpu", {}),
            s.get("memory", {}),   s.get("load", {}), s.get("uptime", {}),
        )
        t.add_row("Hostname",  Text(h.get("hostname", "?"), style="bold"))
        t.add_row("OS",        h.get("os", "?"))
        t.add_row("Kernel",    h.get("kernel", "?"))
        t.add_row("Arch",      h.get("arch", "?"))
        t.add_row("Uptime",    up.get("uptime_human", "?"))
        t.add_row("Load avg",  "{} / {} / {}".format(
                  load.get("load1"), load.get("load5"), load.get("load15")))
        t.add_row("CPU",       _pct_color(cpu.get("usage_total")))
        t.add_row("CPU cores", "{} logical / {} physical".format(
                  cpu.get("logical_cores"), cpu.get("physical_cores")))
        t.add_row("RAM used",  "{} of {}  ({})".format(
                  _mb(mem.get("used_mb")), _mb(mem.get("total_mb")),
                  _pct_color(mem.get("percent"))))
        t.add_row("RAM avail", _mb(mem.get("available_mb")))
        t.add_row("Swap",      _pct_color(mem.get("swap_percent")))
        console.print(t)

    if "disk" in data:
        t = Table(box=box.ROUNDED, title="Disk", title_style="bold yellow")
        t.add_column("Mount",  style="cyan")
        t.add_column("Device", style="dim")
        t.add_column("FS",     style="dim")
        t.add_column("Used",   justify="right")
        t.add_column("Free",   justify="right")
        t.add_column("Total",  justify="right")
        t.add_column("%",      justify="right")
        for p in data["disk"].get("partitions", []):
            pct = p.get("percent", 0)
            col = "bold red" if pct >= 90 else "bold yellow" if pct >= 75 else "bold green"
            t.add_row(p["mountpoint"], p["device"][-20:], p["fstype"],
                      "{:.1f}G".format(p["used_gb"]),  "{:.1f}G".format(p["free_gb"]),
                      "{:.1f}G".format(p["total_gb"]), Text("{:.0f}%".format(pct), style=col))
        console.print(t)

    if "network" in data:
        t = Table(box=box.ROUNDED, title="Network", title_style="bold green")
        t.add_column("Interface", style="cyan")
        t.add_column("Status")
        t.add_column("IP")
        t.add_column("RX MB/s", justify="right")
        t.add_column("TX MB/s", justify="right")
        for iface in data["network"].get("interfaces", []):
            ips = ", ".join(a["address"] for a in iface.get("addresses", [])
                           if a.get("type") == "ipv4")
            up  = iface.get("is_up", False)
            t.add_row(
                iface["interface"],
                Text("UP",   style="bold green") if up else Text("DOWN", style="bold red"),
                ips or "—",
                "{:.3f}".format(iface.get("rx_mb_s", 0)),
                "{:.3f}".format(iface.get("tx_mb_s", 0)),
            )
        console.print(t)

    if "processes" in data:
        procs = data["processes"].get("top_by_cpu", [])[:12]
        t = Table(box=box.ROUNDED, title="Top Processes (CPU)", title_style="bold blue")
        t.add_column("User",    width=12)
        t.add_column("CPU%",    justify="right")
        t.add_column("MEM%",    justify="right")
        t.add_column("RSS",     justify="right")
        t.add_column("THR",     justify="right")
        t.add_column("Command")
        for p in procs:
            t.add_row(
                (p.get("user") or "?")[:12],
                _pct_color(p["cpu_pct"]),
                _pct_color(p["mem_pct"]),
                "{:.0f}M".format(p.get("rss_mb", 0)),
                str(p.get("threads", 0)),
                (p.get("cmd") or p.get("name", "?"))[:55],
            )
        console.print(t)

    if "docker" in data:
        d = data["docker"]
        if d.get("available"):
            t = Table(box=box.ROUNDED, title="Docker Containers", title_style="bold cyan")
            t.add_column("Name",  style="cyan")
            t.add_column("Image", style="dim")
            t.add_column("State")
            t.add_column("CPU%",  justify="right")
            t.add_column("MEM%",  justify="right")
            t.add_column("MEM",   justify="right")
            for c in d.get("containers", []):
                state  = c.get("state") or c.get("status", "?")
                is_run = (state == "running")
                stats  = c.get("stats") or {}
                t.add_row(
                    c.get("name", "?")[:28],
                    c.get("image", "?")[:28],
                    Text(state, style="bold green" if is_run else "dim"),
                    _pct_color(stats.get("cpu_pct")) if is_run else Text("—", "dim"),
                    _pct_color(stats.get("mem_pct")) if is_run else Text("—", "dim"),
                    _mb(stats.get("mem_used_mb"))    if is_run else Text("—", "dim"),
                )
            console.print(t)

            # Also print images if available
            images = d.get("images", [])
            if images:
                ti = Table(box=box.ROUNDED, title="Docker Images", title_style="bold cyan")
                ti.add_column("ID",      style="dim")
                ti.add_column("Tags",    style="cyan")
                ti.add_column("Size",    justify="right")
                ti.add_column("Created", style="dim")
                for img in images[:15]:
                    tags = ", ".join(img.get("tags") or ["<none>"])
                    size = "{:.0f}M".format(img["size_mb"]) if img.get("size_mb") else img.get("size", "?")
                    ti.add_row(img.get("id", "?"), tags, size, img.get("created", "?")[:10])
                console.print(ti)
        else:
            console.print("[dim]Docker: {} [/dim]".format(d.get("error", "not available")))


# ─── check ────────────────────────────────────────────────────────────────────

@cli.command()
def check():
    """Verify all dependencies and system capabilities."""
    checks = [
        ("Python ≥ 3.6",    lambda: "{}.{}.{}".format(*sys.version_info[:3])),
        ("psutil",          lambda: __import__("psutil").__version__),
        ("rich",            lambda: __import__("rich").__version__),
        ("click",           lambda: __import__("click").__version__),
        ("docker-py (opt)", lambda: __import__("docker").__version__),
        ("/proc filesystem",lambda: open("/proc/cpuinfo").read(1) and "present"),
        ("df command",      lambda: subprocess.run(["df", "--version"], capture_output=True).returncode == 0 and "ok"),
        ("ss command",      lambda: subprocess.run(["ss", "--version"], capture_output=True).returncode == 0 and "ok" if os.name != 'nt' else "N/A on Windows"),
        ("Docker daemon",   lambda: subprocess.run(["docker", "info"], capture_output=True, timeout=4).returncode == 0 and "running"),
        ("systemd",         lambda: os.path.exists("/run/systemd") and "present" if os.name != 'nt' else "N/A on Windows"),
        ("fail2ban",        lambda: subprocess.run(["fail2ban-client", "--version"], capture_output=True).returncode == 0 and "installed" if os.name != 'nt' else "N/A on Windows"),
    ]

    t = Table(box=box.ROUNDED, title="{} — Dependency Check".format(TOOL_NAME),
              title_style="bold cyan")
    t.add_column("Component", style="bold", width=22)
    t.add_column("Status",    justify="center", width=12)
    t.add_column("Detail")

    for name, fn in checks:
        try:
            detail = fn()
            t.add_row(name, Text("✓  OK",   style="bold green"),  str(detail) if detail is not True else "")
        except Exception as e:
            t.add_row(name, Text("✗  MISS", style="dim yellow"), str(e)[:60])

    console.print(t)


def _get_bin_path():
    if getattr(sys, 'frozen', False):
        return sys.executable
    if os.name == 'nt':
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
    is_windows = (os.name == 'nt')
    is_mac = (sys.platform == 'darwin')
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
    is_windows = (os.name == 'nt')
    is_mac = (sys.platform == 'darwin')

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
            cmd = f'schtasks /create /tn SysDock /tr "\\"{bin_path}\\" start --host {host} --port {port}" /sc onstart /ru SYSTEM /rl HIGHEST /f'
            subprocess.run(cmd, shell=True, check=True, capture_output=True)
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

        console.print(Panel.fit(
            f"[bold green]✓  Installed and started[/bold green]\n\n"
            f"  Service : {svc_name}\n"
            f"  Port    : {port}\n\n"
            f"  [dim]Run 'sysdock uninstall' to remove.[/dim]\n\n"
            f"[yellow]⚠  Open port {port} only from your monitoring server[/yellow]",
            title="SysDock Installation Complete", border_style="green",
        ))

    except Exception as e:
        console.print(f"[red]Failed to install service: {e}[/red]")
        sys.exit(1)


# ─── uninstall ────────────────────────────────────────────────────────────────

@cli.command()
def uninstall():
    """Remove the SysDock background service (requires admin/root)."""
    is_windows = (os.name == 'nt')
    is_mac = (sys.platform == 'darwin')

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
                lnk = os.path.expandvars(r"%APPDATA%\Microsoft\Windows\Start Menu\Programs\SysDock.lnk")
                if os.path.exists(lnk): os.remove(lnk)
            elif is_mac:
                for app_path in [
                    os.path.join(home, "Applications", "SysDock.app"),
                    "/Applications/SysDock.app"
                ]:
                    if os.path.exists(app_path):
                        import shutil
                        shutil.rmtree(app_path)
            else:
                desk = os.path.join(home, ".local", "share", "applications", "sysdock.desktop")
                if os.path.exists(desk): os.remove(desk)
        except Exception:
            pass
            
        console.print(Panel.fit(
            "[bold green]✓  SysDock service and shortcuts removed successfully[/bold green]\n\n"
            "[dim]To completely remove the package, run as your normal user:[/dim]\n"
            "  - pipx uninstall sysdock (if installed via pipx)\n"
            "  - or simply delete the executable file.",
            title="SysDock Uninstall", border_style="green"
        ))
    except Exception as e:
        console.print(f"[red]Failed to uninstall service: {e}[/red]")
        sys.exit(1)

def main():
    cli()


if __name__ == "__main__":
    main()
