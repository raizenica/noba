#!/bin/bash
# config-check.sh – Validate configuration and check dependencies

set -euo pipefail

SCRIPT_DIR="$(cd "$(dirname "${BASH_SOURCE[0]}")" && pwd)"
# shellcheck source=/dev/null
# shellcheck source=/dev/null
source "$SCRIPT_DIR/noba-lib.sh"

# -------------------------------------------------------------------
# Default configuration
# -------------------------------------------------------------------
VERBOSE=false
# shellcheck disable=SC2034
CHECK_ALL=true
OLD_CONFIG_FILE="${OLD_CONFIG_FILE:-$HOME/.config/automation.conf}"
NEW_CONFIG_FILE="${NEW_CONFIG_FILE:-$HOME/.config/noba/config.yaml}"

# -------------------------------------------------------------------
# Load user configuration (optional)
# -------------------------------------------------------------------
load_config
if [ "$CONFIG_LOADED" = true ]; then
    # Override paths from YAML if defined
    logs_dir="$(get_config ".logs.dir" "$HOME/.local/share/noba")"
    logs_dir="${logs_dir/#\~/$HOME}"
fi

# -------------------------------------------------------------------
# Helper functions
# -------------------------------------------------------------------
show_version() {
    echo "config-check.sh version 1.0"
    exit 0
}

show_help() {
    cat <<EOF
Usage: $0 [OPTIONS]

Check configuration and dependencies for Nobara automation scripts.

Options:
  -v, --verbose        Show detailed information (versions, file contents)
  -q, --quiet          Only show errors (minimal output)
  --no-yaml            Skip checking the new YAML config
  --no-old             Skip checking the old automation.conf
  --help               Show this help message
  --version            Show version information
EOF
    exit 0
}

# Function to check command availability (returns 0 if found)
check_cmd() {
    local cmd="$1"
    local description="${2:-$cmd}"
    if command -v "$cmd" &>/dev/null; then
        log_success "✓ $description"
        if [ "$VERBOSE" = true ]; then
            version=$("$cmd" --version 2>/dev/null | head -1)
            [ -n "$version" ] && echo "      $version"
        fi
        return 0
    else
        log_error "✗ $description (not found)"
        return 1
    fi
}

# Check a list of commands, optionally critical
check_deps_list() {
    local -n list=$1
    local critical="${2:-false}"
    local missing=0
    for cmd in "${list[@]}"; do
        if ! check_cmd "$cmd"; then
            ((missing++))
        fi
    done
    if [ "$critical" = true ] && [ "$missing" -gt 0 ]; then
        return 1
    fi
    return 0
}

# -------------------------------------------------------------------
# Parse command-line arguments
# -------------------------------------------------------------------
PARSED_ARGS=$(getopt -o vq -l verbose,quiet,no-yaml,no-old,help,version -- "$@")
if ! some_command; then
    show_help
fi
eval set -- "$PARSED_ARGS"

while true; do
    case "$1" in
        -v|--verbose)   VERBOSE=true; shift ;;
        -q|--quiet)     # suppress normal output, only errors/warnings
            exec 3>&1
            exec 1>/dev/null
            shift
            ;;
        --no-yaml)      CHECK_YAML=false; shift ;;
        --no-old)       CHECK_OLD=false; shift ;;
        --help)         show_help ;;
        --version)      show_version ;;
        --)             shift; break ;;
        *)              break ;;
    esac
done

# -------------------------------------------------------------------
# Main
# -------------------------------------------------------------------
log_info "=== Configuration & Dependency Check ==="

# 1. Check old config file (automation.conf)
if [ "${CHECK_OLD:-true}" = true ]; then
    log_info "Old config file: $OLD_CONFIG_FILE"
    if [ -f "$OLD_CONFIG_FILE" ]; then
        log_success "File exists"
        if [ -r "$OLD_CONFIG_FILE" ]; then
            log_success "File is readable"
            if [ "$VERBOSE" = true ]; then
                log_info "Variables defined:"
                grep -E '^[A-Za-z_]+=' "$OLD_CONFIG_FILE" | sed 's/^/    /' || echo "    (none)"
                log_info "File contents (with comments stripped):"
                grep -v '^[[:space:]]*#' "$OLD_CONFIG_FILE" | grep -v '^[[:space:]]*$' | sed 's/^/    /'
            fi
        else
            log_error "File not readable"
        fi
    else
        log_warn "File not found (using defaults)"
    fi
fi

# 2. Check new YAML config
if [ "${CHECK_YAML:-true}" = true ]; then
    log_info "New YAML config: $NEW_CONFIG_FILE"
    if [ -f "$NEW_CONFIG_FILE" ]; then
        log_success "File exists"
        if [ -r "$NEW_CONFIG_FILE" ]; then
            log_success "File is readable"
            if command -v yq &>/dev/null; then
                log_success "yq is available (can parse config)"
                if [ "$VERBOSE" = true ]; then
                    log_info "Config structure:"
                    yq eval '.' "$NEW_CONFIG_FILE" | sed 's/^/    /'
                fi
            else
                log_warn "yq not installed – cannot validate YAML content"
            fi
        else
            log_error "File not readable"
        fi
    else
        log_warn "File not found (using defaults)"
    fi
fi

# 3. Dependency checks
log_info "Dependency checks:"

