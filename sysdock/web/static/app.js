"use strict";

let token = sessionStorage.getItem("sysdock_token") || "";
let reconnectTimer = null;
let sortKey = "cpu_percent";
let sortDesc = true;
let filter = "";
let latest = null;

const $ = (id) => document.getElementById(id);

function authHeaders() {
  return token ? { Authorization: "Bearer " + token } : {};
}

function setConn(text, cls) {
  const el = $("conn");
  el.textContent = text;
  el.className = "status" + (cls ? " " + cls : "");
}

function fmtBytes(n) {
  if (n === null || n === undefined) return "—";
  let v = Number(n);
  const units = ["B", "K", "M", "G", "T", "P"];
  for (const u of units) {
    if (Math.abs(v) < 1024) return (u === "B" ? v.toFixed(0) : v.toFixed(1)) + u;
    v /= 1024;
  }
  return v.toFixed(1) + "E";
}

function barClass(pct) {
  if (pct >= 90) return "bar crit";
  if (pct >= 70) return "bar warn";
  return "bar";
}

function bar(pct) {
  const p = Math.max(0, Math.min(100, Number(pct) || 0));
  const d = document.createElement("div");
  d.className = barClass(p);
  const s = document.createElement("span");
  s.style.width = p + "%";
  d.appendChild(s);
  return d;
}

function row(k, v, cls) {
  const r = document.createElement("div");
  r.className = "row";
  const kk = document.createElement("span");
  kk.className = "k";
  kk.textContent = k;
  const vv = document.createElement("span");
  if (cls) vv.className = cls;
  vv.textContent = v;
  r.append(kk, vv);
  return r;
}

function showAuth() {
  $("auth").classList.remove("hidden");
  $("main").classList.add("hidden");
}
function hideAuth() {
  $("auth").classList.add("hidden");
  $("main").classList.remove("hidden");
}

function render(snap) {
  latest = snap;
  $("host").textContent = (snap.host && snap.host.hostname) || "—";

  // CPU
  const cpu = snap.cpu || {};
  $("cpu-total").textContent = (cpu.total_percent ?? 0).toFixed(1) + "%";
  const cores = $("cores");
  cores.textContent = "";
  (cpu.per_core_percent || []).forEach((pct, i) => {
    const c = document.createElement("div");
    c.className = "core";
    const lbl = document.createElement("span");
    lbl.className = "lbl";
    lbl.textContent = i;
    const pc = document.createElement("span");
    pc.className = "pct";
    pc.textContent = Math.round(pct) + "%";
    c.append(lbl, bar(pct), pc);
    cores.appendChild(c);
  });
  $("cpu-meta").textContent =
    `${cpu.logical_cores || "?"} cores · ${cpu.model || ""}` +
    (cpu.load_avg ? ` · load ${cpu.load_avg.map((x) => x.toFixed(2)).join(" ")}` : "");

  // Memory
  const mem = snap.memory || {};
  const memBar = $("mem-bar");
  memBar.textContent = "";
  memBar.appendChild(bar(mem.percent));
  $("mem-meta").textContent = `${fmtBytes(mem.used)} / ${fmtBytes(mem.total)} (${(mem.percent ?? 0).toFixed(1)}%)`;
  const swapBar = $("swap-bar");
  swapBar.textContent = "";
  if (mem.swap_total) {
    swapBar.appendChild(bar(mem.swap_percent));
    $("swap-meta").textContent = `swap ${fmtBytes(mem.swap_used)} / ${fmtBytes(mem.swap_total)}`;
  } else {
    $("swap-meta").textContent = "no swap";
  }

  // Network
  const net = $("net");
  net.textContent = "";
  (snap.network ? snap.network.interfaces : [])
    .filter((n) => n.is_up && (n.rx_bytes_per_s || n.tx_bytes_per_s || (n.addresses || []).length))
    .forEach((n) => {
      net.appendChild(row(n.name, `↓ ${fmtBytes(n.rx_bytes_per_s)}/s   ↑ ${fmtBytes(n.tx_bytes_per_s)}/s`));
    });

  // GPU
  const gpu = snap.gpu || {};
  if (gpu.available && gpu.devices && gpu.devices.length) {
    $("gpu-card").style.display = "";
    const g = $("gpu");
    g.textContent = "";
    gpu.devices.forEach((d) => {
      const util = d.util_percent === null ? "—" : d.util_percent.toFixed(0) + "%";
      const vram = d.mem_total ? `${fmtBytes(d.mem_used)} / ${fmtBytes(d.mem_total)}` : "";
      g.appendChild(row(`${d.vendor} · ${d.name}`, `${util} ${vram}`));
    });
  } else {
    $("gpu-card").style.display = "none";
  }

  // Disks
  const disks = $("disks");
  disks.textContent = "";
  (snap.disk ? snap.disk.partitions : []).forEach((p) => {
    const cls = p.percent >= 90 ? "bad" : p.percent >= 75 ? "warn" : "ok";
    disks.appendChild(row(p.mountpoint, `${fmtBytes(p.used)} / ${fmtBytes(p.total)} · ${p.percent.toFixed(0)}%`, cls));
  });

  renderSecurity(snap.security || {});
  renderProcs();

  const f = $("foot");
  f.textContent = `collected ${snap.collected_at_iso || ""} · ${snap.collection_ms || 0} ms`;
}

