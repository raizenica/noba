#!/bin/bash
# noba-daily-digest.sh – Send daily summary email
# Improved version with robust error handling and consistent logging

set -euo pipefail

SCRIPT_DIR="$(cd "$(dirname "${BASH_SOURCE[0]}")" && pwd)"
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
load_config || true
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
    echo "noba-daily-digest.sh version 2.0 (improved)"
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
if ! PARSED_ARGS=$(getopt -o e:n -l email:,dry-run,help,version -- "$@"); then
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
mkdir -p "$LOG_DIR" || {
    log_error "Failed to create log directory $LOG_DIR"
    exit 1
}

# -------------------------------------------------------------------
# Generate digest
# -------------------------------------------------------------------
digest=$(mktemp) || {
    log_error "Failed to create temporary file"
    exit 1
}
trap 'rm -f "$digest"' EXIT

{
    echo "Daily Digest for $(hostname -s 2>/dev/null || hostname) – $(date)"
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
        # Compute yesterday's date in a portable way
        yesterday=$(date -d 'yesterday' +%Y-%m-%d 2>/dev/null || date -v-1d +%Y-%m-%d 2>/dev/null)
        if [ -n "$yesterday" ]; then
            grep "$yesterday" "$LOG_DIR/download-organizer.log" 2>/dev/null || echo "None"
        else
            echo "Unable to determine yesterday's date."
        fi
    else
        echo "No organizer log."
    fi
    echo ""
    echo "=== System Updates ==="
    if command -v dnf &>/dev/null; then
        dnf_updates=$(dnf check-update -q 2>/dev/null | wc -l)
        echo "DNF updates: $((dnf_updates > 0 ? dnf_updates : 0))"
    fi
    if command -v flatpak &>/dev/null; then
        flatpak_updates=$(flatpak remote-ls --updates 2>/dev/null | wc -l)
        echo "Flatpak updates: $((flatpak_updates > 0 ? flatpak_updates : 0))"
    fi
    echo ""
    echo "=== Recent Service Status ==="
    if command -v systemctl &>/dev/null; then
        # Show status of common user services (adjust as needed)
        for svc in backup-to-nas organize-downloads noba-web; do
            if systemctl --user is-active "$svc.service" &>/dev/null; then
                echo "$svc: active"
            else
                echo "$svc: inactive"
            fi
        done
    else
        echo "systemctl not available."
    fi
} > "$digest"

# -------------------------------------------------------------------
# Output or send
# -------------------------------------------------------------------
if [ "$DRY_RUN" = true ]; then
    cat "$digest"
    log_info "Dry run – digest printed to stdout, not emailed."
else
    # Try mail, then mutt
    if command -v mail &>/dev/null; then
        mail -s "Daily Digest $(date +%Y-%m-%d)" "$EMAIL" < "$digest"
        log_info "Digest sent to $EMAIL via mail"
    elif command -v mutt &>/dev/null; then
        mutt -s "Daily Digest $(date +%Y-%m-%d)" "$EMAIL" < "$digest"
        log_info "Digest sent to $EMAIL via mutt"
    else
        log_error "No mail program found – cannot send email."
        exit 1
    fi
fi

# Temp file automatically removed by trap
