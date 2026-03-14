#!/bin/bash
# backup-to-nas.sh – Backup important directories to NAS with retention, space check, and email report
# Version: 2.2.2

set -euo pipefail

# -------------------------------------------------------------------
# Load shared library
# -------------------------------------------------------------------
SCRIPT_DIR="$(cd "$(dirname "${BASH_SOURCE[0]}")" && pwd)"
# shellcheck source=./noba-lib.sh
source "$SCRIPT_DIR/noba-lib.sh"

# -------------------------------------------------------------------
# Default configuration
# -------------------------------------------------------------------
SOURCES=()
DEST=""
EMAIL="${EMAIL:-strikerke@gmail.com}"
DRY_RUN=false
export VERBOSE=false
LOCK_FILE="/tmp/backup-to-nas.lock"
LOG_FILE="${LOG_FILE:-$HOME/.local/share/backup-to-nas.log}"
RETENTION_DAYS=7
SPACE_MARGIN_PERCENT=10
MIN_FREE_SPACE_GB=5
MOUNT_POINT=""

# -------------------------------------------------------------------
# Load user configuration (if any)
# -------------------------------------------------------------------
if command -v get_config &>/dev/null; then
    sources_from_config=$(get_config_array ".backup.sources")
    if [ -n "$sources_from_config" ]; then
        mapfile -t SOURCES <<< "$sources_from_config"
    fi

    DEST="$(get_config ".backup.dest" "$DEST")"
    EMAIL="$(get_config ".backup.email" "$EMAIL")"
    RETENTION_DAYS="$(get_config ".backup.retention_days" "$RETENTION_DAYS")"
    SPACE_MARGIN_PERCENT="$(get_config ".backup.space_margin_percent" "$SPACE_MARGIN_PERCENT")"
    MIN_FREE_SPACE_GB="$(get_config ".backup.min_free_space_gb" "$MIN_FREE_SPACE_GB")"
    LOG_FILE="$(get_config ".backup.log_file" "$LOG_FILE")"
fi

# -------------------------------------------------------------------
# Helper functions
# -------------------------------------------------------------------
show_version() {
    echo "backup-to-nas.sh version 2.2.2"
    exit 0
}

show_help() {
    cat <<EOF
Usage: $0 [OPTIONS]

Backup specified directories to a NAS share using incremental hardlinks.

Options:
  -s, --source DIR   Source directory to back up (can be repeated)
  -d, --dest PATH    Destination path on NAS (must be a mounted directory)
  -e, --email ADDR   Email address for report (default: $EMAIL)
  -n, --dry-run      Perform trial run with no changes
  -v, --verbose      Enable verbose output
  --help             Show this help message
  --version          Show version information
EOF
    exit 0
}

cleanup() {
    if [ -n "${LOCK_FD:-}" ]; then
        flock -u "$LOCK_FD" 2>/dev/null || true
    fi
    rm -f "$LOCK_FILE"
}

check_space() {
    local src_size_kb=0 total_size_kb=0 src
    for src in "${SOURCES[@]}"; do
        if [ -e "$src" ]; then
            src_size_kb=$(du -sk "$src" 2>/dev/null | cut -f1)
            total_size_kb=$((total_size_kb + src_size_kb))
        else
            log_warn "Source '$src' does not exist – skipping in size estimate."
        fi
    done

    # Add margin
    total_size_kb=$((total_size_kb + (total_size_kb * SPACE_MARGIN_PERCENT / 100)))
    local required_bytes=$((total_size_kb * 1024))

    local free_bytes
    if ! free_bytes=$(df --output=avail "$MOUNT_POINT" 2>/dev/null | tail -1 | awk '{print $1 * 1024}'); then
        log_error "Could not determine free space on $MOUNT_POINT."
        return 1
    fi

    local required_hr free_hr
    if command -v numfmt &>/dev/null; then
        required_hr=$(numfmt --to=iec "$required_bytes")
        free_hr=$(numfmt --to=iec "$free_bytes")
    else
        required_hr="$required_bytes bytes"
        free_hr="$free_bytes bytes"
    fi

    log_info "Estimated backup size (with margin): $required_hr"
    log_info "Free space on $MOUNT_POINT: $free_hr"

    local min_free_bytes=$((MIN_FREE_SPACE_GB * 1024 * 1024 * 1024))
    if [ "$free_bytes" -lt "$min_free_bytes" ]; then
        log_error "Free space is below minimum ${MIN_FREE_SPACE_GB}GB."
        return 1
    fi

    # Only strictly enforce required space if we don't have a previous backup to hardlink against
    local latest_backup
    latest_backup=$(find "$DEST" -maxdepth 1 -type d -name "????????-??????" | sort | tail -n 1 || true)

    if [ -z "$latest_backup" ] && [ "$free_bytes" -lt "$required_bytes" ]; then
        log_error "Insufficient space for initial full backup – need at least $required_hr, only $free_hr available."
        return 1
    fi

    log_info "Space check passed."
    return 0
}

