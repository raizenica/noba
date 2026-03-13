#!/bin/bash
# backup-to-nas.sh – Backup important directories to NAS with retention, space check, and email report

set -euo pipefail

# -------------------------------------------------------------------
# Load shared library
# -------------------------------------------------------------------
SCRIPT_DIR="$(cd "$(dirname "${BASH_SOURCE[0]}")" && pwd)"
source "$SCRIPT_DIR/noba-lib.sh"

# -------------------------------------------------------------------
# Default configuration
# -------------------------------------------------------------------
SOURCES=()
DEST=""
EMAIL="${EMAIL:-strikerke@gmail.com}"
DRY_RUN=false
LOCK_FILE="/tmp/backup-to-nas.lock"
LOG_FILE="${LOG_FILE:-$HOME/.local/share/backup-to-nas.log}"
RETENTION_DAYS=7
SPACE_MARGIN_PERCENT=10
MIN_FREE_SPACE_GB=5
MOUNT_POINT=""

# -------------------------------------------------------------------
# Load user configuration (if any)
# -------------------------------------------------------------------
load_config
if [ "$CONFIG_LOADED" = true ]; then
    sources_from_config=$(get_config_array ".backup.sources")
    log_debug "Raw sources from config: '$sources_from_config'"
    if [ -n "$sources_from_config" ]; then
        mapfile -t SOURCES <<< "$sources_from_config"
        log_debug "SOURCES array after mapfile: ${SOURCES[*]}"
    else
        log_debug "get_config_array returned empty – no sources in config."
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
    echo "backup-to-nas.sh version 2.0"
    exit 0
}

show_help() {
    cat <<EOF
Usage: $0 [OPTIONS]

Backup specified directories to a NAS share with retention and space checks.

Options:
  --source DIR       Source directory to back up (can be repeated)
  --dest PATH        Destination path on NAS (must be a mounted directory)
  --email ADDRESS    Email address for report (default: $EMAIL)
  --dry-run          Perform trial run with no changes
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

    if [ "$free_bytes" -lt "$required_bytes" ]; then
        log_error "Insufficient space – need at least $required_hr, only $free_hr available."
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
PARSED_ARGS=$(getopt -o '' -l source:,dest:,email:,dry-run,help,version -- "$@")
if [ $? -ne 0 ]; then
    show_help
fi
eval set -- "$PARSED_ARGS"

while true; do
    case "$1" in
        --source)   SOURCES+=("$2"); shift 2 ;;
        --dest)     DEST="$2"; shift 2 ;;
        --email)    EMAIL="$2"; shift 2 ;;
        --dry-run)  DRY_RUN=true; shift ;;
        --help)     show_help ;;
        --version)  show_version ;;
        --)         shift; break ;;
        *)          break ;;
    esac
done

# -------------------------------------------------------------------
# Early dry-run exit if destination unavailable (for testing)
# -------------------------------------------------------------------
if [ "$DRY_RUN" = true ] && [ ! -d "$DEST" ]; then
    log_info "Dry run: destination $DEST not available – skipping actual checks."
    exit 0
fi

