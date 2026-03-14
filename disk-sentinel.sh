#!/bin/bash
# disk-sentinel.sh – Monitor disk space and alert when threshold exceeded
# Version: 2.2.1

set -euo pipefail

SCRIPT_DIR="$(cd "$(dirname "${BASH_SOURCE[0]}")" && pwd)"
# shellcheck source=./noba-lib.sh
source "$SCRIPT_DIR/noba-lib.sh"

# -------------------------------------------------------------------
# Default configuration
# -------------------------------------------------------------------
THRESHOLD="${THRESHOLD:-85}"
TARGETS=()
DEFAULT_TARGETS=("/" "/home")
CLEANUP="${CLEANUP:-true}"
EMAIL="${EMAIL:-strikerke@gmail.com}"
LOG_FILE="${LOG_FILE:-$HOME/.local/share/disk-sentinel.log}"
DRY_RUN=false
# shellcheck disable=SC2034
VERBOSE=false
# Filesystem types to ignore (regex)
IGNORE_FS="^(proc|sysfs|tmpfs|devpts|securityfs|fusectl|debugfs|pstore|hugetlbfs|mqueue|configfs|devtmpfs|binfmt_misc|overlay)$"

# -------------------------------------------------------------------
# Load user configuration
# -------------------------------------------------------------------
if command -v get_config &>/dev/null; then
    targets_from_config=$(get_config_array ".disk.targets")
    if [ -n "$targets_from_config" ]; then
        mapfile -t TARGETS <<< "$targets_from_config"
    fi
    THRESHOLD="$(get_config ".disk.threshold" "$THRESHOLD")"
    CLEANUP="$(get_config ".disk.cleanup_enabled" "$CLEANUP")"
    EMAIL="$(get_config ".email" "$EMAIL")"
    IGNORE_FS="$(get_config ".disk.ignore_fs" "$IGNORE_FS")"

    config_log_dir="$(get_config ".logs.dir" "")"
    if [ -n "$config_log_dir" ]; then
        LOG_FILE="$config_log_dir/disk-sentinel.log"
    fi
fi

if [ ${#TARGETS[@]} -eq 0 ]; then
    TARGETS=("${DEFAULT_TARGETS[@]}")
fi

# -------------------------------------------------------------------
# Helper functions
# -------------------------------------------------------------------
show_version() {
    echo "disk-sentinel.sh version 2.2.1"
    exit 0
}

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

# Send email via msmtp or mail
send_email() {
    local subject="$1"
    local body="$2"
    if [ -z "$EMAIL" ]; then
        log_warn "No email recipient set – skipping notification."
        return
    fi

    if command -v msmtp &>/dev/null; then
        printf "Subject: %s\n\n%s\n" "$subject" "$body" | msmtp "$EMAIL"
        log_info "Email sent to $EMAIL via msmtp"
    elif command -v mail &>/dev/null; then
        echo -e "$body" | mail -s "$subject" "$EMAIL"
        log_info "Email sent to $EMAIL via mail"
    else
        log_warn "No mail program found – cannot send email."
    fi
}

# Run a command with sudo seamlessly
run_sudo() {
    local cmd_desc="$1"
    shift
    if [ "$DRY_RUN" = true ]; then
        log_info "[DRY RUN] Would run (sudo): $*"
        return 0
    fi
    log_debug "Running (sudo): $cmd_desc"

    # -n prevents sudo from blocking and asking for a password in automation
    if sudo -n true 2>/dev/null; then
        if sudo "$@"; then
            return 0
        else
            log_warn "Command failed: $*"
            return 1
        fi
    else
        log_warn "sudo not available or requires password – skipping $cmd_desc"
        return 1
    fi
}

# -------------------------------------------------------------------
# Parse command-line arguments
# -------------------------------------------------------------------
if ! PARSED_ARGS=$(getopt -o t:nv -l threshold:,dry-run,verbose,help,version -- "$@"); then
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
        *)              log_error "Invalid argument: $1"; exit 1 ;;
    esac
done

# -------------------------------------------------------------------
# Pre-flight checks & Setup
# -------------------------------------------------------------------
check_deps df awk du sort head date mkdir

if ! [[ "$THRESHOLD" =~ ^[0-9]+$ ]] || [ "$THRESHOLD" -lt 0 ] || [ "$THRESHOLD" -gt 100 ]; then
    die "Threshold must be a number between 0 and 100."
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

    # Skip virtual filesystems
    if [[ "$fstype" =~ $IGNORE_FS ]]; then
        log_debug "Skipping $mount (virtual filesystem $fstype)"
        continue
    fi

    log_info "$mount: ${usage}% used (fstype: $fstype)"

    if [ "$usage" -ge "$THRESHOLD" ]; then
        log_warn "WARNING: $mount exceeded ${THRESHOLD}% threshold."

        # Prepare email body. Use -x (stay on one fs) and -d 3 (max depth) for FAST directory sizing
        email_body="Disk space alert for $mount on $(hostname) at $(date)\n"
        email_body+="Usage: ${usage}% (threshold ${THRESHOLD}%)\n\n"
        email_body+="Top directories by size (max depth 3):\n"
        email_body+="$(sudo -n du -h -x -d 3 "$target" 2>/dev/null | sort -rh | head -10)\n"

        # Cleanup if enabled and not dry run
        if [ "$CLEANUP" = true ]; then
            log_info "Starting cleanup on $mount..."

            if [ "$DRY_RUN" = false ]; then
                # Package manager caches
                if command -v dnf &>/dev/null; then
                    run_sudo "cleaning DNF cache" dnf clean all
                fi

                # Flatpak unused runtimes (huge space saver on Nobara)
                if command -v flatpak &>/dev/null; then
                    run_sudo "cleaning unused flatpak runtimes" flatpak uninstall --unused -y
                fi

                # User cache (Safe targeted cleanup)
                log_info "Cleaning ~/.cache (thumbnails and 30+ day old files)..."
                rm -rf "$HOME/.cache/thumbnails/"* 2>/dev/null || true
                find "$HOME/.cache" -type f -atime +30 -delete 2>/dev/null || true

                # System temp files older than 2 days
                run_sudo "cleaning /tmp (files older than 2 days)" find /tmp -type f -atime +2 -delete

                # Journal vacuum
                if command -v journalctl &>/dev/null; then
                    run_sudo "vacuuming systemd journals" journalctl --vacuum-time=3d
                fi

                # Get new usage
                new_usage=$(df --output=pcent "$target" 2>/dev/null | tail -1 | sed 's/%//')
                email_body+="\nCleanup performed. New usage: ${new_usage}%"
                log_info "Cleanup completed. New usage: ${new_usage}%"
            else
                email_body+="\nDRY RUN: No actual changes made."
            fi
        else
            email_body+="\nNo cleanup performed (cleanup disabled)."
        fi

        # Send email
        if [ "$DRY_RUN" = false ]; then
            send_email "⚠ Disk Space Alert: $mount at ${usage}%" "$email_body"
        else
            log_info "[DRY RUN] Would send email alert:\n$email_body"
        fi
    else
        log_info "$mount usage is OK."
    fi
done

log_info "========== Disk Sentinel finished at $(date) =========="