send_email_report() {
    local subject="$1"
    local body_file="$2"
    if command -v mutt &>/dev/null; then
        mutt -s "$subject" -a "$LOG_FILE" -- "$EMAIL" < "$body_file"
    elif command -v mail &>/dev/null; then
        mail -s "$subject" "$EMAIL" < "$body_file"
    else
        log_warn "No mail program found – skipping email."
    fi
}

# -------------------------------------------------------------------
# Parse command-line arguments
# -------------------------------------------------------------------
if ! PARSED_ARGS=$(getopt -o s:d:e:nvh -l source:,dest:,email:,dry-run,verbose,help,version -- "$@"); then
    show_help
fi
eval set -- "$PARSED_ARGS"

while true; do
    case "$1" in
        -s|--source)  SOURCES+=("$2"); shift 2 ;;
        -d|--dest)    DEST="$2"; shift 2 ;;
        -e|--email)   EMAIL="$2"; shift 2 ;;
        -n|--dry-run) DRY_RUN=true; shift ;;
        -v|--verbose) export VERBOSE=true; shift ;;
        -h|--help)    show_help ;;
        --version)    show_version ;;
        --)           shift; break ;;
        *)            log_error "Invalid argument: $1"; exit 1 ;;
    esac
done

# -------------------------------------------------------------------
# Validations & Setup
# -------------------------------------------------------------------
if [ ${#SOURCES[@]} -eq 0 ]; then
    if [ "$DRY_RUN" = true ]; then exit 0; else die "At least one --source must be specified."; fi
fi

if [ -z "$DEST" ]; then
    if [ "$DRY_RUN" = true ]; then exit 0; else die "Destination (--dest) is required."; fi
fi

if [ ! -d "$DEST" ]; then
    if [ "$DRY_RUN" = true ]; then
        log_info "Dry run: destination $DEST not available – skipping actual checks."
        exit 0
    else
        die "Destination directory $DEST does not exist – is the NAS mounted?"
    fi
fi

check_deps rsync df find du

MOUNT_POINT=$(df -P "$DEST" 2>/dev/null | tail -1 | awk '{print $6}')
if [ -z "$MOUNT_POINT" ]; then
    die "Cannot determine mount point for $DEST – is it a valid path?"
fi

# Prepare logging
mkdir -p "$(dirname "$LOG_FILE")"
touch "$LOG_FILE"
exec > >(tee -a "$LOG_FILE") 2>&1

# Acquire lock
exec 200>"$LOCK_FILE"
if ! flock -n 200; then
    die "Another backup instance is already running (lock: $LOCK_FILE)."
fi
LOCK_FD=200

# Safely append trap
existing_trap=$(trap -p EXIT | sed "s/^trap -- '//;s/' EXIT$//")
# shellcheck disable=SC2064
trap "${existing_trap:+$existing_trap; }cleanup" EXIT

# -------------------------------------------------------------------
# Start backup
# -------------------------------------------------------------------
log_info "========== Backup started at $(date) =========="
log_info "Destination: $DEST"
log_info "Sources: ${SOURCES[*]}"
log_info "Retention: $RETENTION_DAYS days"
log_info "Dry run: $DRY_RUN"

if ! check_space; then
    die "Space check failed – aborting."
fi

TIMESTAMP=$(date +%Y%m%d-%H%M%S)
BACKUP_PATH="$DEST/$TIMESTAMP"

# Find latest backup for hardlinking
LATEST_BACKUP=$(find "$DEST" -maxdepth 1 -type d -name "????????-??????" | sort | tail -n 1 || true)
if [ -n "$LATEST_BACKUP" ]; then
    log_info "Found previous backup: $(basename "$LATEST_BACKUP"). Using for incremental hardlinks."
else
    log_info "No previous backup found. Performing full initial backup."
fi

if [ "$DRY_RUN" = false ]; then
    mkdir -p "$BACKUP_PATH"
else
    log_info "Dry run: would create $BACKUP_PATH"
fi

ERROR_OCCURRED=false
START_TIME=$SECONDS

# Setup core rsync options array
RSYNC_OPTS=("-a" "--delete")
if [ "$VERBOSE" = true ]; then RSYNC_OPTS+=("-v" "--progress"); fi
if [ "$DRY_RUN" = true ]; then RSYNC_OPTS+=("--dry-run"); fi

for src in "${SOURCES[@]}"; do
    base=$(basename "$src")
    extra_opts=()

    # Apply hardlinks if we have a previous backup
    if [ -n "$LATEST_BACKUP" ]; then
        extra_opts+=("--link-dest=$LATEST_BACKUP/$base")
    fi

    if [ "$base" = ".config" ]; then
        dest_path="$BACKUP_PATH/config"
        extra_opts+=(
            "--exclude=*cache*"
            "--exclude=*thumbnails*"
            "--exclude=*Trash*"
            "--exclude=*session*"
            "--exclude=*/sockets/"
            "--exclude=*lock"
            "--exclude=*.tmp"
            "--no-links"
        )
    else
        dest_path="$BACKUP_PATH/$base"
    fi

    log_info "Backing up $src to $dest_path"

    # Ensure source has trailing slash
    src_slashed="${src%/}/"

    if ! rsync "${RSYNC_OPTS[@]}" "${extra_opts[@]}" "$src_slashed" "$dest_path"; then
        log_error "rsync failed for $src"
        ERROR_OCCURRED=true
    fi
done

DURATION=$((SECONDS - START_TIME))

# -------------------------------------------------------------------
# Prune old backups
# -------------------------------------------------------------------
if [ "$DRY_RUN" = false ] && [ -d "$DEST" ]; then
    log_info "Pruning backups older than $RETENTION_DAYS days..."

    while read -r old_backup; do
        [[ -z "$old_backup" ]] && continue
        folder_date=$(basename "$old_backup" | cut -d- -f1)
        if folder_seconds=$(date -d "$folder_date" +%s 2>/dev/null); then
            current_seconds=$(date +%s)
            age_days=$(( (current_seconds - folder_seconds) / 86400 ))
            if [ "$age_days" -ge "$RETENTION_DAYS" ]; then
                log_info "Removing old backup: $old_backup ($age_days days old)"
                rm -rf "$old_backup"
            fi
        else
            log_warn "Cannot parse date from folder name: $old_backup – skipping"
        fi
    done <<< "$(find "$DEST" -maxdepth 1 -type d -name "????????-??????" | sort)"
else
    log_info "Dry run or destination missing – skipping prune."
fi

# -------------------------------------------------------------------
# Reporting
# -------------------------------------------------------------------
if [ "$DRY_RUN" = false ] && [ -d "$BACKUP_PATH" ]; then
    SIZE=$(du -sh "$BACKUP_PATH" 2>/dev/null | cut -f1 || echo "unknown")
else
    SIZE="N/A (dry run)"
fi

EMAIL_BODY_DIR=$(make_temp_dir_auto "backup-to-nas-report")
EMAIL_BODY="$EMAIL_BODY_DIR/email_report.txt"

if [ "$ERROR_OCCURRED" = true ]; then
    subject_prefix="❌ BACKUP FAILED"
else
    subject_prefix="✅ BACKUP SUCCESSFUL"
fi

cat > "$EMAIL_BODY" <<EOF
$subject_prefix

Backup completed at: $(date '+%Y-%m-%d %H:%M:%S')
Destination Folder:  $TIMESTAMP
Retention Policy:    $RETENTION_DAYS days

----------------------------------------
📊 STATS
----------------------------------------
Duration:     ${DURATION}s
Backup Size:  ${SIZE} (Note: Size reflects hardlink usage)

----------------------------------------
📁 SOURCES BACKED UP
----------------------------------------
$(printf ' - %s\n' "${SOURCES[@]}")

----------------------------------------
📝 Full log attached.
This is an automated message from your backup system.
EOF

if [ "$DRY_RUN" = false ]; then
    send_email_report "$subject_prefix - $(date '+%Y-%m-%d')" "$EMAIL_BODY"
fi

log_info "========== Backup finished at $(date) =========="

if [ "$DRY_RUN" = false ] && command -v backup-notify.sh &>/dev/null; then
    backup-notify.sh || true
fi
