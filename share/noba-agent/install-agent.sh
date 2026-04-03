#!/usr/bin/env bash
# Copyright (c) 2024-2026 Kevin Van Nieuwenhove. All rights reserved.
# NOBA Command Center — Licensed under Apache 2.0.
# NOBA Agent — Installer for remote nodes
# Works on: Debian/Ubuntu, Fedora/RHEL, Raspberry Pi OS, TrueNAS SCALE
#
# Usage:
#   bash install-agent.sh http://noba-server:8080 YOUR_AGENT_KEY
#   bash install-agent.sh  # Interactive prompts
set -euo pipefail

INSTALL_DIR="/opt/noba-agent"
CONFIG="/etc/noba-agent.yaml"
SERVICE="noba-agent"
SCRIPT_DIR="$(cd "$(dirname "${BASH_SOURCE[0]}")" && pwd)"

RED='\033[31m'; GREEN='\033[32m'; YELLOW='\033[33m'; NC='\033[0m'
_ok()   { echo -e "${GREEN}[ok]${NC} $*"; }
_warn() { echo -e "${YELLOW}[!]${NC} $*"; }
_err()  { echo -e "${RED}[x]${NC} $*" >&2; }

echo ""
echo "  NOBA Agent Installer"
echo "  ─────────────────────"
echo ""

NOBA_SERVER="${1:-}"
NOBA_KEY="${2:-}"

if [[ -z "$NOBA_SERVER" ]]; then read -rp "  NOBA Server URL: " NOBA_SERVER; fi
if [[ -z "$NOBA_KEY" ]]; then read -rp "  Agent API Key: " NOBA_KEY; fi

if [[ -z "$NOBA_SERVER" || -z "$NOBA_KEY" ]]; then
    _err "Server URL and API key are required"
    exit 1
fi

# Check Python
PYTHON=""
for py in python3 python; do
    if command -v "$py" &>/dev/null; then
        ver=$("$py" -c "import sys; print(sys.version_info >= (3, 6))" 2>/dev/null)
        if [[ "$ver" == "True" ]]; then PYTHON="$py"; break; fi
    fi
done
[[ -z "$PYTHON" ]] && { _err "Python 3.6+ required"; exit 1; }
_ok "Python: $($PYTHON --version 2>&1)"

# Try to install psutil (optional)
if ! $PYTHON -c "import psutil" 2>/dev/null; then
    _warn "psutil not found — trying to install..."
    if command -v apt-get &>/dev/null; then
        sudo apt-get install -y python3-psutil &>/dev/null && _ok "psutil installed" || _warn "Using /proc fallback"
    elif command -v dnf &>/dev/null; then
        sudo dnf install -y python3-psutil &>/dev/null && _ok "psutil installed" || _warn "Using /proc fallback"
    else
        _warn "Agent will use /proc fallback (zero dependencies)"
    fi
else
    _ok "psutil available"
fi

# Deploy
sudo mkdir -p "$INSTALL_DIR"
sudo cp "$SCRIPT_DIR/agent.pyz" "$INSTALL_DIR/agent.pyz"
sudo chmod +x "$INSTALL_DIR/agent.pyz"
_ok "Agent deployed to $INSTALL_DIR"

# Config
HOSTNAME=$(hostname)
TAGS=""
[[ "$HOSTNAME" == *nas* ]] && TAGS="storage"
[[ "$HOSTNAME" == *dns* ]] && TAGS="dns"
[[ "$HOSTNAME" == *ha* ]] && TAGS="automation"

sudo tee "$CONFIG" > /dev/null <<EOF
server: $NOBA_SERVER
api_key: $NOBA_KEY
interval: 30
hostname: $HOSTNAME
tags: $TAGS
EOF
sudo chmod 600 "$CONFIG"
_ok "Config: $CONFIG (mode 600)"

# Test
echo ""
if $PYTHON "$INSTALL_DIR/agent.pyz" --config "$CONFIG" --once 2>&1; then
    _ok "Test report successful!"
else
    _warn "Test failed — agent will retry with backoff"
fi

# Systemd
if command -v systemctl &>/dev/null; then
    sudo tee /etc/systemd/system/noba-agent.service > /dev/null <<EOF
[Unit]
Description=NOBA Agent
After=network-online.target
Wants=network-online.target
[Service]
Type=simple
ExecStart=$PYTHON $INSTALL_DIR/agent.pyz --config $CONFIG
Restart=always
RestartSec=30
StandardOutput=journal
StandardError=journal
SyslogIdentifier=noba-agent
[Install]
WantedBy=multi-user.target
EOF
    sudo systemctl daemon-reload
    sudo systemctl enable --now "$SERVICE"
    _ok "Service enabled and running"
else
    _warn "No systemd — run manually: $PYTHON $INSTALL_DIR/agent.pyz --config $CONFIG"
fi

echo ""
_ok "Done!"
echo ""
