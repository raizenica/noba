#!/bin/bash
# Backup to NAS with HTML email – upgraded version

set -euo pipefail  # strict mode: exit on error, undefined var, pipe failure

# Defaults
DEFAULT_SOURCES=("/home/raizen/Documents" "/home/raizen/Pictures" "/home/raizen/.config")
DEST="/mnt/vnnas/backups/raizen"
EMAIL="strikerke@gmail.com"
DRY_RUN=false
LOCK_FILE="/tmp/backup-to-nas.lock"
LOG_FILE="/tmp/backup.log"

# Functions
usage() {
    cat <<EOF
Usage: $0 [options]

Options:
  --source DIR   Add a source directory to backup (can be used multiple times)
  --dest DIR     Set destination directory (default: $DEST)
  --email ADDR   Set email recipient (default: $EMAIL)
  --dry-run      Simulate backup without copying
  --help         Show this help
EOF
    exit 0
}

# Parse command-line arguments
OPTIONS=$(getopt -o '' -l source:,dest:,email:,dry-run,help -- "$@")
if [ $? -ne 0 ]; then
    usage
fi
eval set -- "$OPTIONS"

SOURCES=()
while true; do
    case "$1" in
        --source)
            SOURCES+=("$2")
            shift 2
            ;;
        --dest)
            DEST="$2"
            shift 2
            ;;
        --email)
            EMAIL="$2"
            shift 2
            ;;
        --dry-run)
            DRY_RUN=true
            shift
            ;;
        --help)
            usage
            ;;
        --)
            shift
            break
            ;;
        *)
            echo "Internal error!"
            exit 1
            ;;
    esac
done

# If no sources specified, use defaults
if [ ${#SOURCES[@]} -eq 0 ]; then
    SOURCES=("${DEFAULT_SOURCES[@]}")
fi

# Check if NAS is mounted (find the mount point containing DEST)
if ! command -v findmnt &>/dev/null; then
    echo "ERROR: findmnt not available. Please install util-linux." >&2
    exit 1
fi

MOUNT_POINT=$(findmnt -n -o TARGET --target "$DEST" 2>/dev/null)
if [ -z "$MOUNT_POINT" ]; then
    echo "ERROR: Destination $DEST is not on a mounted filesystem." >&2
    exit 1
fi

echo "NAS is mounted at $MOUNT_POINT"

# Create destination directory
mkdir -p "$DEST"

# Lock file to prevent concurrent runs
exec 200>"$LOCK_FILE"
if ! flock -n 200; then
    echo "Another backup is already running. Exiting." >&2
    exit 1
fi

# Cleanup lock on exit
trap 'rm -f "$LOCK_FILE"' EXIT

# Start time
START_TIME=$(date +%s)

# Function to send email
send_email() {
    local subject="$1"
    local body_file="$2"
    {
        echo "To: $EMAIL"
        echo "Subject: $subject"
        echo "MIME-Version: 1.0"
        echo "Content-Type: text/html; charset=utf-8"
        echo ""
        cat "$body_file"
    } | msmtp "$EMAIL"
}

# Prepare email body file (HTML)
EMAIL_BODY=$(mktemp)

# Redirect all rsync output to log file
exec > >(tee -a "$LOG_FILE") 2>&1

echo "Starting backup at $(date)"
echo "Destination: $DEST"
echo "Sources: ${SOURCES[*]}"

# Perform rsync for each source
RSYNC_OPTS="-av --delete"
if [ "$DRY_RUN" = true ]; then
    RSYNC_OPTS="$RSYNC_OPTS --dry-run"
fi

for src in "${SOURCES[@]}"; do
    # Determine relative path for destination
    base=$(basename "$src")
    if [ "$base" = ".config" ]; then
        # Special case: .config goes into config/ subfolder
        dest_path="$DEST/config/"
    else
        dest_path="$DEST/"
    fi

    echo "Syncing $src -> $dest_path"
    rsync $RSYNC_OPTS "$src" "$dest_path"
done

# Calculate stats
END_TIME=$(date +%s)
DURATION=$((END_TIME - START_TIME))
# Count files transferred (using rsync summary lines that contain 'files')
FILES_COUNT=$(grep -E '^Number of files: ' "$LOG_FILE" | tail -1 | awk '{print $4}')
if [ -z "$FILES_COUNT" ]; then
    FILES_COUNT="N/A"
fi
SIZE=$(du -sh "$DEST" | cut -f1)

# Generate HTML report
cat > "$EMAIL_BODY" <<EOF
<!DOCTYPE html>
<html><head><style>
body { font-family: Arial, sans-serif; line-height: 1.6; color: #333; }
.container { max-width: 600px; margin: 20px auto; padding: 20px; border-radius: 10px; background: #f9f9f9; }
.header { background: #2196F3; color: white; padding: 15px; border-radius: 10px 10px 0 0; margin: -20px -20px 20px -20px; }
.stats { display: grid; grid-template-columns: 1fr 1fr; gap: 15px; margin: 20px 0; }
.stat-card { background: white; padding: 15px; border-radius: 8px; box-shadow: 0 2px 4px rgba(0,0,0,0.1); }
.stat-label { font-size: 12px; color: #666; text-transform: uppercase; }
.stat-value { font-size: 24px; font-weight: bold; color: #2196F3; }
.log { background: #1e1e1e; color: #00ff00; padding: 15px; border-radius: 8px; font-family: monospace; font-size: 12px; overflow-x: auto; }
.footer { margin-top: 30px; padding-top: 20px; border-top: 1px solid #ddd; font-size: 12px; color: #666; }
</style></head><body>
<div class="container">
<div class="header"><h2 style="margin:0;">💾 NAS Backup Report</h2></div>
<p>Backup completed at <strong>$(date '+%Y-%m-%d %H:%M:%S')</strong></p>
<div class="stats">
<div class="stat-card"><div class="stat-label">Duration</div><div class="stat-value">${DURATION}s</div></div>
<div class="stat-card"><div class="stat-label">Files Transferred</div><div class="stat-value">${FILES_COUNT}</div></div>
<div class="stat-card"><div class="stat-label">Total Size</div><div class="stat-value">${SIZE}</div></div>
<div class="stat-card"><div class="stat-label">Destination</div><div class="stat-value">NAS</div></div>
</div>
<h3>📋 Last 20 lines of log:</h3>
<div class="log">$(tail -20 "$LOG_FILE" | sed 's/$/<br>/')</div>
<div class="footer">
✅ Backup automated • $(hostname) → vnnas
</div>
</div></body></html>
EOF

# Send email
send_email "💾 NAS Backup Complete - $(date +%Y-%m-%d)" "$EMAIL_BODY"

# Cleanup
rm -f "$EMAIL_BODY"
rm -f "$LOG_FILE"

echo "Backup finished successfully."
