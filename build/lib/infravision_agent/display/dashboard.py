"""
SysDock — live Rich terminal dashboard (htop-style).
Updates every N seconds. Press Ctrl+C to exit.
Python 3.6+. All Linux distributions.
"""
from __future__ import annotations

import threading
import time
from datetime import datetime

from rich.console import Console
from rich.layout import Layout
from rich.live import Live
from rich.panel import Panel
from rich.table import Table
from rich.text import Text
from rich.align import Align
from rich.rule import Rule
from rich import box

from infravision_agent.collectors import (
    system as _sys, disk as _disk, processes as _proc,
    network as _net, docker_collector as _docker, security as _sec,
)

console = Console()

TOOL_NAME = "SysDock"
VERSION   = "1.1.0"


# ─── Colour helpers ──────────────────────────────────────────────────────────

def _pct_style(v, warn=70, crit=90):
    if v is None: return "dim white"
    v = float(v)
    if v >= crit: return "bold red"
    if v >= warn: return "bold yellow"
    return "bold green"


def _bar(pct, width=22, warn=70, crit=90):
    pct    = float(pct or 0)
    filled = int(pct / 100 * width)
    filled = min(filled, width)
    color  = _pct_style(pct, warn, crit)
    b = Text()
    b.append("[", style="dim")
    b.append("█" * filled,          style=color)
    b.append("░" * (width - filled), style="dim")
    b.append("]", style="dim")
    return b


def _mb(mb):
    if mb is None: return "?"
    mb = float(mb)
    if mb >= 1024:
        return "{:.2f}G".format(mb / 1024)
    return "{:.0f}M".format(mb)


def _fmt_bytes(b):
    """Format bytes to human-readable."""
    if b is None: return "?"
    b = float(b)
    for unit in ("B", "K", "M", "G", "T"):
        if b < 1024:
            return "{:.1f}{}".format(b, unit)
        b /= 1024
    return "{:.1f}P".format(b)


# ─── Panel builders ──────────────────────────────────────────────────────────

def _header(sys_d):
    h    = sys_d.get("hostname", {})
    up   = sys_d.get("uptime",   {})
    load = sys_d.get("load",     {})
    now  = datetime.now().strftime("%Y-%m-%d  %H:%M:%S")
    g = Table.grid(padding=(0, 3))
    g.add_column(); g.add_column(); g.add_column(); g.add_column(); g.add_column()
    g.add_row(
        Text("🖥  " + h.get("hostname", "?"),         style="bold cyan"),
        Text("📦 " + h.get("os", "?")[:30],           style="dim"),
        Text("⬆  " + up.get("uptime_human", "?"),     style="green"),
        Text("⚡ Load {}/{}/{}".format(
              load.get("load1","?"), load.get("load5","?"), load.get("load15","?")),
             style="yellow"),
        Text("🕐 " + now,                              style="dim"),
    )
    return Panel(
        g,
        title="[bold cyan]{} v{}[/bold cyan]".format(TOOL_NAME, VERSION),
        border_style="cyan", padding=(0, 1),
    )


def _cpu_panel(sys_d):
    cpu   = sys_d.get("cpu", {})
    total = float(cpu.get("usage_total") or 0)
    t = Table.grid(padding=(0, 1))
    t.add_column(width=5)
    t.add_column()
    t.add_column(width=7, justify="right")
    t.add_row(
        Text("ALL", style="bold"),
        _bar(total, 28),
        Text("{:.1f}%".format(total), style=_pct_style(total)),
    )
    for i, pct in enumerate(cpu.get("usage_per_core", [])):
        pct = float(pct or 0)
        t.add_row(
            Text("{:2d}".format(i), style="dim"),
            _bar(pct, 28),
            Text("{:.1f}%".format(pct), style=_pct_style(pct)),
        )
    freq = cpu.get("freq_mhz")
    freq_str = "{} MHz".format(freq) if freq else "? MHz"
    sub = "[dim]{} | {} logical, {} physical | {}[/dim]".format(
          cpu.get("model", "?")[:32],
          cpu.get("logical_cores", "?"),
          cpu.get("physical_cores", "?"),
          freq_str)
    return Panel(
        t,
        title="[bold]CPU[/bold]  [dim]user {:.1f}%  sys {:.1f}%  iowait {:.1f}%[/dim]".format(
              float(cpu.get("user_pct") or 0),
              float(cpu.get("system_pct") or 0),
              float(cpu.get("iowait_pct") or 0)),
        subtitle=sub, border_style="blue",
    )


