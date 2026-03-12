#!/bin/bash
# Disk Space Sentinel – monitor and clean up disk space with email alerts

set -u
set -o pipefail

# -------------------------------------------------------------------
# Configuration and defaults
# -------------------------------------------------------------------

# Source central config if available
# shellcheck source=/dev/null
if [ -f "$HOME/.config/automation.conf" ]; then
    source "$HOME/.config/automation.conf"
fi

# Defaults (can be overridden by config file)
THRESHOLD="${DISK_THRESHOLD:-85}"
# Define default targets as an array
DEFAULT_TARGETS=(/ /home)
# Use DISK_TARGETS from config if set, otherwise defaults
if [ -n "${DISK_TARGETS[*]:-}" ]; then
    TARGETS=("${DISK_TARGETS[@]}")
else
    TARGETS=("${DEFAULT_TARGETS[@]}")
fi
CLEANUP="${CLEANUP_ENABLED:-true}"
EMAIL="${EMAIL:-strikerke@gmail.com}"
LOG_FILE="$HOME/.local/share/disk-sentinel.log"
DRY_RUN=false
VERBOSE=false

# Virtual filesystems to ignore (regex patterns)
IGNORE_FS="^(proc|sysfs|tmpfs|devpts|securityfs|fusectl|debugfs|pstore|hugetlbfs|mqueue|configfs|devtmpfs|binfmt_misc)$"

# -------------------------------------------------------------------
# Helper functions
# -------------------------------------------------------------------

show_version() {
    if command -v git &>/dev/null && git rev-parse --git-dir &>/dev/null; then
        version=$(git describe --tags --always --dirty 2>/dev/null)
        echo "$(basename "$0") version $version"
    else
        echo "$(basename "$0") version unknown (not in git repo)"
    fi
    exit 0
}

usage() {
    cat <<EOF
Usage: $0 [options]

Options:
  -t, --threshold PERCENT  Set warning threshold (default: $THRESHOLD)
  -n, --dry-run            Don't perform cleanup or send email
  -v, --verbose            Print more details
  --help                   Show this help
  --version                Show version information
EOF
    exit 0
}

# Check required commands
check_deps() {
    local missing=()
    for cmd in df awk du sort head date mkdir mktemp; do
        if ! command -v "$cmd" &>/dev/null; then
            missing+=("$cmd")
        fi
    done
    if [ ${#missing[@]} -gt 0 ]; then
        echo "ERROR: Missing required commands: ${missing[*]}" >&2
        exit 1
    fi
}

# Logging function
log() {
    local msg="$1"
    local timestamp
    timestamp=$(date '+%Y-%m-%d %H:%M:%S')
    echo "$timestamp - $msg" >> "$LOG_FILE"
    if [ "$VERBOSE" = true ] || [ "$DRY_RUN" = false ]; then
        echo "$msg"
    fi
}

# Send email via msmtp (if available)
send_email() {
    local subject="$1"
    local body="$2"
    if [ -z "$EMAIL" ]; then
        log "No email recipient set, skipping notification."
        return
    fi
    if ! command -v msmtp &>/dev/null; then
        log "msmtp not installed, cannot send email."
        return
    fi
    # Use printf for portability
    printf "Subject: %s\n\n%s\n" "$subject" "$body" | msmtp "$EMAIL"
    log "Email sent to $EMAIL"
}

# Run a command with sudo, capturing output to log (no direct redirection)
run_sudo() {
    local cmd_desc="$1"
    shift
    if [ "$DRY_RUN" = true ]; then
        log "[DRY RUN] Would run (sudo): $*"
        return 0
    fi
    log "Running: $cmd_desc"
    # Check if user can sudo without password for this command
    if sudo -n true 2>/dev/null; then
        # Use a temporary file to capture output
        local temp_output
        temp_output=$(mktemp)
        # Run command with sudo, capture both stdout and stderr
                # shellcheck disable=SC2024
        if sudo "$@" > "$temp_output" 2>&1; then
            cat "$temp_output" >> "$LOG_FILE"
            rm -f "$temp_output"
            return 0
        else
            local status=$?
            cat "$temp_output" >> "$LOG_FILE"
            rm -f "$temp_output"
            log "WARNING: Command failed (exit $status): $*"
            return $status
        fi
    else
        log "WARNING: sudo not available or requires password; skipping $cmd_desc"
        return 1
    fi
}

# -------------------------------------------------------------------
# Parse command-line arguments
# -------------------------------------------------------------------
while [[ $# -gt 0 ]]; do
    case $1 in
        -t|--threshold)
            THRESHOLD="$2"
            shift 2
            ;;
        -n|--dry-run)
            DRY_RUN=true
            shift
            ;;
        -v|--verbose)
            VERBOSE=true
            shift
            ;;
        --help)
            usage
            ;;
        --version)
            show_version
            ;;
        -*)
            echo "Unknown option: $1" >&2
            exit 1
            ;;
        *)
            echo "Unexpected argument: $1" >&2
            exit 1
            ;;
    esac
