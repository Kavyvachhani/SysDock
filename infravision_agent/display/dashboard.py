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
import os
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
VERSION   = "1.2.8"


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

def _cpu_panel(sys_d, dkr_d, show_cores=True):
    cpu   = sys_d.get("cpu", {})
    total = float(cpu.get("usage_total") or 0)
    logical = cpu.get("logical_cores") or "?"
    phys    = cpu.get("physical_cores") or "?"
    model   = cpu.get("model") or "CPU"

    # Docker-attributed CPU
    dkr_cpu = 0.0
    if dkr_d.get("available"):
        for c in dkr_d.get("containers", []):
            if c.get("state") == "running":
                dkr_cpu += float((c.get("stats") or {}).get("cpu_pct") or 0)
    sys_cpu = max(0.0, total - dkr_cpu)

    # Main vertical grid for the whole panel
    main_grid = Table.grid(padding=(0, 0), expand=True)
    
    # Section 1: Global Stats
    global_t = Table.grid(padding=(0, 1), expand=True)
    global_t.add_column(width=6)
    global_t.add_column(ratio=1)
    global_t.add_column(width=8, justify="right")

    global_t.add_row(Text("ALL", style="bold"), _bar(total, 26), Text("{:5.1f}%".format(total), style=_pct_style(total)))
    main_grid.add_row(global_t)

    # Section 2: Per-Core (if showing)
    if show_cores:
        cores = cpu.get("usage_per_core", [])
        core_grid = Table.grid(expand=True, padding=(0, 2))
        core_grid.add_column(); core_grid.add_column()
        # ... abbreviated ...
        num_cores = len(cores)
        rows_needed = (num_cores + 1) // 2
        for r in range(rows_needed):
            c1_idx = r
            c2_idx = r + rows_needed
            row_items = []
            if c1_idx < num_cores:
                p1 = float(cores[c1_idx] or 0)
                row_items.extend([Text("{:2d} ".format(c1_idx), style="dim"), _bar(p1, 10), Text(" {:>5.1f}%".format(p1), style=_pct_style(p1))])
            if c2_idx < num_cores:
                p2 = float(cores[c2_idx] or 0)
                row_items.extend([Text("  {:2d} ".format(c2_idx), style="dim"), _bar(p2, 10), Text(" {:>5.1f}%".format(p2), style=_pct_style(p2))])
            core_grid.add_row(*row_items)
            
        main_grid.add_row(Text("")) 
        main_grid.add_row(Panel(core_grid, title="[dim]Per-Core Usage[/dim]", border_style="dim"))

    # Section 3: Attribution
    if dkr_cpu > 0:
        attr_t = Table.grid(padding=(0, 1), expand=True)
        attr_t.add_column(width=6); attr_t.add_column(ratio=1); attr_t.add_column(width=8, justify="right")
        attr_t.add_row(Text("🐳", style="cyan"), _bar(min(100.0, dkr_cpu), 26), Text("~{:.1f}%".format(dkr_cpu), style="cyan"))
        attr_t.add_row(Text("OS", style="dim"), _bar(min(100.0, sys_cpu), 26), Text("~{:.1f}%".format(sys_cpu), style="dim"))
        main_grid.add_row(Text(""))
        main_grid.add_row(attr_t)

    # Bottom summary
    main_grid.add_row(Text(""))
    summary = Text(f"{model} | {logical}L/{phys}P cores", style="dim", justify="center")
    main_grid.add_row(summary)

    return Panel(
        main_grid,
        title="[bold cyan]CPU Usage[/bold cyan]  [dim]usr {:.1f}%  sys {:.1f}%[/dim]".format(
              float(cpu.get("user_pct") or 0), float(cpu.get("system_pct") or 0)),
        border_style="cyan",
    )