# Define command lists by category
# shellcheck disable=SC2034
common_cmds=(
    "rsync"
    "msmtp"
    "findmnt"
    "flock"
    "jq"
    "yq"
    "convert"       # ImageMagick
    "md5sum"
    "sha256sum"
    "notify-send"
    "kdialog"       # optional
)

# shellcheck disable=SC2034
backup_cmds=(
    "rsync"
    "msmtp"
    "findmnt"
    "flock"
)

# shellcheck disable=SC2034
verifier_cmds=(
    "find"
    "shuf"
    "md5sum"
)
# shellcheck disable=SC2034
checksum_cmds=(
    "find"
    "jq"
    "yq"
    # clipboard tools: wl-copy or xclip
)
# shellcheck disable=SC2034
disk_cmds=(
    "df"
    "du"
    "msmtp"
)
# shellcheck disable=SC2034
images_cmds=(
    "convert"
)
# shellcheck disable=SC2034
organizer_cmds=(
    "find"
    "mv"
)
# shellcheck disable=SC2034
hogwarts_cmds=(
    "find"
)
# shellcheck disable=SC2034
motd_cmds=(
    "curl"
    "jq"
)
# shellcheck disable=SC2034
dashboard_cmds=(
    "find"
)
# shellcheck disable=SC2034
notify_cmds=(
    "notify-send"
)

# Check common tools first
log_info "Common tools:"
check_deps_list common_cmds false

# Check script-specific tools
log_info "Script-specific tools:"
for section in "backup" "verifier" "checksum" "disk" "images" "organizer" "hogwarts" "motd" "dashboard" "notify"; do
    case $section in
        backup)   cmds=backup_cmds; desc="backup-to-nas.sh" ;;
        verifier) cmds=verifier_cmds; desc="backup-verifier.sh" ;;
        checksum) cmds=checksum_cmds; desc="checksum.sh" ;;
        disk)     cmds=disk_cmds; desc="disk-sentinel.sh" ;;
        images)   cmds=images_cmds; desc="images-to-pdf.sh" ;;
        organizer) cmds=organizer_cmds; desc="organize-downloads.sh" ;;
        hogwarts) cmds=hogwarts_cmds; desc="run-hogwarts-trainer.sh" ;;
        motd)     cmds=motd_cmds; desc="motd-generator.sh" ;;
        dashboard) cmds=dashboard_cmds; desc="noba-dashboard.sh" ;;
        notify)   cmds=notify_cmds; desc="backup-notify.sh" ;;
    esac
    log_info "  $desc:"
    # shellcheck disable=SC2086
    check_deps_list $cmds false
done

# Special checks
if ! sudo -n true 2>/dev/null; then
    log_warn "sudo may require password – some cleanup operations might fail."
fi

# Check for clipboard tool (wl-copy or xclip) for checksum.sh
if ! command -v wl-copy &>/dev/null && ! command -v xclip &>/dev/null; then
    log_warn "No clipboard tool (wl-copy/xclip) found – checksum.sh copy to clipboard will not work."
fi

# 4. Check log directories
log_info "Log directories:"
log_base="${logs_dir:-$HOME/.local/share/noba}"
for logname in backup-to-nas backup-verifier disk-sentinel download-organizer download-organizer-undo; do
    logfile="$log_base/$logname.log"
    logdir="$(dirname "$logfile")"
    if [ -d "$logdir" ]; then
        log_success "$logdir exists"
        if [ "$VERBOSE" = true ] && [ -f "$logfile" ]; then
            echo "      Last 2 lines of $(basename "$logfile"):"
            tail -2 "$logfile" 2>/dev/null | sed 's/^/      /'
        fi
    else
        log_warn "$logdir does not exist (will be created by scripts)"
    fi
done

# 5. Configuration suggestions
log_info "Configuration suggestions:"
if [ -f "$OLD_CONFIG_FILE" ]; then
    if grep -q "EMAIL=" "$OLD_CONFIG_FILE" && ! grep -q "EMAIL=.*@" "$OLD_CONFIG_FILE"; then
        log_warn "EMAIL may not be a valid address in $OLD_CONFIG_FILE"
    fi
    if grep -q "BACKUP_DEST=" "$OLD_CONFIG_FILE" && ! grep -q "BACKUP_DEST=.*/" "$OLD_CONFIG_FILE"; then
        log_warn "BACKUP_DEST may not be a valid path in $OLD_CONFIG_FILE"
    fi
fi

if [ -f "$NEW_CONFIG_FILE" ] && command -v yq &>/dev/null; then
    # Simple check: email field in backup section
    email=$(yq eval '.backup.email // ""' "$NEW_CONFIG_FILE")
    if [ -n "$email" ] && ! echo "$email" | grep -q "@"; then
        log_warn "backup.email in YAML config may not be a valid address: $email"
    fi
fi

log_success "Check complete."

# Exit with status: 0 if all critical dependencies present
# Critical dependencies defined as those needed for essential scripts (e.g., rsync, msmtp)
critical_missing=0
for cmd in rsync msmtp findmnt flock jq convert md5sum sha256sum; do
    if ! command -v "$cmd" &>/dev/null; then
        critical_missing=1
        break
    fi
done
if [ -n "${critical_missing:-0}" ] && [ "$critical_missing" -eq 1 ]; then
    log_error "One or more critical dependencies missing."
    exit 1
else
    exit 0
fi