def _mem_panel(sys_d):
    m = sys_d.get("memory", {})
    t = Table.grid(padding=(0, 1))
    t.add_column(width=5)
    t.add_column()
    t.add_column(width=26, justify="right")

    rp = float(m.get("percent") or 0)
    t.add_row(
        Text("RAM", style="bold"),
        _bar(rp, 22),
        Text("{} / {}  {:.1f}%".format(
            _mb(m.get("used_mb")), _mb(m.get("total_mb")), rp),
            style=_pct_style(rp)),
    )

    sp = float(m.get("swap_percent") or 0)
    t.add_row(
        Text("SWP", style="bold"),
        _bar(sp, 22, 50, 80),
        Text("{} / {}  {:.1f}%".format(
            _mb(m.get("swap_used_mb")), _mb(m.get("swap_total_mb")), sp),
            style=_pct_style(sp, 50, 80)),
    )

    sub = "[dim]avail {}  cached {}  buffers {}  free {}[/dim]".format(
          _mb(m.get("available_mb")),
          _mb(m.get("cached_mb")),
          _mb(m.get("buffers_mb")),
          _mb(m.get("free_mb")))
    return Panel(t, title="[bold]Memory[/bold]", subtitle=sub, border_style="magenta")


def _disk_panel(disk_d):
    t = Table(box=box.SIMPLE, show_header=True, header_style="bold dim",
              show_edge=False, padding=(0, 1))
    t.add_column("Mount",  style="cyan")
    t.add_column("Device", style="dim")
    t.add_column("FS",     style="dim")
    t.add_column("Bar")
    t.add_column("Used",   justify="right")
    t.add_column("Free",   justify="right")
    t.add_column("Total",  justify="right")
    t.add_column("%",      justify="right")
    for p in disk_d.get("partitions", []):
        pct = float(p.get("percent") or 0)
        t.add_row(
            p.get("mountpoint", "?"),
            p.get("device", "?")[-18:],
            p.get("fstype", "?"),
            _bar(pct, 10, 75, 90),
            "{:.1f}G".format(p.get("used_gb", 0)),
            "{:.1f}G".format(p.get("free_gb", 0)),
            "{:.1f}G".format(p.get("total_gb", 0)),
            Text("{:.0f}%".format(pct), style=_pct_style(pct, 75, 90)),
        )
    return Panel(t, title="[bold]Disk[/bold]", border_style="yellow")


def _net_panel(net_d):
    t = Table(box=box.SIMPLE, show_header=True, header_style="bold dim",
              show_edge=False, padding=(0, 1))
    t.add_column("Interface", style="cyan")
    t.add_column("Status")
    t.add_column("IP")
    t.add_column("↓ RX MB/s", justify="right")
    t.add_column("↑ TX MB/s", justify="right")
    t.add_column("Err↓",      justify="right", style="dim")
    t.add_column("Err↑",      justify="right", style="dim")
    for iface in net_d.get("interfaces", []):
        up  = iface.get("is_up", False)
        ips = ", ".join(a["address"] for a in iface.get("addresses", []) if a.get("type") == "ipv4")
        rx  = float(iface.get("rx_mb_s") or 0)
        tx  = float(iface.get("tx_mb_s") or 0)
        t.add_row(
            iface.get("interface", "?"),
            Text("● UP",   style="bold green") if up else Text("○ DOWN", style="dim red"),
            ips or "—",
            Text("{:.3f}".format(rx), style="cyan"  if rx > 0 else "dim"),
            Text("{:.3f}".format(tx), style="green" if tx > 0 else "dim"),
            str(iface.get("errors_in",  0)),
            str(iface.get("errors_out", 0)),
        )
    conns = net_d.get("connections", {})
    sub   = "[dim]estab {}  tw {}  listen {}  udp {}[/dim]".format(
            conns.get("established", 0), conns.get("time_wait", 0),
            conns.get("listen", 0),      conns.get("udp", 0))
    return Panel(t, title="[bold]Network[/bold]", subtitle=sub, border_style="green")