def _gpu_panel(sys_d):
    gpus = sys_d.get("gpu", [])
    if not gpus:
        return Panel(Align.center(Text("No NVIDIA GPU detected", style="dim")), title="[bold cyan]GPU Monitoring[/bold cyan]", border_style="cyan")
    
    t = Table.grid(padding=(0, 1), expand=True)
    t.add_column(width=6); t.add_column(ratio=1); t.add_column(width=8, justify="right")
    
    for g in gpus[:1]: # Show first GPU in detail
        u = float(g.get("gpu_util_pct", 0))
        m_used = g.get("mem_used_mb", 0)
        m_total = g.get("mem_total_mb", 0)
        m_pct = g.get("mem_pct", 0)
        temp = g.get("temp_c", 0)
        
        t.add_row(Text("Load", style="bold"), _bar(u, 18, 70, 90), Text("{:5.1f}%".format(u), style=_pct_style(u)))
        t.add_row(Text("Mem", style="bold"), _bar(m_pct, 18, 80, 90), Text("{:5.1f}%".format(m_pct), style=_pct_style(m_pct)))
        t.add_row(Text("Temp", style="bold"), _bar(min(100, temp), 18, 75, 85), Text("{:.0f}°C".format(temp), style="yellow"))
        t.add_row(Text(""))
        t.add_row(Text("Name", style="dim"), Text(f"{g.get('name')[:20]}", style="dim"))
        t.add_row(Text("VRAM", style="dim"), Text(f"{m_used:.0f}/{m_total:.0f} MB", style="dim"))

    return Panel(t, title=f"[bold cyan]GPU - {gpus[0].get('id', '0')}[/bold cyan]", border_style="cyan")


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
        Text("{} / {} {:5.1f}%".format(_mb(m.get("used_mb")), _mb(m.get("total_mb")), rp),
             style=_pct_style(rp)),
    )

    sp = float(m.get("swap_percent") or 0)
    t.add_row(
        Text("SWP", style="bold"),
        _bar(sp, 20, 50, 80),
        Text("{} / {} {:5.1f}%".format(_mb(m.get("swap_used_mb")), _mb(m.get("swap_total_mb")), sp),
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
            Text("{:>4.0f}%".format(pct), style=_pct_style(pct, 75, 90)),
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

def _proc_panel(proc_d, limit=14):
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
    for p in procs[:limit]:
        cpu = float(p.get("cpu_pct") or 0)
        mem = float(p.get("mem_pct") or 0)
        sc  = sc_map.get(p.get("status", ""), "?")
        cmd = (p.get("cmd") or p.get("name", "?"))[:49]
        t.add_row(
            _clamp(p.get("user") or "?", 10),
            Text(sc, style="bold green" if sc == "R" else "dim"),
            Text("{:5.1f}".format(cpu), style=_pct_style(cpu)),
            Text("{:5.1f}".format(mem), style=_pct_style(mem)),
            _mb(p.get("rss_mb")),
            cmd,
        )
    sub = "[dim]tasks {}  run {}  slp {}  zmb {}[/dim]".format(
          summary.get("total", 0), summary.get("running", 0),
          summary.get("sleeping", 0), summary.get("zombie", 0))
    return Panel(t, title="[bold]Processes[/bold] [dim](by CPU)[/dim]",
                 subtitle=sub, border_style="blue")


# ── Docker panel (adaptive) ────────────────────────────────────────────────────

def _docker_panel(dkr_d, limit=14):
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

    for c in containers[:limit]:
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
            Text("{:5.1f}".format(cpu), style=_pct_style(cpu)) if is_run else Text("—",  "dim"),
            Text(mem_u)                                         if is_run else Text("—",  "dim"),
            Text("{:5.1f}".format(mem), style=_pct_style(mem)) if is_run else Text("—",  "dim"),
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
        self.version   = 0

    def update(self, key, val):
        with self.lock:
            self.data[key] = val
            self.version += 1

    def snapshot(self):
        with self.lock:
            return dict(self.data)


def _ai_panel(proc_d):
    ai_procs = proc_d.get("ai_processes", [])
    if not ai_procs:
        return Panel(Align.center(Text("No AI services detected", style="dim")), title="[bold]AI / Ollama[/bold]", border_style="dim")
        
    t = Table(box=box.SIMPLE, show_header=True, header_style="bold dim", show_edge=False, padding=(0, 1))
    t.add_column("Service", width=12, style="cyan")
    t.add_column("Status", width=8)
    t.add_column("CPU%", justify="right", width=6)
    t.add_column("MEM", justify="right", width=7)
    
    for p in ai_procs[:6]:
        cpu = float(p.get("cpu_pct") or 0)
        mem_pct = float(p.get("mem_pct") or 0)
        sc = "R" if str(p.get("status")) in ("running", "R") else "S"
        t.add_row(
            _clamp(p.get("name", "?"), 12),
            Text("● run", style="bold green") if sc == "R" else Text("○ " + str(p.get("status", "S"))[:4], style="dim"),
            Text("{:5.1f}".format(cpu), style=_pct_style(cpu)),
            _mb(p.get("rss_mb"))
        )
    return Panel(t, title="[bold]AI / LLM[/bold]", border_style="magenta")


def _render(state):
    d    = state.snapshot()
    sys_d = d.get("system",    {})
    dsk_d = d.get("disk",      {})
    prc_d = d.get("processes", {})
    net_d = d.get("network",   {})
    dkr_d = d.get("docker",    {})
    sec_d = d.get("security",  {})

    term_h = console.height
    term_w = console.width

    show_cores = term_h >= 28  # Lower threshold for showing cores
    
    # Calculate how many cores we can actually fit
    # Header(3) + TopRow(CPU/Mem) + MidRow(Disk/Net) + BtmRow(Proc/Dkr/Sec)
    # Available height for per-core bars in TopRow panel:
    # If term_h is small, we hide cores to prevent scrolling.
    # We can fit about (term_h - 18) cores if we allow the panel to expand.
    
    cpu_cores_count = len(sys_d.get("cpu", {}).get("usage_per_core", []))
    if show_cores and cpu_cores_count > (term_h - 22):
        # Still show some cores even if we can't show all
        pass 

    max_procs = max(3, (term_h - 22) // 3) if term_h >= 24 else 3
    max_dkr   = max_procs

    # Adaptive lengths
    layout = Layout()
    layout.split_column(
        Layout(name="hdr",    size=4),
        Layout(name="top",    ratio=3 if term_h > 40 else 2),
        Layout(name="middle", ratio=2),
        Layout(name="bottom", ratio=3),
    )
    
    # Ensure no debug lines are visible
    for name in ["hdr", "top", "middle", "bottom"]:
        layout[name].debug = False

    layout["hdr"].update(_header(sys_d))
    layout["hdr"].debug = False

    top = layout["top"]
    gpus = sys_d.get("gpu", [])
    
    if gpus:
        top.split_row(
            Layout(_cpu_panel(sys_d, dkr_d, show_cores=show_cores), ratio=3),
            Layout(_gpu_panel(sys_d), ratio=2),
            Layout(_mem_panel(sys_d, dkr_d), ratio=3),
        )
    else:
        top.split_row(
            Layout(_cpu_panel(sys_d, dkr_d, show_cores=show_cores)),
            Layout(_mem_panel(sys_d, dkr_d)),
        )
    
    for l in top.children: l.debug = False

    layout["middle"].split_row(
        Layout(_disk_panel(dsk_d, dkr_d)),
        Layout(_net_panel(net_d)),
    )
    for l in layout["middle"].children: l.debug = False
    
    btm = layout["bottom"]
    ai_procs = prc_d.get("ai_processes", [])
    
    if ai_procs:
        btm.split_row(
            Layout(_proc_panel(prc_d, max_procs), ratio=4),
            Layout(_docker_panel(dkr_d, max_dkr), ratio=4),
            Layout(_ai_panel(prc_d),              ratio=3),
        )
    else:
        btm.split_row(
            Layout(_proc_panel(prc_d, max_procs), ratio=4),
            Layout(_docker_panel(dkr_d, max_dkr), ratio=5),
            Layout(_sec_panel(sec_d),             ratio=2),
        )
    for l in btm.children: l.debug = False
        
    return layout


def _bg_loop(state, refresh):
    while state.running:
        # Batch collect all data to prevent partial-update flickering
        new_data = {
            "system":    _sys.collect_all(),
            "disk":      _disk.collect_all(),
            "processes": _proc.collect_all(),
            "network":   _net.collect_all(),
            "docker":    _docker.collect_all(),
        }
        state._sec_tick += 1
        if state._sec_tick % 5 == 1:
            new_data["security"] = _sec.collect_all()
        
        # Atomic swap
        with state.lock:
            state.data.update(new_data)
            state.version += 1
            
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
        # Stabilization for Windows terminals: 
        # - disable Alt Screen to stop 'automatic erasing' flicker
        # - use a very steady refresh cycle
        is_windows = (os.name == 'nt')
        
        # Initial render to clear the old screen state
        if is_windows:
            console.clear()

        with Live(_render(state), refresh_per_second=10, screen=not is_windows, console=console, auto_refresh=False) as live:
            last_version = -1
            while True:
                with state.lock:
                    current_version = state.version
                
                # Update only when new data is ready
                if current_version != last_version:
                    live.update(_render(state), refresh=True)
                    last_version = current_version
                
                # Steady heartbeat sleep
                time.sleep(0.1)
    except KeyboardInterrupt:
        pass
    finally:
        state.running = False
        console.print("\n[dim cyan]SysDock closed.[/dim cyan]\n")