done

# -------------------------------------------------------------------
# Pre-flight checks and setup
# -------------------------------------------------------------------
check_deps
mkdir -p "$(dirname "$LOG_FILE")"

# Validate threshold
if ! [[ "$THRESHOLD" =~ ^[0-9]+$ ]] || [ "$THRESHOLD" -lt 0 ] || [ "$THRESHOLD" -gt 100 ]; then
    echo "ERROR: Threshold must be a number between 0 and 100." >&2
    exit 1
fi

# Start
log "=== Disk Space Check ==="

for target in "${TARGETS[@]}"; do
    # Skip if target does not exist
    if [ ! -e "$target" ]; then
        log "WARNING: Target '$target' does not exist, skipping."
        continue
    fi

    # Get usage percentage and mount point using df --output (more reliable)
    if ! df_output=$(df --output=pcent,target "$target" 2>/dev/null | tail -1); then
        log "WARNING: Cannot get disk usage for '$target', skipping."
        continue
    fi
    usage=$(echo "$df_output" | awk '{print $1}' | sed 's/%//')
    mount=$(echo "$df_output" | awk '{print $2}')

    # Get filesystem type
    if ! fstype=$(df -T "$target" 2>/dev/null | awk 'NR==2 {print $2}'); then
        fstype="unknown"
    fi

    log "$mount: ${usage}% used (fstype: $fstype)"

    # Skip if filesystem type is in IGNORE_FS
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
        EMAIL_BODY+="$(du -h "$target" 2>/dev/null | sort -rh | head -10)\n"

        # Cleanup if enabled and not dry-run
        if [ "$CLEANUP" = true ] && [ "$DRY_RUN" = false ]; then
            log "Starting cleanup on $mount..."

            # Clean package manager caches (using run_sudo)
            if command -v dnf &>/dev/null; then
                run_sudo "cleaning DNF cache" dnf clean all
            elif command -v apt-get &>/dev/null; then
                run_sudo "cleaning APT cache" apt-get clean
            elif command -v pacman &>/dev/null; then
                run_sudo "cleaning pacman cache" pacman -Sc --noconfirm
            fi

            # Clean user cache – no sudo needed
            log "Cleaning ~/.cache..."
            if [ "$DRY_RUN" = false ]; then
                rm -rf "$HOME/.cache/"* >> "$LOG_FILE" 2>&1
            else
                log "[DRY RUN] Would clean ~/.cache"
            fi

            # Clean system temp (old files) – requires sudo
            run_sudo "cleaning /tmp (files older than 1 day)" find /tmp -type f -atime +1 -delete

            # Vacuum journals older than 3 days – requires sudo
            if command -v journalctl &>/dev/null; then
                run_sudo "vacuuming systemd journals" journalctl --vacuum-time=3d
            fi

            # After cleanup, check new usage
            new_usage=$(df --output=pcent "$target" 2>/dev/null | tail -1 | sed 's/%//')
            EMAIL_BODY+="\nCleanup performed. New usage: ${new_usage}%"
            log "Cleanup completed. New usage: ${new_usage}%"
        elif [ "$CLEANUP" = false ]; then
            EMAIL_BODY+="\nNo cleanup performed (CLEANUP=false)."
        else
            # DRY_RUN is true, but we still build body indicating dry run
            EMAIL_BODY+="\nDRY RUN: No actual changes made."
        fi

        # Send email alert (unless dry run)
        if [ "$DRY_RUN" = false ]; then
            send_email "⚠ Disk Space Alert: $mount at ${usage}%" "$EMAIL_BODY"
        else
            log "[DRY RUN] Would send email alert."
        fi
    else
        log "$mount usage is OK."
    fi
done

log "=== Check Complete ==="
