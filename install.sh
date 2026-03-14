#!/bin/bash
# install.sh – Smart installer for Nobara Automation Suite
# Version: 2.2.1

set -euo pipefail

# -------------------------------------------------------------------
# Default paths
# -------------------------------------------------------------------
INSTALL_DIR="${INSTALL_DIR:-$HOME/.local/bin}"
CONFIG_DIR="${CONFIG_DIR:-$HOME/.config/noba}"
SYSTEMD_USER_DIR="${SYSTEMD_USER_DIR:-$HOME/.config/systemd/user}"
SCRIPT_DIR="$(cd "$(dirname "${BASH_SOURCE[0]}")" && pwd)"
DRY_RUN=false
SKIP_DEPS=false

# -------------------------------------------------------------------
# Helper functions
# -------------------------------------------------------------------
show_help() {
    cat <<EOF
Usage: $0 [OPTIONS]

Install the Nobara Automation Suite.

Options:
  -d, --dir DIR      Installation directory (default: $INSTALL_DIR)
  -c, --config DIR   Configuration directory (default: $CONFIG_DIR)
  -s, --systemd DIR  Systemd user unit directory (default: $SYSTEMD_USER_DIR)
  --skip-deps        Skip dependency installation (useful for testing)
  -n, --dry-run      Show what would be done without copying
  --help             Show this help
EOF
    exit 0
}

# Parse arguments
while [[ $# -gt 0 ]]; do
    case $1 in
        -d|--dir)       INSTALL_DIR="$2"; shift 2 ;;
        -c|--config)    CONFIG_DIR="$2"; shift 2 ;;
        -s|--systemd)   SYSTEMD_USER_DIR="$2"; shift 2 ;;
        --skip-deps)    SKIP_DEPS=true; shift ;;
        -n|--dry-run)   DRY_RUN=true; shift ;;
        --help)         show_help ;;
        *) log_error "Invalid argument: $1"; exit 1 ;;
    esac
done

# -------------------------------------------------------------------
# OS detection
# -------------------------------------------------------------------
detect_os() {
    if [ -f /etc/os-release ]; then
        # shellcheck source=/dev/null
        . /etc/os-release
        OS_ID="$ID"
        # shellcheck disable=SC2153
        OS_NAME="$NAME"
    else
        OS_ID="unknown"
        OS_NAME="unknown"
    fi
    echo "Detected OS: $OS_NAME ($OS_ID)"
}

detect_os

# -------------------------------------------------------------------
# Dependency installation
# -------------------------------------------------------------------
install_deps() {
    if [ "$SKIP_DEPS" = true ]; then
        echo "Skipping dependency installation."
        return
    fi

    local deps=()
    case "$OS_ID" in
        fedora|nobara|rhel|centos)
            deps=(rsync rclone msmtp ImageMagick yq jq dialog psmisc lm_sensors lsof speedtest-cli)
            if [ "$DRY_RUN" = true ]; then
                echo "DRY RUN: Would install: sudo dnf install -y ${deps[*]}"
            else
                echo "Installing dependencies via dnf..."
                sudo dnf install -y "${deps[@]}"
            fi
            ;;
        debian|ubuntu|linuxmint|pop)
            deps=(rsync rclone msmtp imagemagick jq dialog psmisc lm-sensors lsof speedtest-cli)
            if [ "$DRY_RUN" = true ]; then
                echo "DRY RUN: Would install: sudo apt install -y ${deps[*]}"
            else
                echo "Installing dependencies via apt..."
                sudo apt update
                sudo apt install -y "${deps[@]}"
                if ! command -v yq &>/dev/null; then
                    echo "yq not found. Installing via snap if available..."
                    if command -v snap &>/dev/null; then
                        sudo snap install yq
                    else
                        echo "WARNING: yq not installed. Please install manually from https://github.com/mikefarah/yq"
                    fi
                fi
            fi
            ;;
        arch|manjaro|endeavouros)
            deps=(rsync rclone msmtp imagemagick yq jq dialog psmisc lm_sensors lsof speedtest-cli)
            if [ "$DRY_RUN" = true ]; then
                echo "DRY RUN: Would install: sudo pacman -S ${deps[*]}"
            else
                echo "Installing dependencies via pacman..."
                sudo pacman -Sy --noconfirm "${deps[@]}"
            fi
            ;;
        *)
            echo "WARNING: Unknown OS '$OS_ID'. Please install dependencies manually: rsync, rclone, msmtp, ImageMagick, yq, jq, dialog, psmisc, lm_sensors, lsof, speedtest-cli"
            ;;
    esac
}

