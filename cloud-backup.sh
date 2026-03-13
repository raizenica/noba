#!/bin/bash
# cloud-backup.sh – Sync local backups to cloud (rclone)

# Load configuration
load_config
if [ "$CONFIG_LOADED" = true ]; then
    true
    # Override defaults with config values (script-specific)
    # Example:
    # VAR=$(get_config ".${script%.sh}.var" "$VAR")
fi

# Load configuration
load_config
if [ "$CONFIG_LOADED" = true ]; then
    true
    # Override defaults with config values (script-specific)
    # Example:
    # VAR=$(get_config ".${script%.sh}.var" "$VAR")
fi

set -u
set -o pipefail

SCRIPT_DIR="$(cd "$(dirname "${BASH_SOURCE[0]}")" && pwd)"
# shellcheck source=/dev/null
source "$SCRIPT_DIR/noba-lib.sh"

# Defaults
CONFIG_FILE="${CLOUD_CONFIG:-$HOME/.config/rclone-backup.conf}"
LOCAL_BACKUP_DIR="${BACKUP_DEST:-/mnt/vnnas/backups/raizen}"
REMOTE_PATH="mycloud:backups/raizen"
RCLONE_OPTS="-v --checksum --progress"
DRY_RUN=""

# Version
show_version() {
    echo "cloud-backup.sh version 1.0"
    exit 0
}

# Help
show_help() {
    cat <<EOF
Usage: $0 [OPTIONS]

Sync local backups to a cloud provider using rclone.

Options:
  --dry-run           Show what would be synced without transferring
  --remote PATH       Set remote path (default: $REMOTE_PATH)
  --config FILE       Use custom rclone config file (default: $CONFIG_FILE)
  --help              Show this help
  --version           Show version information
EOF
    exit 0
}

# Parse arguments
while [[ $# -gt 0 ]]; do
    case $1 in
        --dry-run) DRY_RUN="--dry-run" ;;
        --remote) REMOTE_PATH="$2"; shift ;;
        --config) CONFIG_FILE="$2"; shift ;;
        --help) show_help ;;
        --version) show_version ;;
        *) echo "Unknown option: $1" >&2; show_help ;;
    esac
    shift
done

# Load config if exists
# shellcheck source=/dev/null
[ -f "$CONFIG_FILE" ] && source "$CONFIG_FILE"

if ! command -v rclone &>/dev/null; then
    log_error "rclone not installed."
    exit 1
fi

log_info "Syncing $LOCAL_BACKUP_DIR → $REMOTE_PATH"
# shellcheck disable=SC2086
rclone sync "$LOCAL_BACKUP_DIR" "$REMOTE_PATH" $RCLONE_OPTS $DRY_RUN