function renderSecurity(sec) {
  const s = $("security");
  s.textContent = "";
  const fw = sec.firewall || {};
  if (fw.available) {
    const state = fw.enabled ? "enabled" : fw.enabled === false ? "disabled" : "unknown";
    s.appendChild(row("Firewall", `${state} (${fw.backend}${fw.default_policy ? ", " + fw.default_policy : ""})`,
      fw.enabled ? "ok" : "warn"));
  } else {
    s.appendChild(row("Firewall", "unavailable — " + (fw.reason || ""), "k"));
  }
  const op = sec.open_ports || {};
  if (op.available) {
    const ports = [...new Set((op.ports || []).map((p) => p.port + "/" + p.proto))].slice(0, 16).join(", ");
    s.appendChild(row("Open ports", `${(op.ports || []).length}: ${ports || "none"}`));
  } else {
    s.appendChild(row("Open ports", "unavailable — " + (op.reason || ""), "k"));
  }
  const fa = sec.failed_auth || {};
  s.appendChild(row("Failed auth", fa.available ? `${(fa.events || []).length} recent` : "unavailable", fa.available ? "" : "k"));
  const intr = sec.intrusion || {};
  if (intr.available) {
    const banned = (intr.blocks || []).filter((b) => b.source).length;
    s.appendChild(row("Intrusion", `${banned} banned`));
  } else {
    s.appendChild(row("Intrusion", "unavailable", "k"));
  }
}

function renderProcs() {
  if (!latest || !latest.processes) return;
  let procs = (latest.processes.top_by_cpu || []).slice();
  if (filter) {
    const f = filter.toLowerCase();
    procs = procs.filter((p) => (p.name || "").toLowerCase().includes(f) || (p.username || "").toLowerCase().includes(f));
  }
  procs.sort((a, b) => {
    const av = a[sortKey], bv = b[sortKey];
    const cmp = typeof av === "string" ? String(av).localeCompare(String(bv)) : (av - bv);
    return sortDesc ? -cmp : cmp;
  });
  const body = $("proc-body");
  body.textContent = "";
  procs.forEach((p) => {
    const tr = document.createElement("tr");
    const cells = [
      [p.pid, "num"],
      [p.username || "?", ""],
      [(p.cpu_percent ?? 0).toFixed(1), "num"],
      [(p.memory_percent ?? 0).toFixed(1), "num"],
      [fmtBytes(p.rss), "num"],
      [p.name || "?", ""],
    ];
    cells.forEach(([val, cls]) => {
      const td = document.createElement("td");
      if (cls) td.className = cls;
      td.textContent = val;
      tr.appendChild(td);
    });
    body.appendChild(tr);
  });
}

function wireControls() {
  document.querySelectorAll("#proc-table th").forEach((th) => {
    th.addEventListener("click", () => {
      const key = th.dataset.key;
      if (sortKey === key) sortDesc = !sortDesc;
      else { sortKey = key; sortDesc = key !== "name" && key !== "username"; }
      document.querySelectorAll("#proc-table th").forEach((h) => h.classList.remove("sorted"));
      th.classList.add("sorted");
      renderProcs();
    });
  });
  $("proc-filter").addEventListener("input", (e) => { filter = e.target.value; renderProcs(); });
  $("token-save").addEventListener("click", () => {
    token = $("token").value.trim();
    sessionStorage.setItem("sysdock_token", token);
    $("auth-err").textContent = "";
    connect();
  });
}

function scheduleReconnect() {
  if (reconnectTimer) return;
  reconnectTimer = setTimeout(() => { reconnectTimer = null; connect(); }, 2000);
}

async function connect() {
  setConn("connecting…", "");
  try {
    const resp = await fetch("api/stream", { headers: authHeaders() });
    if (resp.status === 401) {
      showAuth();
      setConn("auth required", "down");
      if (token) $("auth-err").textContent = "Invalid token.";
      return;
    }
    if (!resp.ok) { setConn("error " + resp.status, "down"); scheduleReconnect(); return; }
    hideAuth();
    setConn("live", "live");
    const reader = resp.body.getReader();
    const dec = new TextDecoder();
    let buf = "";
    while (true) {
      const { value, done } = await reader.read();
      if (done) break;
      buf += dec.decode(value, { stream: true });
      let idx;
      while ((idx = buf.indexOf("\n\n")) >= 0) {
        const frame = buf.slice(0, idx);
        buf = buf.slice(idx + 2);
        const line = frame.split("\n").find((l) => l.startsWith("data:"));
        if (line) {
          try { render(JSON.parse(line.slice(5).trim())); } catch (e) { /* ignore */ }
        }
      }
    }
    setConn("reconnecting…", "down");
    scheduleReconnect();
  } catch (e) {
    setConn("disconnected", "down");
    scheduleReconnect();
  }
}

wireControls();
connect();
