#!/bin/bash
SCRIPT_DIR="$(cd "$(dirname "${BASH_SOURCE[0]}")" && pwd)"
source "$SCRIPT_DIR/noba-lib.sh"

# Load configuration
load_config
if [ "$CONFIG_LOADED" = true ]; then
    true
    # Override defaults with config values (script-specific)
    # Example:
    # VAR=$(get_config ".${script%.sh}.var" "$VAR")
fi

show_help() {
    cat <<EOF
Usage: $(basename source "$SCRIPT_DIR/noba-lib.sh") [OPTIONS]

Options:
  --help        Show this help message
  --version     Show version information
EOF
    exit 0
}

show_version() {
    echo "$(basename source "$SCRIPT_DIR/noba-lib.sh") version 1.0"
    exit 0
}

# noba-daily-digest.sh – Send daily summary email

# Load configuration
load_config
if [ "$CONFIG_LOADED" = true ]; then
    true
    # Override defaults with config values (script-specific)
    # Example:
    # VAR=$(get_config ".${script%.sh}.var" "$VAR")
fi

EMAIL="${EMAIL:-strikerke@gmail.com}"
LOG_DIR="$HOME/.local/share"

digest=$(mktemp)
{
    echo "Daily Digest for $(hostname) – $(date)"
    echo ""
    echo "=== Last Backup ==="
    tail -5 "$LOG_DIR/backup-to-nas.log" 2>/dev/null || echo "No backup log"
    echo ""
    echo "=== Disk Warnings ==="
    tail -5 "$LOG_DIR/disk-sentinel.log" 2>/dev/null | grep -E "WARNING|exceeded" || echo "None"
    echo ""
    echo "=== Downloads Organized Yesterday ==="
    grep "$(date -d 'yesterday' +%Y-%m-%d)" "$LOG_DIR/download-organizer.log" 2>/dev/null || echo "None"
    echo ""
    echo "=== System Updates ==="
    echo "DNF updates: $(dnf check-update -q 2>/dev/null | wc -l)"
    echo "Flatpak updates: $(flatpak remote-ls --updates 2>/dev/null | wc -l)"
} > "$digest"

mail -s "Daily Digest $(date +%Y-%m-%d)" "$EMAIL" < "$digest"
rm "$digest"
