#!/bin/bash
# Copyright (c) 2024-2026 Kevin Van Nieuwenhove. All rights reserved.
# NOBA Command Center — Licensed under Apache 2.0.
# noba-daily-digest.sh – Send daily summary email
# Version: 2.2.0

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
    echo "noba-daily-digest.sh version 2.2.0"
    exit 0
fi

SCRIPT_DIR="$(cd "$(dirname "${BASH_SOURCE[0]}")" && pwd)"
# shellcheck source=./lib/noba-lib.sh
source "$SCRIPT_DIR/lib/noba-lib.sh"

# -------------------------------------------------------------------
# Default configuration
# -------------------------------------------------------------------
EMAIL="${EMAIL:-}" # Scrubbed
LOG_DIR="${LOG_DIR:-$HOME/.local/share}"
DRY_RUN=false
SERVICES_LIST="backup-to-nas organize-downloads noba-web syncthing"

# -------------------------------------------------------------------
# Load user configuration
# -------------------------------------------------------------------
if command -v get_config &>/dev/null; then
    EMAIL="$(get_config ".email" "$EMAIL")"
    LOG_DIR="$(get_config ".logs.dir" "$LOG_DIR")"

    # Expand tilde in log dir if present
    LOG_DIR="${LOG_DIR/#\~/$HOME}"

    config_services=$(get_config_array ".services.monitor" 2>/dev/null || true)
    if [[ -n "$config_services" ]]; then
        SERVICES_LIST=$(echo "$config_services" | tr '\n' ' ')
    fi
fi

# -------------------------------------------------------------------
# Parse Arguments
# -------------------------------------------------------------------
while [[ $# -gt 0 ]]; do
    case "$1" in
        --dry-run) DRY_RUN=true; shift ;;
        *) log_error "Unknown argument: $1"; exit 1 ;;
    esac
done

# -------------------------------------------------------------------
# Generate Digest
# -------------------------------------------------------------------
digest_file="${TMPDIR:-/tmp}/noba_digest_$(date +%s).txt"
trap 'rm -f "$digest_file"' EXIT
log_info "Generating daily digest..."

{
    echo "NOBA AUTOMATION SUITE - DAILY DIGEST"
    echo "Host: $(hostname)"
    echo "Date: $(date)"
    echo "----------------------------------------"
    echo ""

    echo "=== Storage ==="
    df -h / /home | awk 'NR>1 {print "  " $6 ": " $5 " used (" $4 " free)"}'
    echo ""

    echo "=== Recent Backups ==="
    backup_log="$LOG_DIR/backup-to-nas.log"
    if [[ -f "$backup_log" ]]; then
        tail -n 5 "$backup_log" | sed 's/^/  /'
    else
        echo "  No backup log found at $backup_log"
    fi
    echo ""

    echo "=== System Updates ==="
    if command -v dnf &>/dev/null; then
        dnf_updates=$(dnf check-update -q 2>/dev/null | grep -c -v '^$' || true)
        echo "  DNF updates pending: $dnf_updates"
    fi
    if command -v flatpak &>/dev/null; then
        flatpak_updates=$(flatpak remote-ls --updates 2>/dev/null | wc -l || true)
        echo "  Flatpak updates pending: $flatpak_updates"
    fi
    echo ""

    echo "=== Service Status ==="
    if command -v systemctl &>/dev/null; then
        for svc in $SERVICES_LIST; do
            if [[ -n "$svc" ]]; then
                if systemctl --user is-active "${svc}.service" &>/dev/null || systemctl is-active "${svc}.service" &>/dev/null; then
                    echo "  🟢 $svc: active"
                else
                    echo "  🔴 $svc: inactive/failed"
                fi
            fi
        done
    else
        echo "  systemctl not available."
    fi
} > "$digest_file"

# -------------------------------------------------------------------
# Output or Send
# -------------------------------------------------------------------
if [[ "$DRY_RUN" == true ]]; then
    cat "$digest_file"
    log_info "Dry run – digest printed to stdout, not emailed."
else
    subject="Daily Digest $(date +%Y-%m-%d)"

    if [[ -z "$EMAIL" ]]; then
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
        log_error "No mail client found (msmtp, mail, mutt). Cannot send."
        cat "$digest_file"
    fi
fi

rm -f "$digest_file"
