<h1 align="center">SysDock 🚀</h1>

<p align="center">
  <b>Modern Linux monitoring agent with a live terminal dashboard, accurate Docker metrics, and a pip-installable CLI.</b>
</p>

<p align="center">
  <a href="https://pypi.org/project/sysdock/"><img src="https://img.shields.io/pypi/v/sysdock.svg?color=blue" alt="PyPI version"></a>
  <a href="https://pypi.org/project/sysdock/"><img src="https://img.shields.io/pypi/pyversions/sysdock.svg" alt="Python versions"></a>
  <a href="https://github.com/Kavyvachhani/SysDock/blob/main/LICENSE"><img src="https://img.shields.io/pypi/l/sysdock.svg?color=green" alt="License"></a>
</p>

---

## ⚡ What is SysDock?

SysDock is a lightweight, zero-configuration monitoring tool for **any Linux server**. It runs completely in the terminal and provides real-time, zero-clutter insights into your system's performance, Docker containers, and live firewall rules.

Think of it as `htop` + `docker stats` + `ufw status` rolled into one beautiful dashboard!

```bash
pipx install sysdock
sysdock          # opens the live dashboard instantly
```

---

## ✨ Features

- 🖥 **Live Terminal Dashboard** — Monitor CPU per-core, RAM, disk, network throughput, processes, and security.
- 🐳 **Laser-Accurate Docker Metrics** — CPU %, true memory usage (correctly subtracting page caching), and network I/O per container exactly matching the `docker stats` formula.
- 📊 **htop-Grade Accuracy** — CPU sampled perfectly at precise intervals; RAM utilizes the authentic `htop` free/buffers/cached formula.
- 🛡️ **Active Firewall & Security Panel** — Live UFW (Uncomplicated Firewall) status, permitted port rules, SSH failures, and `fail2ban` tracking directly on the dashboard.
- 🌐 **Built-in HTTP API** — Instantly export metrics as a JSON snapshot or via a live SSE (Server-Sent Events) network stream without external agents.
- 🛠 **Zero Configuration** — Works cleanly on almost any Linux distribution with Python 3.6+. No heavy daemons needed.

---

## 📦 Installation

We highly recommend using `pipx` (or a standard `pip` environment) for clean installation:

```bash
# Recommended standard install
pipx install sysdock

# Install with native Docker SDK (richer container stats)
pipx install "sysdock[docker]"

# Upgrade to the latest version
pipx upgrade sysdock
```

*Note: If `pipx` is not available on your system, standard `pip install sysdock` works beautifully as well.*

---

## 🚀 Quick Reference

```bash
sysdock              # open live dashboard (default)
sysdock dash         # same as above
sysdock start        # start metrics HTTP server on :5010
sysdock status       # one-shot snapshot (rich table)
sysdock status --json               # raw JSON
sysdock status --section docker     # Docker only
sysdock check        # verify all dependencies
sysdock install      # install as a systemd background service (requires root)
sysdock uninstall    # remove background service (requires root)
```

---

## 📡 HTTP Data API

Start the API server in the background, then pull data securely:

```bash
sysdock start --port 5010
```

| Endpoint | Description |
|----------|-------------|
| `GET /` | Full JSON snapshot — system, docker, processes, and security |
| `GET /stream` | **Server-Sent Events** — pushes a live metrics update every 5 seconds |
| `GET /health` | Basic `{"status": "ok"}` check |

> **Security Note:** If exposing the HTTP API to the internet, always restrict port `5010` to your monitoring server's IP via AWS Security Groups, UFW, or iptables.

---

## 🎯 Metric Accuracy Details

SysDock takes immense pride in providing data that you can actually trust:

| Metric | Method |
|--------|--------|
| **CPU %** | 1-second delta sampling per core (identical to `htop`) |
| **RAM used** | `total − free − buffers − cached` (authentic `htop` formula) |
| **Docker CPU** | `(cpu_delta / sys_delta) × nCPUs × 100` (matches `docker stats`) |
| **Docker Memory** | Subtracts page caching (`inactive_file`/`cache`) from raw memory usage |

---

## 🐧 Compatibility

| Distro | Status |
|--------|--------|
| Ubuntu 20.04 / 22.04 / 24.04 | ✅ Fully Supported |
| Debian 10 / 11 / 12 | ✅ Fully Supported |
| Amazon Linux 2 / 2023 | ✅ Fully Supported |
| CentOS / RHEL (7 / 8 / 9) | ✅ Fully Supported |
| Alpine / Arch Linux | ✅ Fully Supported |

*Requires Linux `/proc` filesystem and Python 3.6 – 3.12.*

---

## 💼 License & Links

- **PyPI Package:** [pypi.org/project/sysdock](https://pypi.org/project/sysdock/)
- **Source Code:** [github.com/Kavyvachhani/SysDock](https://github.com/Kavyvachhani/SysDock)
- **Issue Tracker:** [github.com/Kavyvachhani/SysDock/issues](https://github.com/Kavyvachhani/SysDock/issues)

MIT License © 2026 [Kavyvachhani](https://github.com/Kavyvachhani)
