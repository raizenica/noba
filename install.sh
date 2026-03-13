#!/bin/bash
# install.sh – Install Nobara Automation Suite

set -euo pipefail

INSTALL_DIR="${INSTALL_DIR:-$HOME/.local/bin}"
CONFIG_DIR="${CONFIG_DIR:-$HOME/.config/noba}"
SYSTEMD_USER_DIR="${SYSTEMD_USER_DIR:-$HOME/.config/systemd/user}"
SCRIPT_DIR="$(cd "$(dirname "${BASH_SOURCE[0]}")" && pwd)"
DRY_RUN=false

show_help() {
    cat <<HELP
Usage: $0 [OPTIONS]

Install Nobara Automation Suite.

Options:
  -d, --dir DIR       Installation directory (default: $INSTALL_DIR)
  -c, --config DIR    Configuration directory (default: $CONFIG_DIR)
  -s, --systemd DIR   Systemd user unit directory (default: $SYSTEMD_USER_DIR)
  -n, --dry-run       Show what would be done without copying
  --help              Show this help
HELP
    exit 0
}

while [[ $# -gt 0 ]]; do
    case $1 in
        -d|--dir)       INSTALL_DIR="$2"; shift 2 ;;
        -c|--config)    CONFIG_DIR="$2"; shift 2 ;;
        -s|--systemd)   SYSTEMD_USER_DIR="$2"; shift 2 ;;
        -n|--dry-run)   DRY_RUN=true; shift ;;
        --help)         show_help ;;
        *)              echo "Unknown option: $1" >&2; exit 1 ;;
    esac
done

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
    if [ "$DRY_RUN" = true ]; then
        echo "  Would copy $name to $INSTALL_DIR/"
    else
        cp "$script" "$INSTALL_DIR/"
        chmod +x "$INSTALL_DIR/$name"
        echo "  Copied $name"
    fi
done

# Create default config if missing
if [ ! -f "$CONFIG_DIR/config.yaml" ] && [ "$DRY_RUN" = false ]; then
    cat > "$CONFIG_DIR/config.yaml" <<CONFIG
# Nobara unified configuration
email: "your@email.com"

backup:
  dest: "/mnt/vnnas/backups/raizen"
  sources:
    - "/home/raizen/Documents"
    - "/home/raizen/Pictures"

disk:
  threshold: 85
  targets:
    - "/"
    - "/home"
  cleanup_enabled: true

logs:
  dir: "/home/raizen/.local/share/noba"
CONFIG
    echo "Created default config at $CONFIG_DIR/config.yaml"
elif [ "$DRY_RUN" = false ]; then
    echo "Config file already exists, skipping."
fi

# Copy systemd user units if they exist
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

if [ "$DRY_RUN" = false ]; then
    echo "Reloading systemd user daemon..."
    systemctl --user daemon-reload
fi

echo
echo "Installation complete."
if [ "$DRY_RUN" = false ]; then
    echo "You can now enable timers, e.g.:"
    echo "  systemctl --user enable --now disk-sentinel.timer"
    echo "Edit configuration: $CONFIG_DIR/config.yaml"
fi
