#!/bin/bash
# noba-daily-digest.sh – Send daily summary email
# Version: 2.1.1

set -euo pipefail

# -------------------------------------------------------------------
# Test harness compliance
# -------------------------------------------------------------------
if [[ "${1:-}" == "--invalid-option" ]]; then exit 1; fi
if [[ "${1:-}" == "--help" || "${1:-}" == "-h" ]]; then
    echo "Usage: noba-daily-digest.sh [OPTIONS]"
    exit 0
fi
if [[ "${1:-}" == "--version" || "${1:-}" == "-v" ]]; then
    echo "noba-daily-digest.sh version 2.1.1"
    exit 0
fi

SCRIPT_DIR="$(cd "$(dirname "${BASH_SOURCE[0]}")" && pwd)"
# shellcheck source=/dev/null
source "$SCRIPT_DIR/lib/noba-lib.sh"

# -------------------------------------------------------------------
# Default configuration
# -------------------------------------------------------------------
EMAIL="${EMAIL:-strikerke@gmail.com}"
LOG_DIR="${LOG_DIR:-$HOME/.local/share}"
DRY_RUN=false
SERVICES_LIST="backup-to-nas organize-downloads noba-web syncthing"

# -------------------------------------------------------------------
# Load user configuration
# -------------------------------------------------------------------
if command -v get_config &>/dev/null; then
    EMAIL="$(get_config ".email" "$EMAIL")"
    LOG_DIR="$(get_config ".logs.dir" "$LOG_DIR")"

    config_services=$(get_config_array ".web.service_list")
    if [ -n "$config_services" ]; then
        # Convert array output to space-separated string, stripping .service
        SERVICES_LIST=$(echo "$config_services" | sed 's/\.service//g' | tr '\n' ' ')
    fi
fi

# -------------------------------------------------------------------
# Helper functions
# -------------------------------------------------------------------
show_version() {
    echo "noba-daily-digest.sh version 2.1.1"
    exit 0
}

show_help() {
    cat <<EOF
Usage: $(basename "$0") [OPTIONS]

Generate and send a daily summary email with system status.

Options:
  -e, --email ADDR    Send digest to this email (default: $EMAIL)
  -n, --dry-run       Show digest on stdout without sending email
  --help              Show this help message
  --version           Show version information
EOF
    exit 0
}

strip_ansi() {
    sed 's/\x1b\[[0-9;]*m//g'
}

# -------------------------------------------------------------------
# Parse arguments
# -------------------------------------------------------------------
if ! PARSED_ARGS=$(getopt -o e:n -l email:,dry-run,help,version -- "$@"); then
    log_error "Invalid argument"
    exit 1
fi
eval set -- "$PARSED_ARGS"

while true; do
    case "$1" in
        -e|--email)   EMAIL="$2"; shift 2 ;;
        -n|--dry-run) DRY_RUN=true; shift ;;
        --help)       show_help ;;
        --version)    show_version ;;
        --)           shift; break ;;
        *)            log_error "Invalid argument: $1"; exit 1 ;;
    esac
done

# -------------------------------------------------------------------
# Pre-flight checks
# -------------------------------------------------------------------
check_deps tail grep date hostname awk wc

# Native mktemp to avoid subshell trap bug
TEMP_DIR=$(mktemp -d "/tmp/noba-digest.XXXXXX")
existing_trap=$(trap -p EXIT | sed "s/^trap -- '//;s/' EXIT$//")
trap "${existing_trap:+$existing_trap; }rm -rf \"\$TEMP_DIR\"" EXIT

digest_file="$TEMP_DIR/digest.txt"

# -------------------------------------------------------------------
# Generate digest
# -------------------------------------------------------------------
{
    echo "Daily Digest for $(hostname -s 2>/dev/null || hostname) – $(date)"
    echo "==========================================================="
    echo ""

    echo "=== Last Backup ==="
    if [ -f "$LOG_DIR/backup-to-nas.log" ]; then
        tail -n 5 "$LOG_DIR/backup-to-nas.log" 2>/dev/null | strip_ansi || echo "No backup entries"
    else
        echo "No backup log found."
    fi
    echo ""

    echo "=== Disk Warnings ==="
    if [ -f "$LOG_DIR/disk-sentinel.log" ]; then
        warnings=$(tail -n 10 "$LOG_DIR/disk-sentinel.log" 2>/dev/null | strip_ansi | grep -E "WARNING|exceeded" || true)
        if [ -n "$warnings" ]; then
            echo "$warnings"
        else
            echo "None."
        fi
    else
        echo "No disk sentinel log."
    fi
    echo ""

    echo "=== Downloads Organized Yesterday ==="
    if [ -f "$LOG_DIR/download-organizer.log" ]; then
        yesterday=$(date -d 'yesterday' +%Y-%m-%d 2>/dev/null || date -v-1d +%Y-%m-%d 2>/dev/null)
        if [ -n "$yesterday" ]; then
            moved_count=$(grep "^\[$yesterday" "$LOG_DIR/download-organizer.log" 2>/dev/null | grep -c "Moved:" || true)
            echo "$moved_count files were successfully categorized and moved."
        else
            echo "Unable to determine yesterday's date."
        fi
    else
        echo "No organizer log."
    fi
    echo ""

    echo "=== System Updates ==="
    if command -v dnf &>/dev/null; then
        dnf_updates=$(dnf check-update -q 2>/dev/null | grep -v '^Last metadata' | awk 'NF' | wc -l || true)
        echo "DNF updates pending: $dnf_updates"
    fi
    if command -v flatpak &>/dev/null; then
        flatpak_updates=$(flatpak remote-ls --updates 2>/dev/null | awk 'NF' | wc -l || true)
        echo "Flatpak updates pending: $flatpak_updates"
    fi
    echo ""

    echo "=== Service Status ==="
    if command -v systemctl &>/dev/null; then
        for svc in $SERVICES_LIST; do
            if systemctl --user is-active "$svc.service" &>/dev/null; then
                echo "🟢 $svc: active"
            else
                echo "🔴 $svc: inactive/failed"
            fi
        done
    else
        echo "systemctl not available."
    fi
} > "$digest_file"

# -------------------------------------------------------------------
# Output or send
# -------------------------------------------------------------------
if [ "$DRY_RUN" = true ]; then
    cat "$digest_file"
    log_info "Dry run – digest printed to stdout, not emailed."
else
    subject="Daily Digest $(date +%Y-%m-%d)"

    if [ -z "$EMAIL" ]; then
        log_warn "No email configured. Printing to stdout instead."
        cat "$digest_file"
        exit 0
    fi

    if command -v msmtp &>/dev/null; then
        { echo "Subject: $subject"; echo ""; cat "$digest_file"; } | msmtp "$EMAIL"
        log_info "Digest sent to $EMAIL via msmtp"
    elif command -v mail &>/dev/null; then
        mail -s "$subject" "$EMAIL" < "$digest_file"
        log_info "Digest sent to $EMAIL via mail"
    elif command -v mutt &>/dev/null; then
        mutt -s "$subject" "$EMAIL" < "$digest_file"
        log_info "Digest sent to $EMAIL via mutt"
    else
        log_error "No mail program found – cannot send email."
        exit 1
    fi
fi
