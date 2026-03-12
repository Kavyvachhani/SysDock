# SysDock — EC2 Deploy & Test Guide

## Step-by-Step: From Your Windows Machine to EC2

---

## Part 1 — Transfer the Project to EC2

### Option A: SCP (recommended — transfer the wheel file)
The wheel `dist/sysdock-1.1.0-py3-none-any.whl` is a self-contained installer.

Open **PowerShell** on your Windows machine and run:
```powershell
# Replace with your key file path and EC2 public IP / DNS
$KEY = "C:\Users\Kavy\.ssh\your-key.pem"
$EC2 = "ubuntu@ec2-xx-xx-xx-xx.compute-1.amazonaws.com"
$PROJ = "C:\Users\Kavy\Desktop\infravision-agent-pip-ready (2)\infravision-agent"

# Transfer the pre-built wheel + test script
scp -i $KEY "$PROJ\dist\sysdock-1.1.0-py3-none-any.whl" ${EC2}:~/
scp -i $KEY "$PROJ\test_sysdock.py"                      ${EC2}:~/
scp -i $KEY "$PROJ\SETUP_GUIDE.md"                       ${EC2}:~/
```

### Option B: SCP the full source folder
```powershell
$KEY  = "C:\Users\Kavy\.ssh\your-key.pem"
$EC2  = "ubuntu@ec2-xx-xx-xx-xx.compute-1.amazonaws.com"
$PROJ = "C:\Users\Kavy\Desktop\infravision-agent-pip-ready (2)\infravision-agent"

scp -r -i $KEY $PROJ ${EC2}:~/sysdock
```

### Option C: Git (cleanest for ongoing work)
```powershell
# On Windows — push to GitHub first
cd "C:\Users\Kavy\Desktop\infravision-agent-pip-ready (2)\infravision-agent"
git init
git add .
git commit -m "SysDock v1.1.0"
git remote add origin https://github.com/YOUR_USERNAME/sysdock.git
git push -u origin main
```
Then on EC2:
```bash
git clone https://github.com/YOUR_USERNAME/sysdock.git
cd sysdock
```

---

## Part 2 — Set Up EC2 Instance

### Connect to your EC2 instance
```bash
ssh -i your-key.pem ubuntu@ec2-xx-xx-xx-xx.compute-1.amazonaws.com
```

### 2.1 — Update and install Python
```bash
sudo apt-get update -y
sudo apt-get install -y python3 python3-pip python3-venv git curl
python3 --version    # should be 3.8+ on modern AMIs
```

### 2.2 — (Optional but recommended) Create a virtual environment
```bash
python3 -m venv ~/.venv/sysdock
source ~/.venv/sysdock/bin/activate
```

---

## Part 3 — Install SysDock on EC2

### If you transferred the wheel (Option A):
```bash
pip install ~/sysdock-1.1.0-py3-none-any.whl
pip install docker     # optional: richer Docker metrics
```

### If you transferred the source folder (Option B):
```bash
cd ~/sysdock
pip install -e .
pip install docker     # optional
```

### If you cloned from git (Option C):
```bash
cd ~/sysdock
pip install -e .
pip install docker     # optional
```

### Verify the CLI is registered:
```bash
sysdock --version
# Should print: SysDock, version 1.1.0

which sysdock
# Should print: /home/ubuntu/.venv/sysdock/bin/sysdock  (or similar)
```

---

## Part 4 — Run the Test Suite

```bash
# Full test (takes ~10 seconds for the CPU 1s samples):
python3 ~/test_sysdock.py

# Quick test (skips 1s CPU wait, faster but less accurate CPU check):
python3 ~/test_sysdock.py --quick

# With Docker container stat checks (if Docker is running):
python3 ~/test_sysdock.py --docker

# Expected output:
# ── 1. Package imports ─────────────────────────────
# [PASS] Import infravision_agent package
# [PASS] Import system collector
# ...
# ═══════════════════════════════════════════════════
#   SysDock Test Results: 25 passed, 0 failed, 0 skipped / 25 total
# ═══════════════════════════════════════════════════
```

### Compare with htop after tests pass:
```bash
# Install htop if needed:
sudo apt-get install -y htop

# Run both side-by-side in two terminals:
htop                          # Terminal 1
sysdock status --section system   # Terminal 2  (see CPU%, RAM used)
```

---

## Part 5 — Run the Live Dashboard

```bash
sysdock          # Opens live dashboard (Ctrl+C to exit)
```

> **Note:** The dashboard requires a terminal that is at least 120 columns wide.
> If it looks garbled, try: `export COLUMNS=150` before running.

---

## Part 6 — Test the Metrics HTTP Server

```bash
# Start server in background:
sysdock start --port 5010 &

# Query the API:
curl http://localhost:5010/health
curl http://localhost:5010/ | python3 -m json.tool | head -60
curl -N http://localhost:5010/stream   # live stream (Ctrl+C to stop)
```

### Open port 5010 in AWS Security Group:
In the AWS Console → EC2 → Security Groups → Inbound rules → Add rule:
- Type: Custom TCP
- Port: 5010
- Source: **Your IP** (not 0.0.0.0/0 — for security)

Then test from your Windows machine:
```powershell
$EC2_IP = "xx.xx.xx.xx"
Invoke-WebRequest "http://${EC2_IP}:5010/health"
```

---

## Part 7 — Install as a Permanent Systemd Service

Once tests pass, install SysDock to run on boot:
```bash
sudo sysdock install              # uses port 5010
sudo systemctl status sysdock     # verify it's running
journalctl -u sysdock -f          # live logs
```

---

## Part 8 — Docker Metrics Test (if Docker is on EC2)

```bash
# Install Docker on EC2 (if not already):
curl -fsSL https://get.docker.com | sudo bash
sudo usermod -aG docker ubuntu
newgrp docker          # or re-login

# Start a test container:
docker run -d --name test-nginx nginx

# Now test Docker metrics:
docker stats --no-stream           # reference values
sysdock status --section docker    # should match

# Full Docker test:
python3 ~/test_sysdock.py --docker
```

---

## Part 9 — Publish to PyPI (after all tests pass)

### 9.1 — Create a PyPI account
Go to https://pypi.org and register.

### 9.2 — Get an API token
PyPI → Account Settings → API tokens → Create token → scope: Entire account

### 9.3 — Install Twine and upload
```bash
pip install twine

# If you transferred the wheel:
twine upload ~/sysdock-1.1.0-py3-none-any.whl

# If you have the full source on EC2:
cd ~/sysdock
pip install build
python -m build
twine upload dist/*

# Twine will prompt:
#   Username: __token__
#   Password: <paste your PyPI API token>
```

### 9.4 — Verify the PyPI install
```bash
pip install sysdock               # fresh install from PyPI
sysdock --version                 # should print 1.1.0
sysdock                           # opens dashboard
```

---

## Quick Reference Cheat Sheet

| Task | Command |
|------|---------|
| Open dashboard | `sysdock` |
| One-shot snapshot | `sysdock status` |
| JSON output | `sysdock status --json` |
| Start HTTP server | `sysdock start` |
| Check dependencies | `sysdock check` |
| Run all tests | `python3 test_sysdock.py` |
| Install as service | `sudo sysdock install` |
| View service logs | `journalctl -u sysdock -f` |
| Uninstall service | `sudo sysdock uninstall` |
| Uninstall package | `pip uninstall sysdock` |
