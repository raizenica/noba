#!/bin/bash
# undo-organizer.sh – Undo last download organizer run
# Version: 2.2.0

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
    echo "undo-organizer.sh version 2.2.0"
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

# Portable reverse line function
reverse_lines() {
    if command -v tac &>/dev/null; then
        tac "$1"
    else
        awk '{a[NR]=$0} END {for (i=NR;i>=1;i--) print a[i]}' "$1"
    fi
}

# -------------------------------------------------------------------
# Parse command-line arguments
# -------------------------------------------------------------------
if ! PARSED_ARGS=$(getopt -o df -l dry-run,force,help,version -- "$@"); then
    log_error "Invalid arguments"
    exit 1
    exit 1
fi
eval set -- "$PARSED_ARGS"

while true; do
    case "$1" in
        -d|--dry-run) DRY_RUN=true; shift ;;
        -f|--force)   FORCE=true; shift ;;
        --help)       show_help ;;
        --version)    show_version ;;
        --)           shift; break ;;
        *) log_error "Invalid argument: $1"; exit 1 ;;
    esac
done

# -------------------------------------------------------------------
# Pre-flight checks
# -------------------------------------------------------------------
if [ ! -f "$UNDO_LOG" ] || [ ! -s "$UNDO_LOG" ]; then
    if [ "$DRY_RUN" = true ]; then
        log_info "[DRY RUN] No undo log found at $UNDO_LOG – nothing to do."
        exit 0
    else
        die "No undo log found at $UNDO_LOG. Nothing to undo."
    fi
fi

# Count entries
count=$(wc -l < "$UNDO_LOG")
log_info "This will undo the last download organizer run, moving $count file(s) back."

if [ "$FORCE" = false ] && [ "$DRY_RUN" = false ]; then
    if ! confirm "Are you sure you want to proceed?" "n"; then
        log_info "Cancelled by user."
        exit 0
    fi
fi

# -------------------------------------------------------------------
# Process undo log in reverse order
# -------------------------------------------------------------------
log_info "Starting undo process (dry run: $DRY_RUN)..."

ERROR_OCCURRED=false

while IFS= read -r line; do
    # Remove trailing carriage return if any
    line=${line%$'\r'}

    # Try ASCII unit separator \037 first, fallback to pipe |
    if [[ "$line" == *$'\037'* ]]; then
        src="${line%%$'\037'*}"
        dest="${line#*$'\037'}"
    elif [[ "$line" == *'|'* ]]; then
        src="${line%%|*}"
        dest="${line#*|}"
    else
        log_warn "Malformed undo entry, skipping: $line"
        continue
    fi

    if [ -z "$src" ] || [ -z "$dest" ]; then
        log_warn "Empty source or destination in entry, skipping: $line"
        continue
    fi

    if [ ! -f "$dest" ]; then
        log_warn "Restoration source file not found: $dest – skipping"
        ERROR_OCCURRED=true
        continue
    fi

    if [ "$DRY_RUN" = true ]; then
        log_info "[DRY RUN] Would restore: $(basename "$dest") → $(dirname "$src")/"
    else
        mkdir -p "$(dirname "$src")"
        if mv "$dest" "$src"; then
            log_info "Restored: $(basename "$dest")"
        else
            log_error "Failed to restore: $dest"
            ERROR_OCCURRED=true
        fi
    fi
done < <(reverse_lines "$UNDO_LOG")

if [ "$DRY_RUN" = false ]; then
    if [ "$ERROR_OCCURRED" = false ]; then
        : > "$UNDO_LOG"
        log_success "Undo complete. Undo log cleared."
    else
        log_warn "Undo completed with errors. The undo log was NOT cleared so you can retry failed files."
    fi
fi