def _proc_panel(proc_d):
    procs   = proc_d.get("top_by_cpu", [])
    summary = proc_d.get("summary", {})
    t = Table(box=box.SIMPLE, show_header=True, header_style="bold dim",
              show_edge=False, padding=(0, 1))
    t.add_column("PID",  justify="right", width=7)
    t.add_column("User", width=10)
    t.add_column("S",    width=3)
    t.add_column("CPU%", justify="right", width=7)
    t.add_column("MEM%", justify="right", width=7)
    t.add_column("RSS",  justify="right", width=8)
    t.add_column("THR",  justify="right", width=5)
    t.add_column("Command")
    status_char = {
        "sleeping": "S", "running": "R", "zombie": "Z",
        "stopped": "T",  "disk-sleep": "D",
    }
    for p in procs[:15]:
        cpu = float(p.get("cpu_pct") or 0)
        mem = float(p.get("mem_pct") or 0)
        sc  = status_char.get(p.get("status", ""), "?")
        t.add_row(
            str(p["pid"]),
            (p.get("user") or "?")[:10],
            Text(sc, style="bold green" if sc == "R" else "dim"),
            Text("{:.1f}".format(cpu), style=_pct_style(cpu)),
            Text("{:.1f}".format(mem), style=_pct_style(mem)),
            _mb(p.get("rss_mb")),
            str(p.get("threads", 0)),
            (p.get("cmd") or p.get("name", "?"))[:50],
        )
    sub = "[dim]tasks {}  run {}  slp {}  zmb {}[/dim]".format(
          summary.get("total", 0), summary.get("running", 0),
          summary.get("sleeping", 0), summary.get("zombie", 0))
    return Panel(t, title="[bold]Processes[/bold] [dim](by CPU)[/dim]",
                 subtitle=sub, border_style="blue")


def _docker_panel(docker_d):
    if not docker_d.get("available"):
        err = docker_d.get("error", "Docker not available")
        return Panel(
            Align.center(Text("⊘  " + err, style="dim")),
            title="[bold]Docker[/bold]",
            border_style="dim",
        )

    t = Table(box=box.SIMPLE, show_header=True, header_style="bold dim",
              show_edge=False, padding=(0, 1))
    t.add_column("Name",    style="cyan", max_width=22)
    t.add_column("Image",   style="dim",  max_width=20)
    t.add_column("State",   width=10)
    t.add_column("CPU%",    justify="right", width=7)
    t.add_column("MEM",     justify="right", width=9)
    t.add_column("MEM%",    justify="right", width=7)
    t.add_column("PIDs",    justify="right", width=5)

    for c in docker_d.get("containers", [])[:12]:
        # Use "state" (normalized) field; fall back to "status"
        state = c.get("state") or c.get("status", "?")
        # Normalize long status strings like "Up 2 hours" → check for "running"
        is_running = (state == "running")
        stats = c.get("stats") or {}
        cpu   = float(stats.get("cpu_pct") or 0)
        mem   = float(stats.get("mem_pct") or 0)
        mem_u = _mb(stats.get("mem_used_mb")) if stats.get("mem_used_mb") else stats.get("mem_usage") or "—"

        if is_running:
            state_text = Text("● running", style="bold green")
        elif state in ("exited", "dead"):
            state_text = Text("○ " + state, style="dim red")
        elif state == "paused":
            state_text = Text("⏸ paused",  style="yellow")
        else:
            state_text = Text("  " + str(state)[:8], style="dim")

        t.add_row(
            c.get("name", "?"),
            c.get("image", "?"),
            state_text,
            Text("{:.1f}".format(cpu), style=_pct_style(cpu)) if is_running else Text("—", "dim"),
            Text(str(mem_u))                                   if is_running else Text("—", "dim"),
            Text("{:.1f}".format(mem), style=_pct_style(mem)) if is_running else Text("—", "dim"),
            str(stats.get("pids", "—"))                        if is_running else "—",
        )

    ver = docker_d.get("version") or {}
    n_images = ver.get("total_images", len(docker_d.get("images", [])) or "?")
    sub = "[dim]Docker {}  images {}  containers {}/{}[/dim]".format(
          ver.get("version", ver.get("server", "?")),
          n_images,
          ver.get("running_containers", "?"),
          ver.get("total_containers", "?"))
    return Panel(t, title="[bold]Docker[/bold]", subtitle=sub, border_style="cyan")


