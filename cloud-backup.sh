#!/bin/bash
SCRIPT_DIR="$(cd "$(dirname "${BASH_SOURCE[0]}")" && pwd)"
source "$SCRIPT_DIR/noba-lib.sh"
# cloud-backup.sh – Sync local backups to cloud (rclone)

set -u
set -o pipefail

CONFIG_FILE="${CLOUD_CONFIG:-$HOME/.config/rclone-backup.conf}"
LOCAL_BACKUP_DIR="${BACKUP_DEST:-/mnt/vnnas/backups/raizen}"
REMOTE_PATH="mycloud:backups/raizen"
RCLONE_OPTS=(-v --checksum --progress)

# Load custom remote if config exists
# shellcheck source=/dev/null
[ -f "$CONFIG_FILE" ] && source "$CONFIG_FILE"

usage() {
    echo "Usage: $0 [--dry-run] [--remote PATH]"
    exit 1
}

DRY_RUN=""
while [[ $# -gt 0 ]]; do
    case $1 in
        --dry-run) DRY_RUN="--dry-run" ;;
        --remote) REMOTE_PATH="$2"; shift ;;
        *) usage ;;
    esac
    shift
done

if ! command -v rclone &>/dev/null; then
    echo "ERROR: rclone not installed." >&2
    exit 1
fi

echo "Syncing $LOCAL_BACKUP_DIR → $REMOTE_PATH"
rclone sync "$LOCAL_BACKUP_DIR" "$REMOTE_PATH" "${RCLONE_OPTS[@]}" $DRY_RUN
