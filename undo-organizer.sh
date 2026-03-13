#!/bin/bash
# undo-organizer.sh – Undo last download organizer run

set -euo pipefail

SCRIPT_DIR="$(cd "$(dirname "${BASH_SOURCE[0]}")" && pwd)"
# shellcheck source=/dev/null
# shellcheck source=/dev/null
source "$SCRIPT_DIR/noba-lib.sh"

# -------------------------------------------------------------------
# Default configuration
# -------------------------------------------------------------------
UNDO_LOG="${UNDO_LOG:-$HOME/.local/share/download-organizer-undo.log}"
DRY_RUN=false
FORCE=false

# -------------------------------------------------------------------
# Load user configuration (if any)
# -------------------------------------------------------------------
load_config
if [ "$CONFIG_LOADED" = true ]; then
    # Override undo log path from logs.dir in config
    logs_dir="$(get_config ".logs.dir" "$HOME/.local/share")"
    # Expand tilde if present (get_config returns as-is)
    logs_dir="${logs_dir/#\~/$HOME}"
    UNDO_LOG="${logs_dir}/download-organizer-undo.log"
fi

# -------------------------------------------------------------------
# Helper functions
# -------------------------------------------------------------------
show_version() {
    echo "undo-organizer.sh version 1.0"
    exit 0
}

show_help() {
    cat <<EOF
Usage: $0 [OPTIONS]

Undo the last download organizer run by moving files back to their original locations.

Options:
  -d, --dry-run   Show what would be undone without moving
  -f, --force     Skip confirmation prompt
  --help          Show this help message
  --version       Show version information
EOF
    exit 0
}

# Portable reverse line function (tac, tail -r, or awk)
reverse_lines() {
    if command -v tac &>/dev/null; then
        tac "$1"
    elif command -v tail &>/dev/null && tail --version 2>/dev/null | grep -q "GNU"; then
        # GNU tail has -r option (reverse) but it's not portable
        # Actually tail -r is not in GNU, it's BSD. Use awk fallback.
        # Use awk as most reliable fallback.
        awk '{a[NR]=$0} END {for (i=NR;i>=1;i--) print a[i]}' "$1"
    else
        awk '{a[NR]=$0} END {for (i=NR;i>=1;i--) print a[i]}' "$1"
    fi
}

# -------------------------------------------------------------------
# Parse command-line arguments
# -------------------------------------------------------------------
# shellcheck disable=SC2034
# shellcheck disable=SC2034
# shellcheck disable=SC2034
# shellcheck disable=SC2034
# shellcheck disable=SC2034
# shellcheck disable=SC2034
# shellcheck disable=SC2034
# shellcheck disable=SC2034
# shellcheck disable=SC2034
# shellcheck disable=SC2034
# shellcheck disable=SC2034
PARSED_ARGS=$(getopt -o df -l dry-run,force,help,version -- "$@")
if ! some_command; then
    show_help
fi
eval set -- "$PARSED_ARGS"

while true; do
    case "$1" in
        -d|--dry-run) DRY_RUN=true; shift ;;
        -f|--force)   FORCE=true; shift ;;
        --help)       show_help ;;
        --version)    show_version ;;
        --)           shift; break ;;
        *)            break ;;
    esac
done

# -------------------------------------------------------------------
# Pre-flight checks
# -------------------------------------------------------------------
# Check if undo log exists and is non‑empty
if [ ! -f "$UNDO_LOG" ] || [ ! -s "$UNDO_LOG" ]; then
    if [ "$DRY_RUN" = true ]; then
        log_info "[DRY RUN] No undo log found – nothing to do."
        exit 0
    else
        log_error "No undo log found at $UNDO_LOG"
        exit 1
    fi
fi

# Count entries
count=$(wc -l < "$UNDO_LOG")
log_info "This will undo the last download organizer run, moving $count file(s) back."

if [ "$FORCE" = false ] && [ "$DRY_RUN" = false ]; then
    read -p "Are you sure? (y/N) " -n 1 -r
    echo
    if [[ ! $REPLY =~ ^[Yy]$ ]]; then
        log_info "Cancelled by user."
        exit 0
    fi
fi

# -------------------------------------------------------------------
# Process undo log in reverse order
# -------------------------------------------------------------------
log_info "Starting undo process (dry run: $DRY_RUN)..."

# We'll use a temporary file to collect errors, but simpler: just process
reverse_lines "$UNDO_LOG" | while IFS= read -r line; do
    # Remove trailing carriage return if any
    line=${line%$'\r'}
    # Try new separator (ASCII unit separator \037)
    if [[ "$line" == *$'\037'* ]]; then
        src="${line%%$'\037'*}"
        rest="${line#*$'\037'}"
        dest="${rest%%$'\037'*}"
    # Fallback to old pipe separator
    elif [[ "$line" == *'|'* ]]; then
        src="${line%%|*}"
        dest="${line#*|}"
    else
        log_warn "Malformed undo entry, skipping: $line"
        continue
    fi

    if [ -z "$src" ] || [ -z "$dest" ]; then
        log_warn "Empty src or dest in entry, skipping: $line"
        continue
    fi

    if [ ! -f "$dest" ]; then
        log_warn "Source file not found: $dest – skipping"
        continue
    fi

    if [ "$DRY_RUN" = true ]; then
        log_info "[DRY RUN] Would restore: $dest → $src"
    else
        # Ensure target directory exists
        mkdir -p "$(dirname "$src")"
        mv "$dest" "$src"
        log_info "Restored: $dest → $src"
    fi
done

if [ "$DRY_RUN" = false ]; then
    # Clear undo log after successful undo
    : > "$UNDO_LOG"
    log_info "Undo complete. Undo log cleared."
else
    log_info "[DRY RUN] Undo log would be cleared after actual run."
fi