def _sec_panel(sec_d):
    falco  = sec_d.get("falco", {})
    events = sec_d.get("ssh_events", [])
    t = Table.grid(padding=(0, 1))
    t.add_column(width=16)
    t.add_column()

    falco_st = (Text("● RUNNING", style="bold green")  if falco.get("running")
                else Text("○ STOPPED", style="bold red") if falco.get("installed")
                else Text("⊘ Not installed", style="dim"))
    t.add_row(Text("Falco:", style="bold"), falco_st)
    for ev in (falco.get("recent_events") or [])[:3]:
        lvl = ev.get("level", "")
        col = "red" if "CRITICAL" in lvl or "ERROR" in lvl else "yellow"
        t.add_row(
            Text("  {}".format((ev.get("timestamp") or "")[-8:]), style="dim"),
            Text(ev.get("message", "")[:55], style=col),
        )

    fails = sum(1 for e in events if e.get("type") == "ssh_fail")
    ok    = sum(1 for e in events if e.get("type") == "ssh_success")
    t.add_row(Text("SSH fails:", style="bold"),
              Text(str(fails), style="bold red" if fails else "bold green"))
    t.add_row(Text("SSH ok:",   style="bold"), Text(str(ok), style="green"))
    for e in [x for x in events if x.get("type") == "ssh_fail"][:2]:
        t.add_row(Text("  fail", "red dim"), Text(e.get("raw", "")[:55], "dim"))

    f2b = sec_d.get("fail2ban", {})
    t.add_row(Text("fail2ban:", style="bold"),
              Text("● active", "green") if f2b.get("installed") else Text("⊘ off", "dim"))
    return Panel(t, title="[bold]Security[/bold]", border_style="red")


# ─── Dashboard engine ────────────────────────────────────────────────────────

class _State:
    def __init__(self):
        self.data      = {}
        self.lock      = threading.RLock()
        self.running   = False
        self._sec_tick = 0

    def update(self, key, fn):
        try:
            with self.lock:
                self.data[key] = fn()
        except Exception as exc:
            with self.lock:
                self.data[key] = {"error": str(exc)}

    def snapshot(self):
        with self.lock:
            return dict(self.data)


def _render(state):
    d     = state.snapshot()
    sys_d = d.get("system",    {})
    dsk_d = d.get("disk",      {})
    prc_d = d.get("processes", {})
    net_d = d.get("network",   {})
    dkr_d = d.get("docker",    {})
    sec_d = d.get("security",  {})

    layout = Layout()
    layout.split_column(
        Layout(name="hdr",    size=3),
        Layout(name="top",    size=12),
        Layout(name="middle", size=16),
        Layout(name="bottom"),
    )
    layout["hdr"].update(_header(sys_d))
    layout["top"].split_row(Layout(_cpu_panel(sys_d)), Layout(_mem_panel(sys_d)))
    layout["middle"].split_row(Layout(_disk_panel(dsk_d)), Layout(_net_panel(net_d)))
    layout["bottom"].split_row(
        Layout(_proc_panel(prc_d),   ratio=2),
        Layout(_docker_panel(dkr_d), ratio=2),
        Layout(_sec_panel(sec_d),    ratio=1),
    )
    return layout


def _bg_loop(state, refresh):
    """Background data collection loop.
    CPU is sampled with a 1-second interval each cycle (matches htop).
    Security is sampled every 5 cycles to avoid excessive log file reads.
    """
    while state.running:
        # System (CPU blocks for 1s internally — done in bg so dashboard stays live)
        state.update("system",    _sys.collect_all)
        state.update("disk",      _disk.collect_all)
        state.update("processes", _proc.collect_all)
        state.update("network",   _net.collect_all)
        state.update("docker",    _docker.collect_all)
        state._sec_tick += 1
        if state._sec_tick % 5 == 1:
            state.update("security", _sec.collect_all)
        time.sleep(max(0, refresh - 1.0))  # CPU sampling already took ~1s


def run_dashboard(refresh=3.0):
    """
    Launch the live SysDock terminal dashboard.
    Press Ctrl+C to exit.
    refresh: total cycle time in seconds (minimum 2.0 enforced).
    """
    refresh = max(2.0, refresh)

    console.print("[bold cyan]{} v{} — loading...[/bold cyan]".format(TOOL_NAME, VERSION))

    state = _State()
    # Warm with initial data (CPU blocks for 1s — acceptable on startup)
    for key, fn in [
        ("system",    _sys.collect_all),
        ("disk",      _disk.collect_all),
        ("processes", _proc.collect_all),
        ("network",   _net.collect_all),
        ("docker",    _docker.collect_all),
        ("security",  _sec.collect_all),
    ]:
        state.update(key, fn)

    state.running = True
    bg = threading.Thread(target=_bg_loop, args=(state, refresh), daemon=True)
    bg.start()

    try:
        with Live(_render(state), refresh_per_second=1, screen=True, console=console) as live:
            while True:
                live.update(_render(state))
                time.sleep(1.0)
    except KeyboardInterrupt:
        pass
    finally:
        state.running = False
        console.print("\n[dim cyan]SysDock closed. Goodbye![/dim cyan]\n")