# -------------------------------------------------------------------
# Validate required arguments
# -------------------------------------------------------------------
if [ ${#SOURCES[@]} -eq 0 ]; then
    log_error "At least one --source must be specified."
    show_help
fi
if [ -z "$DEST" ]; then
    log_error "Destination (--dest) is required."
    show_help
fi

# Derive mount point from DEST
MOUNT_POINT=$(df -P "$DEST" 2>/dev/null | tail -1 | awk '{print $6}')
if [ -z "$MOUNT_POINT" ]; then
    log_error "Cannot determine mount point for $DEST – is it a valid path?"
    exit 1
fi

# -------------------------------------------------------------------
# Prepare log directory and file
# -------------------------------------------------------------------
mkdir -p "$(dirname "$LOG_FILE")"
touch "$LOG_FILE"
exec > >(tee -a "$LOG_FILE") 2>&1

# -------------------------------------------------------------------
# Acquire lock
# -------------------------------------------------------------------
exec 200>"$LOCK_FILE"
if ! flock -n 200; then
    log_error "Another backup instance is already running (lock: $LOCK_FILE)."
    exit 1
fi
LOCK_FD=200
trap cleanup EXIT

# -------------------------------------------------------------------
# Start backup
# -------------------------------------------------------------------
log_info "========== Backup started at $(date) =========="
log_info "Destination: $DEST"
log_info "Sources: ${SOURCES[*]}"
log_info "Retention: $RETENTION_DAYS days"
log_info "Dry run: $DRY_RUN"

if [ ! -d "$DEST" ]; then
    log_error "Destination directory $DEST does not exist – is the NAS mounted?"
    exit 1
fi

if ! check_space; then
    log_error "Space check failed – aborting."
    exit 1
fi

TIMESTAMP=$(date +%Y%m%d-%H%M%S)
BACKUP_PATH="$DEST/$TIMESTAMP"
if [ "$DRY_RUN" = false ]; then
    mkdir -p "$BACKUP_PATH"
else
    log_info "Dry run: would create $BACKUP_PATH"
fi

ERROR_OCCURRED=false
START_TIME=$SECONDS

for src in "${SOURCES[@]}"; do
    base=$(basename "$src")
    if [ "$base" = ".config" ]; then
        dest_path="$BACKUP_PATH/config/"
        extra_opts=(
            --exclude='*cache*'
            --exclude='*thumbnails*'
            --exclude='*Trash*'
            --exclude='*session*'
            --exclude='*/sockets/'
            --exclude='*lock'
            --exclude='*.tmp'
            --no-links
        )
    else
        dest_path="$BACKUP_PATH/"
        extra_opts=()
    fi

    log_info "Backing up $src to $dest_path"

    if [ "$DRY_RUN" = true ]; then
        rsync_dry="--dry-run"
    else
        rsync_dry=""
    fi

    if ! rsync -avhP --delete "${extra_opts[@]}" $rsync_dry "$src" "$dest_path"; then
        log_error "rsync failed for $src"
        ERROR_OCCURRED=true
    fi
done

DURATION=$((SECONDS - START_TIME))

# Prune old backups
if [ "$DRY_RUN" = false ] && [ -d "$DEST" ]; then
    log_info "Pruning backups older than $RETENTION_DAYS days..."
    find "$DEST" -maxdepth 1 -type d -name "????????-??????" | while read -r old_backup; do
        folder_date=$(basename "$old_backup" | cut -d- -f1)
        if folder_seconds=$(date -d "$folder_date" +%s 2>/dev/null); then
            current_seconds=$(date +%s)
            age_days=$(( (current_seconds - folder_seconds) / 86400 ))
            if [ "$age_days" -ge "$RETENTION_DAYS" ]; then
                log_info "Removing old backup: $old_backup"
                rm -rf "$old_backup"
            fi
        else
            log_warn "Cannot parse date from folder name: $old_backup – skipping"
        fi
    done
else
    log_info "Dry run or destination missing – skipping prune."
fi

# Collect statistics
FILES_COUNT=$(grep -E '^Number of files: ' "$LOG_FILE" 2>/dev/null | tail -1 | awk '{print $4}' || echo "N/A")
if [ -z "$FILES_COUNT" ] || [ "$FILES_COUNT" = "N/A" ]; then
    FILES_COUNT="N/A"
fi

if [ "$DRY_RUN" = false ] && [ -d "$BACKUP_PATH" ]; then
    SIZE=$(du -sh "$BACKUP_PATH" 2>/dev/null | cut -f1 || echo "unknown")
else
    SIZE="N/A (dry run)"
fi

# Generate email report (always, but only send if not dry run)
EMAIL_BODY=$(mktemp)
if [ "$ERROR_OCCURRED" = true ]; then
    subject_prefix="❌ BACKUP FAILED"
    status_class="error"
else
    subject_prefix="✅ BACKUP SUCCESSFUL"
    status_class="success"
fi

cat > "$EMAIL_BODY" <<EOF
<!DOCTYPE html>
<html>
<head>
    <meta charset="UTF-8">
    <style>
        body { font-family: Arial, sans-serif; line-height: 1.6; color: #333; }
        .container { max-width: 800px; margin: 0 auto; padding: 20px; }
        .header { background-color: #f4f4f4; padding: 10px; border-radius: 5px; }
        .stats { display: grid; grid-template-columns: repeat(3, 1fr); gap: 10px; margin: 20px 0; }
        .stat-card { background-color: #f9f9f9; padding: 15px; border-radius: 5px; text-align: center; }
        .stat-label { font-size: 0.9em; color: #666; }
        .stat-value { font-size: 1.5em; font-weight: bold; }
        .error { color: #d32f2f; }
        .success { color: #388e3c; }
        .footer { margin-top: 30px; font-size: 0.9em; color: #777; }
    </style>
</head>
<body>
<div class="container">
    <div class="header">
        <h2 class="$status_class">$subject_prefix</h2>
    </div>
    <p>Backup completed at <strong>$(date '+%Y-%m-%d %H:%M:%S')</strong></p>
    <p>Backup folder: <code>$TIMESTAMP</code></p>
    <p>Retention: last $RETENTION_DAYS days kept</p>
    <div class="stats">
        <div class="stat-card">
            <div class="stat-label">Duration</div>
            <div class="stat-value">${DURATION}s</div>
        </div>
        <div class="stat-card">
            <div class="stat-label">Files Transferred</div>
            <div class="stat-value">${FILES_COUNT}</div>
        </div>
        <div class="stat-card">
            <div class="stat-label">Backup Size</div>
            <div class="stat-value">${SIZE}</div>
        </div>
    </div>
    <p><strong>Sources backed up:</strong></p>
    <ul>
EOF
for src in "${SOURCES[@]}"; do
    echo "        <li>$src</li>" >> "$EMAIL_BODY"
done
cat >> "$EMAIL_BODY" <<EOF
    </ul>
    <p>Full log is attached.</p>
    <div class="footer">
        <p>This is an automated message from your backup system.</p>
    </div>
</div>
</body>
</html>
EOF

# Only send email if not dry-run
if [ "$DRY_RUN" = false ]; then
    send_email_report "$subject_prefix - $(date '+%Y-%m-%d')" "$EMAIL_BODY"
fi

rm -f "$EMAIL_BODY"
log_info "========== Backup finished at $(date) =========="

# Call notification script only if not in dry-run mode, and ignore any failure
if [ "$DRY_RUN" = false ] && command -v backup-notify.sh &>/dev/null; then
    backup-notify.sh || true
fi
