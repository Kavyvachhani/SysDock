# SysDock

**Linux / EC2 monitoring agent** with a live terminal dashboard, accurate Docker metrics, and a pip-installable CLI.

```bash
pip install sysdock
sysdock          # opens the live dashboard — like htop, but more
```

---

## Features

- 🖥 **Live terminal dashboard** — CPU per-core, RAM, disk, network, processes, Docker, security
- 🐳 **Accurate Docker metrics** — CPU %, memory, network I/O per container (matches `docker stats`)
- 📊 **htop-accurate readings** — CPU sampled at 1s interval; RAM uses htop's exact formula
- 🌐 **HTTP metrics API** — JSON snapshot + live SSE stream on one port
- 🔒 **Security panel** — Falco events, SSH failures, fail2ban status
- ⚡ **Zero config** — works on any Linux distro, Python 3.6+

---

## Install

```bash
# From PyPI
pip install sysdock

# With Docker SDK (richer container stats)
pip install "sysdock[docker]"

# With everything
pip install "sysdock[all]"

# From source
git clone https://github.com/Kavyvachhani/SysDock.git
cd SysDock
pip install -e .
```

---

## Quick Start

```bash
sysdock              # open live dashboard (default — no subcommand needed)
sysdock dash         # same as above
sysdock start        # start metrics HTTP server on :5010
sysdock status       # one-shot snapshot (rich table)
sysdock status --json               # raw JSON
sysdock status --section docker     # Docker only
sysdock check        # verify all dependencies
```

### On EC2 — one-step install
```bash
sudo bash install.sh          # auto-installs Python, pip, sysdock + systemd service
```

---

## HTTP API

```bash
curl http://localhost:5010/health
curl http://localhost:5010/
curl -N http://localhost:5010/stream   # live SSE stream
```

| Endpoint | Description |
|----------|-------------|
| `GET /` | Full JSON snapshot — all metrics |
| `GET /stream` | Server-Sent Events — pushes every 5s |
| `GET /health` | `{"status": "ok"}` |

---

## Metric Accuracy

| Metric | Method |
|--------|--------|
| CPU % | 1-second sampling (matches htop) |
| RAM used | `total − free − buffers − cached` (htop formula) |
| Docker CPU | `(cpu_delta / sys_delta) × nCPUs × 100` (matches `docker stats`) |
| Docker memory | Subtracts `inactive_file` (cgroups v2) / `cache` (cgroups v1) |

---

## CLI Reference

```
sysdock             → live dashboard (default)
sysdock dash        → live dashboard (with --refresh option)
sysdock start       → HTTP metrics server [--port 5010] [--host 0.0.0.0]
sysdock status      → snapshot [--section system|disk|processes|network|docker|security|all] [--json]
sysdock check       → dependency check
sysdock install     → systemd service (requires root)
sysdock uninstall   → remove service (requires root)
sysdock --version   → 1.1.0
```

---

## Project Structure

```
SysDock/
├── pyproject.toml              pip package config (entry point: sysdock)
├── setup.py                    legacy pip fallback
├── MANIFEST.in
├── install.sh                  one-step Linux installer
├── test_sysdock.py             self-test suite
├── SETUP_GUIDE.md              full setup + PyPI publishing guide
├── EC2_DEPLOY_GUIDE.md         EC2 transfer + test + deploy guide
└── infravision_agent/
    ├── cli.py                  sysdock CLI (auto-launches dashboard)
    ├── server.py               HTTP server on port 5010
    ├── collectors/
    │   ├── system.py           CPU / RAM / load / uptime
    │   ├── disk.py             partitions + I/O
    │   ├── processes.py        top processes
    │   ├── network.py          interfaces + connections
    │   ├── docker_collector.py container stats (SDK + CLI fallback)
    │   └── security.py         Falco / SSH / fail2ban
    └── display/
        └── dashboard.py        Rich live TUI dashboard
```

---

## Compatibility

| Distro | Status |
|--------|--------|
| Ubuntu 20.04 / 22.04 / 24.04 | ✅ |
| Debian 10 / 11 / 12 | ✅ |
| Amazon Linux 2 / 2023 | ✅ |
| CentOS 7 / Stream 8 / 9 | ✅ |
| RHEL 7 / 8 / 9 | ✅ |
| Alpine Linux | ✅ |
| Arch Linux | ✅ |

**Python 3.6 – 3.12.** Requires Linux `/proc` filesystem.

---

## Security Note

When exposing the HTTP API, restrict port 5010 to your monitoring server only:

```bash
aws ec2 authorize-security-group-ingress \
  --group-id sg-xxxxxxxxxx \
  --protocol tcp --port 5010 \
  --cidr <monitoring-server-ip>/32
```

---

## License

MIT © 2026 [Kavyvachhani](https://github.com/Kavyvachhani)