install_deps

# -------------------------------------------------------------------
# Installation steps
# -------------------------------------------------------------------
echo "Installing Nobara Automation Suite to $INSTALL_DIR"
echo "Configuration directory: $CONFIG_DIR"
echo "Systemd user units: $SYSTEMD_USER_DIR"

if [ "$DRY_RUN" = true ]; then
    echo "DRY RUN – no files will be copied."
fi

# Create directories
if [ "$DRY_RUN" = false ]; then
    mkdir -p "$INSTALL_DIR" "$CONFIG_DIR" "$SYSTEMD_USER_DIR"
fi

# Copy scripts
echo "Copying scripts..."
for script in "$SCRIPT_DIR"/*.sh; do
    name=$(basename "$script")
    # Prevent the installer from installing itself
    if [[ "$name" == "install.sh" ]] || [[ "$name" == "noba-setup.sh" ]]; then
        continue
    fi

    if [ "$DRY_RUN" = true ]; then
        echo "  Would copy $name to $INSTALL_DIR/"
    else
        cp "$script" "$INSTALL_DIR/"
        chmod +x "$INSTALL_DIR/$name"
        echo "  Copied $name"
    fi
done

# Copy noba CLI wrapper
if [ -f "$SCRIPT_DIR/noba" ]; then
    if [ "$DRY_RUN" = true ]; then
        echo "  Would copy noba to $INSTALL_DIR/"
    else
        cp "$SCRIPT_DIR/noba" "$INSTALL_DIR/"
        chmod +x "$INSTALL_DIR/noba"
        echo "  Copied noba wrapper"
    fi
fi

# Create default config if missing
if [ ! -f "$CONFIG_DIR/config.yaml" ] && [ "$DRY_RUN" = false ]; then
    cat > "$CONFIG_DIR/config.yaml" <<CONFIG
# Nobara Automation Suite Unified Configuration
email: "strikerke@gmail.com"

logs:
  dir: "$HOME/.local/share"

backup:
  dest: "/mnt/vnnas/backups/raizen"
  retention_days: 7
  sources:
    - "$HOME/Documents"
    - "$HOME/Pictures"

cloud:
  remote: "mycloud:backups/raizen"
  rclone_opts: "-v --checksum --progress --fast-list"

disk:
  threshold: 85
  cleanup_enabled: true
  targets:
    - "/"
    - "$HOME"

web:
  port: 8080
  service_list:
    - backup-to-nas.service
    - organize-downloads.service
    - noba-web.service
    - syncthing.service

services:
  monitor:
    - sshd
    - docker
    - NetworkManager
  notify: true
CONFIG
    echo "Created default config at $CONFIG_DIR/config.yaml"
elif [ "$DRY_RUN" = false ]; then
    echo "Config file already exists, skipping generation."
fi

# Setup Bash Completions
BASHRC="$HOME/.bashrc"
COMPLETION_STR="source $INSTALL_DIR/noba-completion.sh"
if [ "$DRY_RUN" = false ] && [ -f "$INSTALL_DIR/noba-completion.sh" ]; then
    if grep -qF "$COMPLETION_STR" "$BASHRC" 2>/dev/null; then
        echo "Bash completions already wired in $BASHRC."
    else
        {
            echo ""
            echo "# Nobara Automation Suite Completions"
            echo "$COMPLETION_STR"
        } >> "$BASHRC"
        echo "Added Bash completions to $BASHRC."
    fi
fi

# Copy systemd user units
if [ -d "$SCRIPT_DIR/systemd" ]; then
    echo "Copying systemd user units..."
    for unit in "$SCRIPT_DIR"/systemd/*.{timer,service}; do
        if [ -f "$unit" ]; then
            name=$(basename "$unit")
            if [ "$DRY_RUN" = true ]; then
                echo "  Would copy $name to $SYSTEMD_USER_DIR/"
            else
                cp "$unit" "$SYSTEMD_USER_DIR/"
                echo "  Copied $name"
            fi
        fi
    done
else
    echo "No systemd units directory found; skipping."
fi

if [ "$DRY_RUN" = false ] && command -v systemctl &>/dev/null; then
    echo "Reloading systemd user daemon..."
    systemctl --user daemon-reload || true
fi

echo
echo "Installation complete."
if [ "$DRY_RUN" = false ]; then
    echo "Please open a new terminal or run 'source ~/.bashrc' to enable CLI completions."
    echo "You can now enable timers, e.g.:"
    echo "  systemctl --user enable --now disk-sentinel.timer"
    echo "Edit configuration: $CONFIG_DIR/config.yaml"
fi
