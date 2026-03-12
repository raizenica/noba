#!/bin/bash
# Disk Space Sentinel – monitor and clean up disk space with email alerts

set -u
set -o pipefail

# Source central config if available
if [ -f "$HOME/.config/automation.conf" ]; then
    source "$HOME/.config/automation.conf"
fi

# Configuration (with central config overrides)
THRESHOLD="${DISK_THRESHOLD:-85}"
TARGETS=("${DISK_TARGETS[@]:-/ /home}")
CLEANUP="${CLEANUP_ENABLED:-true}"
EMAIL="${EMAIL:-strikerke@gmail.com}"
LOG_FILE="$HOME/.local/share/disk-sentinel.log"
DRY_RUN=false

# Virtual filesystems to ignore (regex patterns)
IGNORE_FS="^(proc|sysfs|tmpfs|devpts|securityfs|fusectl|debugfs|pstore|hugetlbfs|mqueue|configfs|devtmpfs|binfmt_misc)$"

# Function to show version
show_version() {
    if command -v git &>/dev/null && git rev-parse --git-dir &>/dev/null; then
        version=$(git describe --tags --always --dirty 2>/dev/null)
        echo "$(basename "$0") version $version"
    else
        echo "$(basename "$0") version unknown (not in git repo)"
    fi
    exit 0
}

# Function to log messages
log() {
    echo "$(date '+%Y-%m-%d %H:%M:%S') - $1" >> "$LOG_FILE"
    echo "$1"
}

# Function to send email
send_email() {
    local subject="$1"
    local body="$2"
    echo -e "Subject: $subject\n\n$body" | msmtp "$EMAIL"
}

# Simple argument parsing
for arg in "$@"; do
    case $arg in
        --version)
            show_version
            ;;
        --help)
            echo "Usage: $0 [--version] [--help]"
            echo "Monitors disk space and cleans up if threshold exceeded."
            exit 0
            ;;
        *)
            ;;
    esac
done

# Start
log "=== Disk Space Check ==="

for target in "${TARGETS[@]}"; do
    # Get usage percentage and mount point
    read -r usage mount <<< $(df -h "$target" | awk 'NR==2 {print $5" "$6}')
    usage=${usage%\%}  # remove %
    log "$mount: ${usage}% used"

    # Skip if filesystem type is in IGNORE_FS
    fstype=$(df -T "$target" | awk 'NR==2 {print $2}')
    if [[ "$fstype" =~ $IGNORE_FS ]]; then
        log "Skipping $mount (virtual filesystem $fstype)"
        continue
    fi

    if [ "$usage" -ge "$THRESHOLD" ]; then
        log "WARNING: $mount exceeded ${THRESHOLD}% threshold."

        # Prepare email body
        EMAIL_BODY="Disk space alert for $mount on $(hostname) at $(date)\n"
        EMAIL_BODY+="Usage: ${usage}% (threshold ${THRESHOLD}%)\n\n"
        EMAIL_BODY+="Top 10 directories by size:\n"
        EMAIL_BODY+=$(du -h "$target" 2>/dev/null | sort -rh | head -10)

        if [ "$CLEANUP" = true ] && [ "$DRY_RUN" = false ]; then
            log "Starting cleanup on $mount..."

            # Clean package manager caches
            if command -v dnf &>/dev/null; then
                log "Cleaning DNF cache..."
                sudo dnf clean all >> "$LOG_FILE" 2>&1
            fi

            # Clean user cache
            log "Cleaning ~/.cache..."
            rm -rf "$HOME/.cache/"* >> "$LOG_FILE" 2>&1

            # Clean system temp (old files)
            log "Cleaning /tmp (old files)..."
            sudo find /tmp -type f -atime +1 -delete >> "$LOG_FILE" 2>&1

            # Vacuum journals older than 3 days
            if command -v journalctl &>/dev/null; then
                log "Vacuuming systemd journals..."
                sudo journalctl --vacuum-time=3d >> "$LOG_FILE" 2>&1
            fi

            # After cleanup, check new usage
            new_usage=$(df -h "$target" | awk 'NR==2 {print $5}' | sed 's/%//')
            EMAIL_BODY+="\nCleanup performed. New usage: ${new_usage}%"
            log "Cleanup completed. New usage: ${new_usage}%"
        else
            EMAIL_BODY+="\nNo cleanup performed (dry run or CLEANUP=false)."
        fi

        # Send email alert
        send_email "⚠️ Disk Space Alert: $mount at ${usage}%" "$EMAIL_BODY"
    else
        log "$mount usage is OK."
    fi
done

log "=== Check Complete ==="
