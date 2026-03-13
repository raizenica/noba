#!/bin/bash
# noba-daily-digest.sh – Send daily summary email

set -euo pipefail

SCRIPT_DIR="$(cd "$(dirname "${BASH_SOURCE[0]}")" && pwd)"
# shellcheck source=/dev/null
# shellcheck source=/dev/null
source "$SCRIPT_DIR/noba-lib.sh"

# -------------------------------------------------------------------
# Default configuration
# -------------------------------------------------------------------
EMAIL="${EMAIL:-strikerke@gmail.com}"
LOG_DIR="${LOG_DIR:-$HOME/.local/share/noba}"
DRY_RUN=false

# -------------------------------------------------------------------
# Load user configuration (if any)
# -------------------------------------------------------------------
load_config
if [ "$CONFIG_LOADED" = true ]; then
    EMAIL="$(get_config ".email" "$EMAIL")"
    logs_dir="$(get_config ".logs.dir" "$HOME/.local/share/noba")"
    logs_dir="${logs_dir/#\~/$HOME}"
    LOG_DIR="$logs_dir"
fi

# -------------------------------------------------------------------
# Helper functions
# -------------------------------------------------------------------
show_version() {
    echo "noba-daily-digest.sh version 1.0"
    exit 0
}

show_help() {
    cat <<EOF
Usage: $0 [OPTIONS]

Generate and send a daily summary email with system status.

Options:
  -e, --email ADDR    Send digest to this email (default: $EMAIL)
  -n, --dry-run       Show digest on stdout without sending email
  --help              Show this help message
  --version           Show version information
EOF
    exit 0
}

# -------------------------------------------------------------------
# Parse arguments
# -------------------------------------------------------------------
PARSED_ARGS=$(getopt -o e:n -l email:,dry-run,help,version -- "$@")
if ! some_command; then
    show_help
fi
eval set -- "$PARSED_ARGS"

while true; do
    case "$1" in
        -e|--email)    EMAIL="$2"; shift 2 ;;
        -n|--dry-run)  DRY_RUN=true; shift ;;
        --help)        show_help ;;
        --version)     show_version ;;
        --)            shift; break ;;
        *)             break ;;
    esac
done

# -------------------------------------------------------------------
# Pre-flight checks
# -------------------------------------------------------------------
check_deps tail grep date hostname
# Optional: mail command – we'll check at send time

mkdir -p "$LOG_DIR"

# -------------------------------------------------------------------
# Generate digest
# -------------------------------------------------------------------
digest=$(mktemp)

{
    echo "Daily Digest for $(hostname) – $(date)"
    echo ""
    echo "=== Last Backup ==="
    if [ -f "$LOG_DIR/backup-to-nas.log" ]; then
        tail -5 "$LOG_DIR/backup-to-nas.log" 2>/dev/null | sed 's/\x1b\[[0-9;]*m//g' || echo "No backup entries"
    else
        echo "No backup log found."
    fi
    echo ""
    echo "=== Disk Warnings ==="
    if [ -f "$LOG_DIR/disk-sentinel.log" ]; then
        tail -5 "$LOG_DIR/disk-sentinel.log" 2>/dev/null | grep -E "WARNING|exceeded" || echo "None"
    else
        echo "No disk sentinel log."
    fi
    echo ""
    echo "=== Downloads Organized Yesterday ==="
    if [ -f "$LOG_DIR/download-organizer.log" ]; then
        yesterday=$(date -d 'yesterday' +%Y-%m-%d 2>/dev/null || date -v-1d +%Y-%m-%d 2>/dev/null)
        grep "$yesterday" "$LOG_DIR/download-organizer.log" 2>/dev/null || echo "None"
    else
        echo "No organizer log."
    fi
    echo ""
    echo "=== System Updates ==="
    if command -v dnf &>/dev/null; then
        dnf_updates=$(dnf check-update -q 2>/dev/null | wc -l)
        echo "DNF updates: $dnf_updates"
    fi
    if command -v flatpak &>/dev/null; then
        flatpak_updates=$(flatpak remote-ls --updates 2>/dev/null | wc -l)
        echo "Flatpak updates: $flatpak_updates"
    fi
} > "$digest"

# -------------------------------------------------------------------
# Output or send
# -------------------------------------------------------------------
if [ "$DRY_RUN" = true ]; then
    cat "$digest"
    log_info "Dry run – digest printed to stdout, not emailed."
else
    if command -v mail &>/dev/null; then
        mail -s "Daily Digest $(date +%Y-%m-%d)" "$EMAIL" < "$digest"
        log_info "Digest sent to $EMAIL"
    elif command -v mutt &>/dev/null; then
        mutt -s "Daily Digest $(date +%Y-%m-%d)" "$EMAIL" < "$digest"
        log_info "Digest sent to $EMAIL via mutt"
    else
        log_error "No mail program found – cannot send email."
        rm -f "$digest"
        exit 1
    fi
fi

rm -f "$digest"
