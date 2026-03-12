#!/usr/bin/env bash
# =============================================================
#  SysDock — Universal Linux Installer
#  Supports: Ubuntu, Debian, CentOS, RHEL, Amazon Linux,
#            Fedora, Arch Linux, Alpine Linux, Raspberry Pi OS
#
#  Usage:
#    sudo bash install.sh
#    sudo bash install.sh --port 5010 --falco
#    sudo bash install.sh --uninstall
#
#  Options:
#    --port PORT     metrics port (default: 5010)
#    --falco         also start Falco security container
#    --no-service    skip systemd registration
#    --uninstall     remove agent and service
# =============================================================
set -euo pipefail

PORT=5010; INSTALL_FALCO=false; NO_SERVICE=false; UNINSTALL=false

RED='\033[0;31m' GRN='\033[0;32m' YLW='\033[1;33m' CYN='\033[0;36m' NC='\033[0m'
ok()   { echo -e "${GRN}[OK]${NC}  $1"; }
warn() { echo -e "${YLW}[!!]${NC}  $1"; }
die()  { echo -e "${RED}[ER]${NC}  $1"; exit 1; }
step() { echo -e "\n${CYN}==> $1${NC}"; }

while [[ $# -gt 0 ]]; do
  case "$1" in
    --port)       PORT="$2"; shift 2 ;;
    --falco)      INSTALL_FALCO=true; shift ;;
    --no-service) NO_SERVICE=true;    shift ;;
    --uninstall)  UNINSTALL=true;     shift ;;
    *) warn "Unknown arg: $1"; shift ;;
  esac
done

[[ "$EUID" -ne 0 ]] && die "Run as root:  sudo bash install.sh"

# ── Uninstall ─────────────────────────────────────────────────────────────────
if [[ "$UNINSTALL" == true ]]; then
  step "Removing SysDock"
  systemctl stop     sysdock 2>/dev/null || true
  systemctl disable  sysdock 2>/dev/null || true
  rm -f /etc/systemd/system/sysdock.service
  rm -f /usr/local/bin/sysdock
  pip3 uninstall -y sysdock 2>/dev/null || true
  systemctl daemon-reload 2>/dev/null || true
  ok "SysDock removed."
  exit 0
fi

echo -e "${CYN}"
echo "╔══════════════════════════════════════╗"
echo "║         SysDock  Installer           ║"
echo "╚══════════════════════════════════════╝"
echo -e "${NC}"

# ── Detect distro / package manager ───────────────────────────────────────────
step "Detecting OS"
PKG_MGR=""
if   command -v apt-get &>/dev/null; then PKG_MGR="apt"
elif command -v dnf     &>/dev/null; then PKG_MGR="dnf"
elif command -v yum     &>/dev/null; then PKG_MGR="yum"
elif command -v pacman  &>/dev/null; then PKG_MGR="pacman"
elif command -v apk     &>/dev/null; then PKG_MGR="apk"
fi
OS=$(cat /etc/os-release 2>/dev/null | grep PRETTY_NAME | cut -d= -f2 | tr -d '"' || echo "Linux")
ok "OS: $OS  |  pkg-mgr: ${PKG_MGR:-none}"

# ── Python 3 ──────────────────────────────────────────────────────────────────
step "Checking Python 3.6+"
PY=""
for candidate in python3 python3.12 python3.11 python3.10 python3.9 python3.8 python3.7 python3.6; do
  if command -v "$candidate" &>/dev/null; then
    ver=$("$candidate" -c "import sys; print('{}.{}'.format(*sys.version_info[:2]))" 2>/dev/null)
    maj=${ver%%.*}; min=${ver##*.}
    if [[ "$maj" -ge 3 && "$min" -ge 6 ]]; then PY="$candidate"; break; fi
  fi
done

if [[ -z "$PY" ]]; then
  warn "Python 3.6+ not found — installing..."
  case "$PKG_MGR" in
    apt)    apt-get update -qq && apt-get install -y python3 python3-pip ;;
    dnf)    dnf install -y python3 python3-pip ;;
    yum)    yum install -y python3 python3-pip ;;
    pacman) pacman -Sy --noconfirm python python-pip ;;
    apk)    apk add --no-cache python3 py3-pip ;;
    *) die "Cannot auto-install Python. Please install Python 3.6+ manually." ;;
  esac
  PY=$(command -v python3)
fi
ok "Python: $($PY --version)"

# ── pip ───────────────────────────────────────────────────────────────────────
step "Checking pip"
if ! $PY -m pip --version &>/dev/null 2>&1; then
  warn "pip not found — installing..."
  case "$PKG_MGR" in
    apt)    apt-get install -y python3-pip ;;
    dnf)    dnf install -y python3-pip ;;
    yum)    yum install -y python3-pip ;;
    apk)    apk add --no-cache py3-pip ;;
    pacman) pacman -Sy --noconfirm python-pip ;;
    *)
      curl -fsSL https://bootstrap.pypa.io/get-pip.py -o /tmp/get-pip.py
      $PY /tmp/get-pip.py
      ;;
  esac
