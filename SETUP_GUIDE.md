# SysDock — Setup Guide

**SysDock** is a lightweight Linux monitoring agent with a live terminal dashboard, Docker metrics, and a pip-installable CLI command.

---

## Table of Contents
1. [Prerequisites](#1-prerequisites)
2. [Install Locally from Source](#2-install-locally-from-source)
3. [Using SysDock](#3-using-sysdock)
4. [Install Docker Support](#4-install-docker-support)
5. [Build a Distributable Package](#5-build-a-distributable-package)
6. [Publish to PyPI](#6-publish-to-pypi)
7. [Install as a Systemd Service](#7-install-as-a-systemd-service)
8. [One-Step Linux Installer Script](#8-one-step-linux-installer-script)
9. [Uninstall](#9-uninstall)
10. [CLI Reference](#10-cli-reference)

---

## 1. Prerequisites

| Requirement | Version |
|-------------|---------|
| Python      | 3.6+    |
| pip         | 21+     |
| Linux       | Any distribution with `/proc` filesystem |
| Docker      | Optional — enables live container stats |

Check your Python version:
```bash
python3 --version
```

---

## 2. Install Locally from Source

### Step 1 — Clone or copy the project
```bash
# If you have git:
git clone https://github.com/your-org/sysdock.git
cd sysdock

# Or unzip / copy the project folder and cd into it:
cd infravision-agent
```

### Step 2 — (Optional) Create a virtual environment
```bash
python3 -m venv .venv
source .venv/bin/activate
```

### Step 3 — Install in editable (development) mode
```bash
pip install -e .
```

This registers the `sysdock` command in your PATH. You can now run:
```bash
sysdock
```

### Step 4 — Install with all optional dependencies
```bash
# With Docker SDK support (recommended):
pip install -e ".[docker]"

# With everything (Docker + Flask server):
pip install -e ".[all]"
```

---

## 3. Using SysDock

### Open the live dashboard (default)
```bash
sysdock
```
Just type `sysdock` and press Enter — the live dashboard opens immediately, like htop.

### Open the dashboard explicitly
```bash
sysdock dash
sysdock dash --refresh 2   # refresh every 2 seconds (default: 3)
```

### One-shot status snapshot
```bash
sysdock status             # pretty table output
sysdock status --json      # raw JSON
sysdock status --section cpu       # only CPU section
sysdock status --section docker    # only Docker
```
Available sections: `system`, `disk`, `processes`, `network`, `docker`, `security`, `all`

### Start the metrics HTTP server
```bash
sysdock start                       # default: 0.0.0.0:5010
sysdock start --port 8080           # custom port
sysdock start --host 127.0.0.1     # localhost only

# Query the API:
curl http://localhost:5010/
curl http://localhost:5010/health
curl -N http://localhost:5010/stream   # live JSON stream
```

### Check all dependencies
```bash
sysdock check
```

---

## 4. Install Docker Support

Install the `docker-py` SDK for richer container metrics (CPU, memory, network I/O):
```bash
pip install "docker>=5.0.0"
```

Without the SDK, SysDock falls back to the `docker` CLI automatically — both give accurate stats.

To verify Docker is detected:
```bash
sysdock check           # "Docker daemon" row should show "running"
sysdock status --section docker
```

---

## 5. Build a Distributable Package

### Step 1 — Install the build tool
```bash
pip install build
```

### Step 2 — Build wheel + sdist
```bash
cd /path/to/infravision-agent    # project root (contains pyproject.toml)
python -m build
```

Output files will be in the `dist/` directory:
```
dist/
  sysdock-1.1.0.tar.gz        # source distribution
  sysdock-1.1.0-py3-none-any.whl  # wheel
```

### Step 3 — Install from the wheel
```bash
pip install dist/sysdock-1.1.0-py3-none-any.whl
```

### Step 4 — Verify
```bash
sysdock --version    # should print: SysDock, version 1.1.0
sysdock check
```

---

## 6. Publish to PyPI

### Step 1 — Create a PyPI account
Register at https://pypi.org/account/register/

### Step 2 — Install Twine
```bash
pip install twine
```

### Step 3 — Build the package
```bash
python -m build
```

### Step 4 — Upload to TestPyPI first (recommended)
```bash
twine upload --repository testpypi dist/*
```

Test install from TestPyPI:
```bash
pip install --index-url https://test.pypi.org/simple/ sysdock
sysdock --version
```

### Step 5 — Upload to real PyPI
```bash
twine upload dist/*
```

### Step 6 — Anyone can now install with:
```bash
pip install sysdock
pip install "sysdock[docker]"    # with Docker SDK
```

---

## 7. Install as a Systemd Service

Run as a persistent background service that auto-starts on boot:

```bash
sudo sysdock install                  # uses default port 5010
sudo sysdock install --port 8080      # custom port
```

Service management commands:
```bash
sudo systemctl status  sysdock
sudo systemctl restart sysdock
sudo systemctl stop    sysdock
sudo journalctl -u sysdock -f          # live logs
```

---

## 8. One-Step Linux Installer Script

The `install.sh` script handles everything automatically (Python, pip, sysdock, systemd service, firewall):

```bash
sudo bash install.sh                   # default port 5010
sudo bash install.sh --port 8080       # custom port
sudo bash install.sh --falco           # also install Falco security
sudo bash install.sh --no-service      # skip systemd registration
```

After installation:
```bash
sysdock                                # open live dashboard
curl http://localhost:5010/            # access metrics API
```

---

## 9. Uninstall

```bash
# Remove systemd service:
sudo sysdock uninstall

# Uninstall pip package:
pip uninstall sysdock

# Or using the install script:
sudo bash install.sh --uninstall
```

---

## 10. CLI Reference

```
Usage: sysdock [OPTIONS] COMMAND [ARGS]...

  SysDock — Linux / EC2 monitoring agent.
  Type 'sysdock' (no command) to open the live dashboard.

Options:
  --version   Show version and exit.
  --help      Show this message and exit.

Commands:
  dash        Open the live terminal dashboard (Ctrl+C to exit)
  start       Start the metrics HTTP server
  status      Print a one-shot status snapshot
  check       Verify all dependencies and system capabilities
  install     Install SysDock as a systemd service (requires root)
  uninstall   Remove the SysDock systemd service (requires root)
```

### Metrics HTTP API

| Endpoint        | Description                               |
|-----------------|-------------------------------------------|
| `GET /`         | Full JSON snapshot of all metrics         |
| `GET /health`   | Simple health check `{"status": "ok"}`    |
| `GET /stream`   | Newline-delimited live JSON stream        |
| `GET /metrics`  | Prometheus-compatible text format         |

---

## Notes on Metric Accuracy

- **CPU%** is measured with a 1-second sampling interval, matching htop's default method.
- **Memory used** = `total − free − buffers − cached (+ SReclaimable)` — this is the htop formula.
- **Docker CPU%** uses the same calculation as `docker stats`: `(cpu_delta / sys_delta) × nCPUs × 100`.
- **Docker memory** subtracts the page cache (`inactive_file` on cgroups v2, `cache` on cgroups v1), matching `docker stats` output exactly.
