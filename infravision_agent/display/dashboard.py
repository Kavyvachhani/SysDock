"""
SysDock — adaptive live dashboard.
- Auto-sizes Docker name/image columns based on actual content
- Load breakdown: Docker-attributed vs system total
- Docker storage section (images + volumes disk usage)
- Accurate htop-style RAM (Shmem-corrected)
Press Ctrl+C to exit.
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
from rich import box

from infravision_agent.collectors import (
    system as _sys, disk as _disk, processes as _proc,
    network as _net, docker_collector as _docker, security as _sec,
)

console = Console()
TOOL_NAME = "SysDock"
VERSION   = "1.2.4"


# ── Helpers ───────────────────────────────────────────────────────────────────

def _pct_style(v, warn=70, crit=90):
    if v is None: return "dim white"
    v = float(v)
    if v >= crit: return "bold red"
    if v >= warn: return "bold yellow"
    return "bold green"


def _bar(pct, width=20, warn=70, crit=90):
    pct    = min(100.0, max(0.0, float(pct or 0)))
    filled = int(pct / 100 * width)
    color  = _pct_style(pct, warn, crit)
    b = Text()
    b.append("[", style="dim")
    b.append("█" * filled,           style=color)
    b.append("░" * (width - filled), style="dim")
    b.append("]", style="dim")
    return b


def _mb(mb):
    if mb is None: return "?"
    mb = float(mb)
    if mb >= 1024: return "{:.2f}G".format(mb / 1024)
    return "{:.0f}M".format(mb)


def _clamp(s, n):
    """Truncate string to n chars, adding … if needed."""
    s = str(s or "")
    return s[:n - 1] + "…" if len(s) > n else s


def _auto_width(values, header, min_w=10, max_w=30):
    """Compute a good column width based on actual data + header."""
    mx = max((len(str(v)) for v in values), default=0)
    return min(max_w, max(min_w, max(mx, len(header)) + 1))


# ── Header ─────────────────────────────────────────────────────────────────────

def _header(sys_d):
    h    = sys_d.get("hostname", {})
    up   = sys_d.get("uptime",   {})
    load = sys_d.get("load",     {})
    now  = datetime.now().strftime("%Y-%m-%d  %H:%M:%S")
    g = Table.grid(padding=(0, 3))
    g.add_column(); g.add_column(); g.add_column(); g.add_column(); g.add_column()
    g.add_row(
        Text("🖥  " + h.get("hostname", "?"),     style="bold cyan"),
        Text("📦 " + h.get("os", "?")[:28],       style="dim"),
        Text("⬆  " + up.get("uptime_human", "?"), style="green"),
        Text("⚡ Load {}/{}/{}".format(
              load.get("load1", "?"), load.get("load5", "?"), load.get("load15", "?")),
             style="yellow"),
        Text("🕐 " + now, style="dim"),
    )
    return Panel(
        g,
        title="[bold cyan]{} v{}[/bold cyan]".format(TOOL_NAME, VERSION),
        border_style="cyan", padding=(0, 1),
    )


# ── CPU panel ─────────────────────────────────────────────────────────────────

def _cpu_panel(sys_d, dkr_d):
    cpu   = sys_d.get("cpu", {})
    total = float(cpu.get("usage_total") or 0)

    # Docker-attributed CPU: sum cpu_pct of running containers
    dkr_cpu = 0.0
    if dkr_d.get("available"):
        for c in dkr_d.get("containers", []):
            if c.get("state") == "running":
                dkr_cpu += float((c.get("stats") or {}).get("cpu_pct") or 0)
    sys_cpu = max(0.0, total - dkr_cpu)

    t = Table.grid(padding=(0, 1))
    t.add_column(width=6)
    t.add_column()
    t.add_column(width=8, justify="right")

    t.add_row(Text("ALL", style="bold"), _bar(total, 26), Text("{:.1f}%".format(total), style=_pct_style(total)))
    for i, pct in enumerate(cpu.get("usage_per_core", [])):
        pct = float(pct or 0)
        t.add_row(Text("{:2d}".format(i), style="dim"), _bar(pct, 26), Text("{:.1f}%".format(pct), style=_pct_style(pct)))

    # Load attribution bar
    ncores = max(1, cpu.get("logical_cores") or 1)
    t.add_row(Text(""))
    # Docker load bar
    if dkr_cpu > 0:
        t.add_row(
            Text("🐳", style="cyan"),
            _bar(min(100.0, dkr_cpu), 26),
            Text("~{:.1f}%".format(dkr_cpu), style="cyan"),
        )
        t.add_row(
            Text("OS", style="dim"),
            _bar(min(100.0, sys_cpu), 26, 50, 85),
            Text("~{:.1f}%".format(sys_cpu), style="dim"),
        )

    freq = cpu.get("freq_mhz")
    sub = "[dim]{} | {} logical / {} phys | {}MHz[/dim]".format(
          cpu.get("model", "?")[:30],
          cpu.get("logical_cores", "?"),
          cpu.get("physical_cores", "?"),
          freq or "?")
    return Panel(
        t,
        title="[bold]CPU[/bold]  [dim]usr {:.1f}%  sys {:.1f}%  iowait {:.1f}%[/dim]".format(
              float(cpu.get("user_pct") or 0),
              float(cpu.get("system_pct") or 0),
              float(cpu.get("iowait_pct") or 0)),
        subtitle=sub, border_style="blue",
    )


# ── Memory panel ──────────────────────────────────────────────────────────────

def _mem_panel(sys_d, dkr_d):
    m = sys_d.get("memory", {})

    # Docker-attributed memory: sum mem_used_mb of running containers
    dkr_mem_mb = 0.0
    if dkr_d.get("available"):
        for c in dkr_d.get("containers", []):
            if c.get("state") == "running":
                v = (c.get("stats") or {}).get("mem_used_mb") or 0
                dkr_mem_mb += float(v)
    total_mb = float(m.get("total_mb") or 1)

    t = Table.grid(padding=(0, 1))
    t.add_column(width=5)
    t.add_column()
    t.add_column(width=28, justify="right")

    rp = float(m.get("percent") or 0)
    t.add_row(
        Text("RAM", style="bold"),
        _bar(rp, 20),
        Text("{} / {}  {:.1f}%".format(_mb(m.get("used_mb")), _mb(m.get("total_mb")), rp),
             style=_pct_style(rp)),
    )

    sp = float(m.get("swap_percent") or 0)
    t.add_row(
        Text("SWP", style="bold"),
        _bar(sp, 20, 50, 80),
        Text("{} / {}  {:.1f}%".format(_mb(m.get("swap_used_mb")), _mb(m.get("swap_total_mb")), sp),
             style=_pct_style(sp, 50, 80)),
    )

    # Docker memory attribution
    if dkr_mem_mb > 0:
        dkr_pct = min(100.0, 100.0 * dkr_mem_mb / total_mb)
        t.add_row(Text(""))
        t.add_row(
            Text("🐳", style="cyan"),
            _bar(dkr_pct, 20),
            Text("{} ({:.1f}%)".format(_mb(dkr_mem_mb), dkr_pct), style="cyan"),
        )
        sys_mem_mb = max(0.0, float(m.get("used_mb") or 0) - dkr_mem_mb)
        sys_pct    = min(100.0, 100.0 * sys_mem_mb / total_mb)
        t.add_row(
            Text("OS", style="dim"),
            _bar(sys_pct, 20),
            Text("{} ({:.1f}%)".format(_mb(sys_mem_mb), sys_pct), style="dim"),
        )

    sub = "[dim]avail {}  buff/cache {}  shmem {}  free {}[/dim]".format(
          _mb(m.get("available_mb")), _mb(m.get("cached_mb")),
          _mb(m.get("shmem_mb")),     _mb(m.get("free_mb")))
    return Panel(t, title="[bold]Memory[/bold]", subtitle=sub, border_style="magenta")


# ── Disk panel ────────────────────────────────────────────────────────────────

def _disk_panel(disk_d, dkr_d):
    t = Table(box=box.SIMPLE, show_header=True, header_style="bold dim",
              show_edge=False, padding=(0, 1))
    t.add_column("Mount",  style="cyan",  max_width=18)
    t.add_column("FS",     style="dim",   max_width=8)
    t.add_column("Bar",    min_width=12)
    t.add_column("Used",   justify="right")
    t.add_column("Free",   justify="right")
    t.add_column("Total",  justify="right")
    t.add_column("%",      justify="right", width=6)

    for p in disk_d.get("partitions", []):
        pct = float(p.get("percent") or 0)
        t.add_row(
            p.get("mountpoint", "?"),
            p.get("fstype", "?")[:8],
            _bar(pct, 12, 75, 90),
            "{:.1f}G".format(p.get("used_gb", 0)),
            "{:.1f}G".format(p.get("free_gb", 0)),
            "{:.1f}G".format(p.get("total_gb", 0)),
            Text("{:.0f}%".format(pct), style=_pct_style(pct, 75, 90)),
        )

    # Docker disk usage (docker system df)
    dkr_sub = ""
    if dkr_d.get("available"):
        ver = dkr_d.get("version") or {}
        dkr_disk = ver.get("disk_usage") or {}
        if dkr_disk:
            imgs_sz  = dkr_disk.get("images_size",  "?")
            cntr_sz  = dkr_disk.get("containers_size", "?")
            vol_sz   = dkr_disk.get("volumes_size", "?")
            dkr_sub  = "  [cyan]🐳 docker — imgs:{} cntrs:{} vols:{}[/cyan]".format(
                        imgs_sz, cntr_sz, vol_sz)
        else:
            n_imgs = len(dkr_d.get("images", []))
            if n_imgs:
                total_img_mb = sum(float((img.get("size_mb") or 0)) for img in dkr_d.get("images", []))
                dkr_sub = "  [cyan]🐳 {} images  ~{} total[/cyan]".format(n_imgs, _mb(total_img_mb))

    return Panel(t, title="[bold]Disk[/bold]" + dkr_sub, border_style="yellow")


# ── Network panel ─────────────────────────────────────────────────────────────

def _net_panel(net_d):
    t = Table(box=box.SIMPLE, show_header=True, header_style="bold dim",
              show_edge=False, padding=(0, 1))
    t.add_column("Interface", style="cyan",  max_width=14)
    t.add_column("Status",    width=8)
    t.add_column("IP",        max_width=16)
    t.add_column("↓ RX",      justify="right", width=9)
    t.add_column("↑ TX",      justify="right", width=9)
    t.add_column("Err↓",      justify="right", style="dim", width=5)
    t.add_column("Err↑",      justify="right", style="dim", width=5)
    for iface in net_d.get("interfaces", []):
        up  = iface.get("is_up", False)
        ips = ", ".join(a["address"] for a in iface.get("addresses", []) if a.get("type") == "ipv4")
        rx  = float(iface.get("rx_mb_s") or 0)
        tx  = float(iface.get("tx_mb_s") or 0)
        t.add_row(
            iface.get("interface", "?"),
            Text("UP",   style="bold green") if up else Text("DOWN", style="dim red"),
            ips or "—",
            Text("{:.3f}M".format(rx), style="cyan"  if rx > 0 else "dim"),
            Text("{:.3f}M".format(tx), style="green" if tx > 0 else "dim"),
            str(iface.get("errors_in",  0)),
            str(iface.get("errors_out", 0)),
        )
    conns = net_d.get("connections", {})
    sub   = "[dim]estab {}  tw {}  listen {}[/dim]".format(
            conns.get("established", 0), conns.get("time_wait", 0), conns.get("listen", 0))
    return Panel(t, title="[bold]Network[/bold]", subtitle=sub, border_style="green")


# ── Process panel ─────────────────────────────────────────────────────────────

def _proc_panel(proc_d):
    procs   = proc_d.get("top_by_cpu", [])
    summary = proc_d.get("summary", {})
    t = Table(box=box.SIMPLE, show_header=True, header_style="bold dim",
              show_edge=False, padding=(0, 1))
    t.add_column("User", width=10)
    t.add_column("S",    width=2)
    t.add_column("CPU%", justify="right", width=6)
    t.add_column("MEM%", justify="right", width=6)
    t.add_column("RSS",  justify="right", width=7)
    t.add_column("Command")
    sc_map = {"sleeping": "S", "running": "R", "zombie": "Z", "stopped": "T", "disk-sleep": "D"}
    for p in procs[:14]:
        cpu = float(p.get("cpu_pct") or 0)
        mem = float(p.get("mem_pct") or 0)
        sc  = sc_map.get(p.get("status", ""), "?")
        cmd = (p.get("cmd") or p.get("name", "?"))[:49]
        t.add_row(
            _clamp(p.get("user") or "?", 10),
            Text(sc, style="bold green" if sc == "R" else "dim"),
            Text("{:.1f}".format(cpu), style=_pct_style(cpu)),
            Text("{:.1f}".format(mem), style=_pct_style(mem)),
            _mb(p.get("rss_mb")),
            cmd,
        )
    sub = "[dim]tasks {}  run {}  slp {}  zmb {}[/dim]".format(
          summary.get("total", 0), summary.get("running", 0),
          summary.get("sleeping", 0), summary.get("zombie", 0))
    return Panel(t, title="[bold]Processes[/bold] [dim](by CPU)[/dim]",
                 subtitle=sub, border_style="blue")


# ── Docker panel (adaptive) ────────────────────────────────────────────────────

def _docker_panel(dkr_d):
    if not dkr_d.get("available"):
        return Panel(
            Align.center(Text("⊘  " + dkr_d.get("error", "Docker not available"), style="dim")),
            title="[bold]Docker[/bold]", border_style="dim",
        )

    containers = dkr_d.get("containers", [])

    # Auto-compute column widths based on actual names / images
    names  = [c.get("name",  "") for c in containers]
    images = [c.get("image", "") for c in containers]
    name_w  = _auto_width(names,  "Name",  10, 28)
    image_w = _auto_width(images, "Image", 10, 26)

    t = Table(box=box.SIMPLE, show_header=True, header_style="bold dim",
              show_edge=False, padding=(0, 1))
    t.add_column("Name",  style="cyan",  max_width=name_w,  min_width=10)
    t.add_column("Image", style="dim",   max_width=image_w, min_width=10)
    t.add_column("State", width=10)
    t.add_column("CPU%",  justify="right", width=7)
    t.add_column("MEM",   justify="right", width=9)
    t.add_column("MEM%",  justify="right", width=6)
    t.add_column("Net↓",  justify="right", width=7)
    t.add_column("Net↑",  justify="right", width=7)

    for c in containers[:14]:
        state  = c.get("state") or c.get("status", "?")
        is_run = (state == "running")
        stats  = c.get("stats") or {}
        cpu    = float(stats.get("cpu_pct")   or 0)
        mem    = float(stats.get("mem_pct")   or 0)
        mem_u  = _mb(stats.get("mem_used_mb")) if stats.get("mem_used_mb") else "—"
        rx     = stats.get("net_rx_mb")
        tx     = stats.get("net_tx_mb")

        if is_run:
            st_text = Text("● run", style="bold green")
        elif state in ("exited", "dead"):
            st_text = Text("○ " + state[:4], style="dim red")
        elif state == "paused":
            st_text = Text("⏸ psd",  style="yellow")
        else:
            st_text = Text("  " + str(state)[:5], style="dim")

        t.add_row(
            _clamp(c.get("name",  "?"), name_w),
            _clamp(c.get("image", "?"), image_w),
            st_text,
            Text("{:.1f}".format(cpu), style=_pct_style(cpu)) if is_run else Text("—",  "dim"),
            Text(mem_u)                                         if is_run else Text("—",  "dim"),
            Text("{:.1f}".format(mem), style=_pct_style(mem)) if is_run else Text("—",  "dim"),
            Text("{:.2f}M".format(float(rx or 0)), style="cyan")  if rx is not None else Text("—", "dim"),
            Text("{:.2f}M".format(float(tx or 0)), style="green") if tx is not None else Text("—", "dim"),
        )

    ver = dkr_d.get("version") or {}
    dkr_disk = ver.get("disk_usage") or {}
    disk_info = ""
    if dkr_disk:
        disk_info = "  [dim]imgs {} cntrs {} vols {}[/dim]".format(
                    dkr_disk.get("images_size", "?"),
                    dkr_disk.get("containers_size", "?"),
                    dkr_disk.get("volumes_size", "?"))

    sub = "[dim]v{}  images {}  {}/{} running[/dim]{}".format(
          ver.get("version", ver.get("server", "?")),
          ver.get("total_images", len(dkr_d.get("images", []))),
          ver.get("running_containers", "?"),
          ver.get("total_containers",   "?"),
          disk_info)
    return Panel(t, title="[bold]Docker[/bold]", subtitle=sub, border_style="cyan")


# ── Security panel ────────────────────────────────────────────────────────────

def _sec_panel(sec_d):
    ufw    = sec_d.get("ufw", {})
    events = sec_d.get("ssh_events", [])
    t = Table.grid(padding=(0, 1))
    t.add_column(width=12)
    t.add_column()
    
    ufw_st = (Text("● ACTIVE",  style="bold green") if ufw.get("active")
              else Text("○ INACTIVE", style="dim") if ufw.get("installed")
              else Text("⊘ N/A", style="dim"))
    t.add_row(Text("UFW:",  style="bold"), ufw_st)
    
    for rule in (ufw.get("rules") or [])[:5]:
        t.add_row(Text(""), Text(rule, style="cyan"))
        
    fails = sum(1 for e in events if e.get("type") == "ssh_fail")
    ok    = sum(1 for e in events if e.get("type") == "ssh_success")
    t.add_row(Text("SSH fail:", style="bold"), Text(str(fails), style="bold red" if fails else "green"))
    t.add_row(Text("SSH ok:",   style="bold"), Text(str(ok), style="green"))
    
    f2b = sec_d.get("fail2ban", {})
    t.add_row(Text("fail2ban:", style="bold"),
              Text("active", "green") if f2b.get("installed") else Text("off", "dim"))
    return Panel(t, title="[bold]Security / Firewall[/bold]", border_style="red")


# ── State / background loop ───────────────────────────────────────────────────

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
    d    = state.snapshot()
    sys_d = d.get("system",    {})
    dsk_d = d.get("disk",      {})
    prc_d = d.get("processes", {})
    net_d = d.get("network",   {})
    dkr_d = d.get("docker",    {})
    sec_d = d.get("security",  {})

    layout = Layout()
    layout.split_column(
        Layout(name="hdr",    size=3),
        Layout(name="top",    size=13),
        Layout(name="middle", size=15),
        Layout(name="bottom"),
    )
    layout["hdr"].update(_header(sys_d))
    # Pass docker data to CPU and memory panels for attribution bars
    layout["top"].split_row(
        Layout(_cpu_panel(sys_d, dkr_d)),
        Layout(_mem_panel(sys_d, dkr_d)),
    )
    # Pass docker data to disk panel for Docker storage info
    layout["middle"].split_row(
        Layout(_disk_panel(dsk_d, dkr_d)),
        Layout(_net_panel(net_d)),
    )
    layout["bottom"].split_row(
        Layout(_proc_panel(prc_d),   ratio=2),
        Layout(_docker_panel(dkr_d), ratio=3),
        Layout(_sec_panel(sec_d),    ratio=1),
    )
    return layout


def _bg_loop(state, refresh):
    while state.running:
        state.update("system",    _sys.collect_all)   # blocks ~1s for CPU sampling
        state.update("disk",      _disk.collect_all)
        state.update("processes", _proc.collect_all)
        state.update("network",   _net.collect_all)
        state.update("docker",    _docker.collect_all)
        state._sec_tick += 1
        if state._sec_tick % 5 == 1:
            state.update("security", _sec.collect_all)
        time.sleep(max(0, refresh - 1.0))


def run_dashboard(refresh=3.0):
    """Open the live SysDock dashboard. Press Ctrl+C to exit."""
    refresh = max(2.0, refresh)
    console.print("[bold cyan]{} v{} — loading...[/bold cyan]".format(TOOL_NAME, VERSION))

    state = _State()
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
        console.print("\n[dim cyan]SysDock closed.[/dim cyan]\n")
