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
VERSION   = "1.3.3"

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
        from infravision_agent.display.dashboard import run_dashboard
        run_dashboard()


# ─── dash ─────────────────────────────────────────────────────────────────────

@cli.command()
@click.option("--refresh", default=3.0, show_default=True,
              help="Refresh interval in seconds (min 2.0)")
def dash(refresh):
    """Open the live terminal dashboard. Press Ctrl+C to exit."""
    from infravision_agent.display.dashboard import run_dashboard
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
    from infravision_agent.server import run_server
    run_server(host=host, port=port)


# ─── status ───────────────────────────────────────────────────────────────────

@cli.command()
@click.option("--json", "as_json", is_flag=True, help="Raw JSON output")
@click.option("--section",
              type=click.Choice(["system", "disk", "processes", "network", "docker", "security", "all"]),
              default="all", show_default=True)
def status(as_json, section):
    """Print a one-shot status snapshot to the terminal."""
    from infravision_agent.collectors import (
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


# ─── install ──────────────────────────────────────────────────────────────────

@cli.command()
@click.option("--port", default=5010, show_default=True)
@click.option("--host", default="0.0.0.0", show_default=True)
def install(port, host):
    """Install SysDock as a systemd service (requires root)."""
    if os.name == 'nt':
        console.print("[red]Service installation is currently Linux-only.[/red]")
        sys.exit(1)

    if os.geteuid() != 0:
        console.print("[red]Run as root: sudo sysdock install[/red]")
        sys.exit(1)

    bin_path = subprocess.run(["which", "sysdock"], capture_output=True, text=True).stdout.strip()
    if not bin_path:
        bin_path = sys.executable + " -m infravision_agent"

    svc = (
        "[Unit]\n"
        "Description=SysDock Monitoring Agent\n"
        "After=network.target\n\n"
        "[Service]\n"
        "Type=simple\n"
        "ExecStart={bin} start --host {host} --port {port}\n"
        "Restart=always\n"
        "RestartSec=10\n"
        "StandardOutput=journal\n"
        "StandardError=journal\n"
        "Environment=PYTHONUNBUFFERED=1\n\n"
        "[Install]\n"
        "WantedBy=multi-user.target\n"
    ).format(bin=bin_path, host=host, port=port)

    svc_path = "/etc/systemd/system/sysdock.service"
    with open(svc_path, "w") as f:
        f.write(svc)

    for cmd in [
        ["systemctl", "daemon-reload"],
        ["systemctl", "enable",  "sysdock"],
        ["systemctl", "restart", "sysdock"],
    ]:
        subprocess.run(cmd, check=False)

    console.print(Panel.fit(
        "[bold green]✓  Installed and started[/bold green]\n\n"
        "  Service : sysdock\n"
        "  Port    : {port}\n\n"
        "  [dim]journalctl -u sysdock -f[/dim]\n"
        "  [dim]systemctl status sysdock[/dim]\n\n"
        "[yellow]⚠  Open port {port} only from your monitoring server[/yellow]".format(port=port),
        title="SysDock Installation Complete", border_style="green",
    ))


# ─── uninstall ────────────────────────────────────────────────────────────────

@cli.command()
def uninstall():
    """Remove the SysDock systemd service (requires root)."""
    if os.name == 'nt':
        console.print("[red]Service installation is currently Linux-only.[/red]")
        sys.exit(1)

    if os.geteuid() != 0:
        console.print("[red]Run as root to remove the service: sudo sysdock uninstall[/red]")
        sys.exit(1)
    
    for cmd in [["systemctl", "stop", "sysdock"], ["systemctl", "disable", "sysdock"]]:
        subprocess.run(cmd, capture_output=True)
    
    svc = "/etc/systemd/system/sysdock.service"
    if os.path.exists(svc):
        os.remove(svc)
        subprocess.run(["systemctl", "daemon-reload"])
        
    console.print(Panel.fit(
        "[bold green]✓  SysDock service removed successfully[/bold green]\n\n"
        "[dim]To completely remove the package, run as your normal user:[/dim]\n"
        "  pipx uninstall sysdock",
        title="SysDock Uninstall", border_style="green"
    ))

def main():
    cli()


if __name__ == "__main__":
    main()
