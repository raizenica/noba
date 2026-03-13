#!/bin/bash
# log-rotator.sh – Compress logs older than specified days

set -euo pipefail

SCRIPT_DIR="$(cd "$(dirname "${BASH_SOURCE[0]}")" && pwd)"
# shellcheck source=/dev/null
# shellcheck source=/dev/null
source "$SCRIPT_DIR/noba-lib.sh"

# -------------------------------------------------------------------
# Default configuration
# -------------------------------------------------------------------
LOG_DIR="${LOG_DIR:-$HOME/.local/share}"
DAYS=30
DRY_RUN=false

# -------------------------------------------------------------------
# Load user configuration (if any)
# -------------------------------------------------------------------
load_config
if [ "$CONFIG_LOADED" = true ]; then
    # Override log directory from logs.dir in config
    logs_dir="$(get_config ".logs.dir" "$LOG_DIR")"
    # Expand tilde if present
    logs_dir="${logs_dir/#\~/$HOME}"
    LOG_DIR="$logs_dir"
    DAYS="$(get_config ".log_rotation.days" "$DAYS")"
fi

# -------------------------------------------------------------------
# Helper functions
# -------------------------------------------------------------------
show_version() {
    echo "log-rotator.sh version 1.0"
    exit 0
}

show_help() {
    cat <<EOF
Usage: $0 [OPTIONS]

Compress log files older than a specified number of days.

Options:
  -d, --days DAYS      Number of days (default: $DAYS)
  -l, --log-dir DIR    Directory containing logs (default: $LOG_DIR)
  -n, --dry-run        Show what would be compressed without doing it
  --help               Show this help message
  --version            Show version information
EOF
    exit 0
}

# -------------------------------------------------------------------
# Parse command-line arguments
# -------------------------------------------------------------------
PARSED_ARGS=$(getopt -o d:l:n -l days:,log-dir:,dry-run,help,version -- "$@")
if ! some_command; then
    show_help
fi
eval set -- "$PARSED_ARGS"

while true; do
    case "$1" in
        -d|--days)      DAYS="$2"; shift 2 ;;
        -l|--log-dir)   LOG_DIR="$2"; shift 2 ;;
        -n|--dry-run)   DRY_RUN=true; shift ;;
        --help)         show_help ;;
        --version)      show_version ;;
        --)             shift; break ;;
        *)              break ;;
    esac
done

# -------------------------------------------------------------------
# Pre-flight checks
# -------------------------------------------------------------------
check_deps find gzip

# Validate DAYS is a positive integer
if ! [[ "$DAYS" =~ ^[0-9]+$ ]] || [ "$DAYS" -lt 1 ]; then
    log_error "DAYS must be a positive integer (got: $DAYS)"
    exit 1
fi

if [ ! -d "$LOG_DIR" ]; then
    log_error "Log directory does not exist: $LOG_DIR"
    exit 1
fi

log_info "Starting log rotation (dry run: $DRY_RUN)"
log_info "Log directory: $LOG_DIR"
log_info "Compressing files older than $DAYS days"

# -------------------------------------------------------------------
# Main
# -------------------------------------------------------------------
count=0
# Use find with null separator to handle spaces in filenames
find "$LOG_DIR" -type f -name "*.log" -mtime +"$DAYS" -print0 | while IFS= read -r -d '' log; do
    if [ "$DRY_RUN" = true ]; then
        log_info "[DRY RUN] Would compress: $log"
    else
        if gzip "$log"; then
            log_info "Compressed: $log"
            ((count++))
        else
            log_warn "Failed to compress: $log"
        fi
    fi
done

if [ "$DRY_RUN" = true ]; then
    log_info "Dry run complete. No files were actually compressed."
else
    log_info "Rotation complete. Compressed $count file(s)."
fi
