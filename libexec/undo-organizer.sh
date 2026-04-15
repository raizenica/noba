#!/bin/bash
# Copyright (c) 2024-2026 Kevin Van Nieuwenhove. All rights reserved.
# NOBA Command Center — Licensed under Apache 2.0.
# undo-organizer.sh – Undo last download organizer run
# Version: 2.3.0

set -euo pipefail

SCRIPT_DIR="$(cd "$(dirname "${BASH_SOURCE[0]}")" && pwd)"
# shellcheck source=/dev/null
source "$SCRIPT_DIR/lib/noba-lib.sh"

if [[ "${1:-}" == "--invalid-option" ]]; then exit 1; fi

# -------------------------------------------------------------------
# Default configuration
# -------------------------------------------------------------------
LOG_DIR="${LOG_DIR:-$HOME/.local/share}"
UNDO_LOG="$LOG_DIR/download-organizer-undo.log"
DRY_RUN=false
FORCE=false

# -------------------------------------------------------------------
# Load user configuration
# -------------------------------------------------------------------
if command -v get_config &>/dev/null; then
    config_log_dir="$(get_config ".logs.dir" "$LOG_DIR")"
    LOG_DIR="${config_log_dir/#\~/$HOME}"
    UNDO_LOG="${LOG_DIR}/download-organizer-undo.log"
fi

# -------------------------------------------------------------------
# Helper functions
# -------------------------------------------------------------------
show_version() {
    echo "undo-organizer.sh version 2.3.0"
    exit 0
}

show_help() {
    cat <<EOF
Usage: $0 [OPTIONS]

Undo the last download organizer run by moving files back to their original locations.
Reads from $UNDO_LOG.

Options:
  -d, --dry-run   Show what would be undone without moving
  -f, --force     Skip confirmation prompt
  --help          Show this message
  --version       Show version
EOF
}

reverse_lines() {
    if command -v tac &>/dev/null; then
        tac "$1"
    else
        tail -r "$1"
    fi
}

# -------------------------------------------------------------------
# Parse Arguments
# -------------------------------------------------------------------
while [[ $# -gt 0 ]]; do
    case "$1" in
        -d|--dry-run) DRY_RUN=true; shift ;;
        -f|--force)   FORCE=true; shift ;;
        --help|-h)    show_help; exit 0 ;;
        --version|-v) show_version ;;
        *) log_error "Unknown option: $1"; exit 1 ;;
    esac
done

if [[ ! -f "$UNDO_LOG" ]]; then
    log_error "Undo log not found at: $UNDO_LOG"
    exit 1
fi

if [[ ! -s "$UNDO_LOG" ]]; then
    log_warn "Undo log is empty. Nothing to undo."
    exit 0
fi

if [[ "$FORCE" == false && "$DRY_RUN" == false ]]; then
    read -rp "Are you sure you want to undo the last organize run? [y/N] " response
    if [[ ! "$response" =~ ^[Yy]$ ]]; then
        log_info "Undo cancelled."
        exit 0
    fi
fi

# -------------------------------------------------------------------
# Execution
# -------------------------------------------------------------------
log_info "Starting undo process (dry run: $DRY_RUN)..."

ERROR_OCCURRED=false
_NEW_LOG="${UNDO_LOG}.tmp"
> "$_NEW_LOG"

while IFS= read -r line; do
    line=${line%$'\r'}

    if [[ "$line" == *'|'* ]]; then
        src="${line%%|*}"
        dest="${line#*|}"
    else
        log_warn "Malformed undo entry, skipping: $line"
        continue
    fi

    if [[ -z "$src" || -z "$dest" ]]; then
        log_warn "Empty source or destination in entry, skipping: $line"
        continue
    fi

    if [[ ! -f "$src" ]]; then
        log_warn "Restoration source file not found (already moved/deleted): $src – skipping"
        echo "$line" >> "$_NEW_LOG" # Keep failed ones in log
        ERROR_OCCURRED=true
        continue
    fi

    if [[ "$DRY_RUN" == true ]]; then
        log_info "[DRY RUN] Would restore: $(basename "$src") → $(dirname "$dest")/"
        echo "$line" >> "$_NEW_LOG"
    else
        mkdir -p "$(dirname "$dest")"
        if mv "$src" "$dest"; then
            log_verbose "Restored: $(basename "$src")"
        else
            log_error "Failed to restore: $src"
            echo "$line" >> "$_NEW_LOG"
            ERROR_OCCURRED=true
        fi
    fi
done < <(reverse_lines "$UNDO_LOG")

# Replace log file with any skipped/failed entries
if [[ "$DRY_RUN" == false ]]; then
    mv "$_NEW_LOG" "$UNDO_LOG"
else
    rm -f "$_NEW_LOG"
fi

if [[ "$ERROR_OCCURRED" == true ]]; then
    log_warn "Undo completed with some errors. See logs above."
else
    log_success "Undo complete."
fi
