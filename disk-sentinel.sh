#!/bin/bash
# disk-sentinel.sh – Monitor disk space and alert when threshold exceeded

set -euo pipefail

SCRIPT_DIR="$(cd "$(dirname "${BASH_SOURCE[0]}")" && pwd)"
source "$SCRIPT_DIR/noba-lib.sh"

# -------------------------------------------------------------------
# Default configuration
# -------------------------------------------------------------------
THRESHOLD="${THRESHOLD:-85}"
TARGETS=()
# If no targets specified, use defaults: / and /home
DEFAULT_TARGETS=("/" "/home")
CLEANUP="${CLEANUP:-true}"
EMAIL="${EMAIL:-strikerke@gmail.com}"
LOG_FILE="${LOG_FILE:-$HOME/.local/share/disk-sentinel.log}"
DRY_RUN=false
# Filesystem types to ignore (regex)
IGNORE_FS="^(proc|sysfs|tmpfs|devpts|securityfs|fusectl|debugfs|pstore|hugetlbfs|mqueue|configfs|devtmpfs|binfmt_misc)$"

# -------------------------------------------------------------------
# Load user configuration (if any)
# -------------------------------------------------------------------
load_config
if [ "$CONFIG_LOADED" = true ]; then
    # Read targets array from config (if defined)
    targets_from_config=$(get_config_array ".disk.targets")
    if [ -n "$targets_from_config" ]; then
        mapfile -t TARGETS <<< "$targets_from_config"
    fi
    THRESHOLD="$(get_config ".disk.threshold" "$THRESHOLD")"
    CLEANUP="$(get_config ".disk.cleanup_enabled" "$CLEANUP")"
    EMAIL="$(get_config ".email" "$EMAIL")"  # top-level email fallback
    IGNORE_FS="$(get_config ".disk.ignore_fs" "$IGNORE_FS")"
    LOG_FILE="$(get_config ".logs.dir" "$LOG_FILE")/disk-sentinel.log"
fi

# If TARGETS still empty, use defaults
if [ ${#TARGETS[@]} -eq 0 ]; then
    TARGETS=("${DEFAULT_TARGETS[@]}")
fi

# -------------------------------------------------------------------
# Helper functions
# -------------------------------------------------------------------
show_version() {
    echo "disk-sentinel.sh version 1.0"
    exit 0
}
    source "$HOME/.config/automation.conf"

show_help() {
    cat <<EOF
Usage: $0 [OPTIONS]

Monitor disk space and send alerts when usage exceeds threshold.

Options:
  -t, --threshold PERCENT  Set warning threshold (default: $THRESHOLD)
  -n, --dry-run            Perform trial run with no changes
  -v, --verbose            Enable verbose output
  --help                   Show this help message
  --version                Show version information
EOF
    exit 0
}

# Send email via msmtp (if available)
send_email() {
    local subject="$1"
    local body="$2"
    if [ -z "$EMAIL" ]; then
        log_warn "No email recipient set – skipping notification."
        return
    fi
    if ! command -v msmtp &>/dev/null; then
        log_warn "msmtp not installed – cannot send email."
        return
    fi
    printf "Subject: %s\n\n%s\n" "$subject" "$body" | msmtp "$EMAIL"
    log_info "Email sent to $EMAIL"
}

# Run a command with sudo, capturing output to log
run_sudo() {
    local cmd_desc="$1"
    shift
    if [ "$DRY_RUN" = true ]; then
        log_debug "[DRY RUN] Would run (sudo): $*"
        return 0
    fi
    log_debug "Running (sudo): $cmd_desc"
    # Check if sudo is available without password
    if sudo -n true 2>/dev/null; then
        local temp_output
        temp_output=$(mktemp)
        if sudo "$@" > "$temp_output" 2>&1; then
            cat "$temp_output" >> "$LOG_FILE"
            rm -f "$temp_output"
            return 0
        else
            local status=$?
            cat "$temp_output" >> "$LOG_FILE"
            rm -f "$temp_output"
            log_warn "Command failed (exit $status): $*"
            return $status
        fi
    else
        log_warn "sudo not available or requires password – skipping $cmd_desc"
        return 1
    fi
}

# -------------------------------------------------------------------
# Parse command-line arguments
# -------------------------------------------------------------------
PARSED_ARGS=$(getopt -o t:nv -l threshold:,dry-run,verbose,help,version -- "$@")
if [ $? -ne 0 ]; then
    show_help
fi
eval set -- "$PARSED_ARGS"

while true; do
    case "$1" in
        -t|--threshold) THRESHOLD="$2"; shift 2 ;;
        -n|--dry-run)   DRY_RUN=true; shift ;;
        -v|--verbose)   VERBOSE=true; shift ;;
        --help)         show_help ;;
        --version)      show_version ;;
        --)             shift; break ;;
        *)              break ;;
    esac