fi
ok "pip: $($PY -m pip --version | cut -d' ' -f2)"

# ── Install sysdock ───────────────────────────────────────────────────────────
step "Installing SysDock"
SCRIPT_DIR="$(cd "$(dirname "${BASH_SOURCE[0]}")" && pwd)"

_pip_install() {
  $PY -m pip install --break-system-packages "$@" 2>/dev/null \
    || $PY -m pip install "$@"
}

if [[ -f "$SCRIPT_DIR/setup.py" || -f "$SCRIPT_DIR/pyproject.toml" ]]; then
  _pip_install "$SCRIPT_DIR"
else
  # Install from PyPI
  _pip_install sysdock
fi

# Optional docker-py for live container stats
_pip_install "docker>=5.0.0" 2>/dev/null \
  || warn "docker-py not installed (docker CLI fallback will be used)"

# Ensure the CLI wrapper exists
if ! command -v sysdock &>/dev/null; then
  cat > /usr/local/bin/sysdock << WRAPPER
#!/bin/bash
exec $PY -m infravision_agent "\$@"
WRAPPER
  chmod +x /usr/local/bin/sysdock
fi
ok "sysdock installed at $(command -v sysdock)"

# ── Falco (optional) ──────────────────────────────────────────────────────────
if [[ "$INSTALL_FALCO" == true ]]; then
  step "Installing Falco security container"
  if ! command -v docker &>/dev/null; then
    warn "Docker not found — installing..."
    curl -fsSL https://get.docker.com | bash
    systemctl enable --now docker
  fi
  if docker ps --format '{{.Names}}' 2>/dev/null | grep -q falco; then
    ok "Falco already running"
  else
    docker pull falcosecurity/falco:master-debian
    docker run -d --name falco --restart unless-stopped --privileged \
      -v /var/run/docker.sock:/host/var/run/docker.sock \
      -v /dev:/host/dev \
      -v /proc:/host/proc:ro \
      -v /boot:/host/boot:ro \
      -v /lib/modules:/host/lib/modules:ro \
      -v /usr:/host/usr:ro \
      -v /etc:/host/etc:ro \
      falcosecurity/falco:master-debian \
        -o "log_stderr=true" -o "log_level=info"
    ok "Falco started"
  fi
fi

# ── Systemd service ───────────────────────────────────────────────────────────
if [[ "$NO_SERVICE" == false ]]; then
  step "Installing systemd service on port $PORT"
  if command -v systemctl &>/dev/null && systemctl --version &>/dev/null 2>&1; then
    IV_BIN=$(command -v sysdock 2>/dev/null || echo "$PY -m infravision_agent")
    cat > /etc/systemd/system/sysdock.service << SVC
[Unit]
Description=SysDock Monitoring Agent
After=network.target

[Service]
Type=simple
ExecStart=${IV_BIN} start --port ${PORT}
Restart=always
RestartSec=10
StandardOutput=journal
StandardError=journal
Environment=PYTHONUNBUFFERED=1

[Install]
WantedBy=multi-user.target
SVC
    systemctl daemon-reload
    systemctl enable  sysdock
    systemctl restart sysdock
    ok "Service started: sysdock"
  else
    warn "systemd not available — starting in background"
    nohup sysdock start --port "$PORT" >> /var/log/sysdock.log 2>&1 &
    echo $! > /var/run/sysdock.pid
    ok "Agent running (PID $(cat /var/run/sysdock.pid)) | tail -f /var/log/sysdock.log"
  fi
fi

# ── Open firewall (best-effort) ───────────────────────────────────────────────
command -v ufw          &>/dev/null && ufw allow "$PORT/tcp" comment "sysdock" 2>/dev/null && ok "ufw: opened $PORT" || true
command -v firewall-cmd &>/dev/null && firewall-cmd --permanent --add-port="$PORT/tcp" 2>/dev/null && firewall-cmd --reload 2>/dev/null && ok "firewalld: opened $PORT" || true

# ── Verify ────────────────────────────────────────────────────────────────────
step "Verifying"
sleep 3
if curl -sf "http://127.0.0.1:${PORT}/health" >/dev/null 2>&1; then
  ok "Agent responding on port $PORT"
  curl -s "http://127.0.0.1:${PORT}/health"; echo
else
  warn "Not yet responding — check: journalctl -u sysdock -n 30"
fi

echo ""
echo -e "${GRN}Done!${NC}"
echo "  Dashboard: sysdock"
echo "  Metrics  : curl http://$(hostname -I | awk '{print $1}'):${PORT}/"
echo "  Stream   : curl -N http://$(hostname -I | awk '{print $1}'):${PORT}/stream"
echo "  Logs     : journalctl -u sysdock -f"
echo ""
echo -e "${YLW}  Security group: allow TCP $PORT only from your monitoring server IP${NC}"
