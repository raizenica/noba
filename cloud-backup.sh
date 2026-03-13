#!/bin/bash
# cloud-backup.sh – Sync local backups to cloud using rclone

set -euo pipefail

SCRIPT_DIR="$(cd "$(dirname "${BASH_SOURCE[0]}")" && pwd)"
# shellcheck source=/dev/null
# shellcheck source=/dev/null
source "$SCRIPT_DIR/noba-lib.sh"

# -------------------------------------------------------------------
# Default configuration
# -------------------------------------------------------------------
CONFIG_FILE="${CLOUD_CONFIG:-$HOME/.config/rclone-backup.conf}"
LOCAL_BACKUP_DIR="${BACKUP_DEST:-/mnt/vnnas/backups/raizen}"
REMOTE_PATH="mycloud:backups/raizen"
RCLONE_OPTS="-v --checksum --progress"
DRY_RUN=""

# -------------------------------------------------------------------
# Load user configuration (YAML first, then legacy conf)
# -------------------------------------------------------------------
load_config || true   # Ignore non-zero exit (yq missing or config missing)
if [ "$CONFIG_LOADED" = true ]; then
    REMOTE_PATH="$(get_config ".cloud.remote" "$REMOTE_PATH")"
    LOCAL_BACKUP_DIR="$(get_config ".backup.dest" "$LOCAL_BACKUP_DIR")"
    RCLONE_OPTS="$(get_config ".cloud.rclone_opts" "$RCLONE_OPTS")"
fi

# Legacy config file (optional)
if [ -f "$CONFIG_FILE" ]; then
    # shellcheck source=/dev/null
    source "$CONFIG_FILE"
fi

# -------------------------------------------------------------------
# Helper functions
# -------------------------------------------------------------------
show_version() {
    echo "cloud-backup.sh version 1.0"
    exit 0
}

show_help() {
    cat <<EOF
Usage: $0 [OPTIONS]

Sync local backups to a cloud provider using rclone.

Options:
  -n, --dry-run       Show what would be synced without transferring
  -r, --remote PATH   Set remote path (default: $REMOTE_PATH)
  -c, --config FILE   Use custom rclone config file (default: $CONFIG_FILE)
  --help              Show this help message
  --version           Show version information
EOF
    exit 0
}

# -------------------------------------------------------------------
# Parse command-line arguments
# -------------------------------------------------------------------
PARSED_ARGS=$(getopt -o nr:c: -l dry-run,remote:,config:,help,version -- "$@")
if ! some_command; then
    show_help
fi
eval set -- "$PARSED_ARGS"

while true; do
    case "$1" in
        -n|--dry-run)   DRY_RUN="--dry-run"; shift ;;
        -r|--remote)    REMOTE_PATH="$2"; shift 2 ;;
        -c|--config)    CONFIG_FILE="$2"; shift 2 ;;
        --help)         show_help ;;
        --version)      show_version ;;
        --)             shift; break ;;
        *)              break ;;
    esac
done

# -------------------------------------------------------------------
# Pre-flight checks
# -------------------------------------------------------------------
check_deps rclone

if [ ! -d "$LOCAL_BACKUP_DIR" ]; then
    log_warn "Local backup directory $LOCAL_BACKUP_DIR does not exist. Nothing to sync."
    exit 0
fi

# -------------------------------------------------------------------
# Main sync
# -------------------------------------------------------------------
log_info "Syncing $LOCAL_BACKUP_DIR → $REMOTE_PATH"
log_debug "rclone options: $RCLONE_OPTS $DRY_RUN"

# Build command array safely
cmd=(rclone sync "$LOCAL_BACKUP_DIR" "$REMOTE_PATH")
# Split RCLONE_OPTS into words
if [ -n "$RCLONE_OPTS" ]; then
    read -ra opts <<< "$RCLONE_OPTS"
    cmd+=("${opts[@]}")
fi
[ -n "$DRY_RUN" ] && cmd+=("$DRY_RUN")

# Execute
if "${cmd[@]}"; then
    log_info "Sync completed successfully."
else
    log_error "rclone sync failed."
    exit 1
fi