done

# -------------------------------------------------------------------
# Pre-flight checks
# -------------------------------------------------------------------
check_deps df awk du sort head date mkdir mktemp

# Validate threshold
if ! [[ "$THRESHOLD" =~ ^[0-9]+$ ]] || [ "$THRESHOLD" -lt 0 ] || [ "$THRESHOLD" -gt 100 ]; then
    log_error "Threshold must be a number between 0 and 100."
    exit 1
fi

mkdir -p "$(dirname "$LOG_FILE")"
exec > >(tee -a "$LOG_FILE") 2>&1

log_info "========== Disk Sentinel started at $(date) =========="
log_info "Threshold: $THRESHOLD%, Cleanup: $CLEANUP, Dry run: $DRY_RUN"
log_debug "Targets: ${TARGETS[*]}"

# -------------------------------------------------------------------
# Main loop
# -------------------------------------------------------------------
for target in "${TARGETS[@]}"; do
    if [ ! -e "$target" ]; then
        log_warn "Target '$target' does not exist – skipping."
        continue
    fi

    # Get usage percentage and mount point
    if ! df_output=$(df --output=pcent,target "$target" 2>/dev/null | tail -1); then
        log_warn "Cannot get disk usage for '$target' – skipping."
        continue
    fi
    usage=$(echo "$df_output" | awk '{print $1}' | sed 's/%//')
    mount=$(echo "$df_output" | awk '{print $2}')

    # Get filesystem type
    fstype=$(df -T "$target" 2>/dev/null | awk 'NR==2 {print $2}') || fstype="unknown"

    log_info "$mount: ${usage}% used (fstype: $fstype)"

    # Skip virtual filesystems
    if [[ "$fstype" =~ $IGNORE_FS ]]; then
        log_debug "Skipping $mount (virtual filesystem $fstype)"
        continue
    fi

    if [ "$usage" -ge "$THRESHOLD" ]; then
        log_warn "WARNING: $mount exceeded ${THRESHOLD}% threshold."

        # Prepare email body
        email_body="Disk space alert for $mount on $(hostname) at $(date)\n"
        email_body+="Usage: ${usage}% (threshold ${THRESHOLD}%)\n\n"
        email_body+="Top 10 directories by size:\n"
        email_body+="$(du -h "$target" 2>/dev/null | sort -rh | head -10)\n"

        # Cleanup if enabled and not dry run
        if [ "$CLEANUP" = true ] && [ "$DRY_RUN" = false ]; then
            log_info "Starting cleanup on $mount..."

            # Package manager caches
            if command -v dnf &>/dev/null; then
                run_sudo "cleaning DNF cache" dnf clean all
            elif command -v apt-get &>/dev/null; then
                run_sudo "cleaning APT cache" apt-get clean
            elif command -v pacman &>/dev/null; then
                run_sudo "cleaning pacman cache" pacman -Sc --noconfirm
            fi

            # User cache (no sudo)
            log_info "Cleaning ~/.cache..."
            if [ "$DRY_RUN" = false ]; then
                rm -rf "$HOME/.cache/"* >> "$LOG_FILE" 2>&1
            else
                log_debug "[DRY RUN] Would clean ~/.cache"
            fi

            # System temp files older than 1 day
# shellcheck disable=SC2119
            run_sudo "cleaning /tmp (files older than 1 day)" find /tmp -type f -atime +1 -delete

            # Journal vacuum
            if command -v journalctl &>/dev/null; then
                run_sudo "vacuuming systemd journals" journalctl --vacuum-time=3d
            fi

            # Get new usage
            new_usage=$(df --output=pcent "$target" 2>/dev/null | tail -1 | sed 's/%//')
            email_body+="\nCleanup performed. New usage: ${new_usage}%"
            log_info "Cleanup completed. New usage: ${new_usage}%"
        elif [ "$CLEANUP" = false ]; then
            email_body+="\nNo cleanup performed (cleanup disabled)."
        else
            email_body+="\nDRY RUN: No actual changes made."
        fi

        # Send email (unless dry run)
        if [ "$DRY_RUN" = false ]; then
            send_email "⚠ Disk Space Alert: $mount at ${usage}%" "$email_body"
        else
            log_info "[DRY RUN] Would send email alert."
        fi
    else
        log_info "$mount usage is OK."
    fi
done

log_info "========== Disk Sentinel finished at $(date) =========="
