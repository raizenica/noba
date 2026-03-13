#!/bin/bash
# config-check.sh – Validate configuration and check dependencies
# Version: 2.2.0

set -euo pipefail

SCRIPT_DIR="$(cd "$(dirname "${BASH_SOURCE[0]}")" && pwd)"
# shellcheck source=/dev/null
source "$SCRIPT_DIR/noba-lib.sh"

# -------------------------------------------------------------------
# Default configuration
# -------------------------------------------------------------------
VERBOSE=false
CHECK_YAML=true
CHECK_OLD=true
OLD_CONFIG_FILE="${OLD_CONFIG_FILE:-$HOME/.config/automation.conf}"
NEW_CONFIG_FILE="${NEW_CONFIG_FILE:-$HOME/.config/noba/config.yaml}"
LOG_DIR="$HOME/.local/share"

# -------------------------------------------------------------------
# Load user configuration
# -------------------------------------------------------------------
if command -v get_config &>/dev/null; then
    config_log_dir="$(get_config ".logs.dir" "$LOG_DIR")"
    # Expand tilde if present
    LOG_DIR="${config_log_dir/#\~/$HOME}"
fi

# -------------------------------------------------------------------
# Helper functions
# -------------------------------------------------------------------
show_version() {
    echo "config-check.sh version 2.2.0"
    exit 0
}

show_help() {
    cat <<EOF
Usage: $0 [OPTIONS]

Check configuration and dependencies for the Nobara Automation Suite.

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

check_cmd() {
    local cmd="$1"
    local description="${2:-$cmd}"
    if command -v "$cmd" &>/dev/null; then
        log_success "✓ $description"
        if [ "$VERBOSE" = true ]; then
            version=$("$cmd" --version 2>/dev/null | head -1 || echo "Version info not available")
            [ -n "$version" ] && echo "      $version"
        fi
        return 0
    else
        log_error "✗ $description (not found)"
        return 1
    fi
}

# -------------------------------------------------------------------
# Parse command-line arguments
# -------------------------------------------------------------------
if ! PARSED_ARGS=$(getopt -o vq -l verbose,quiet,no-yaml,no-old,help,version -- "$@"); then
    show_help
fi
eval set -- "$PARSED_ARGS"

while true; do
    case "$1" in
        -v|--verbose)   VERBOSE=true; shift ;;
        -q|--quiet)     exec 1>/dev/null; shift ;; # redirect stdout, keep stderr
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
if [ "$CHECK_OLD" = true ]; then
    log_info "Old config file: $OLD_CONFIG_FILE"
    if [ -f "$OLD_CONFIG_FILE" ]; then
        log_success "File exists"
        if [ -r "$OLD_CONFIG_FILE" ]; then
            log_success "File is readable"
            if [ "$VERBOSE" = true ]; then
                log_info "Variables defined:"
                grep -E '^[A-Za-z_]+=' "$OLD_CONFIG_FILE" | sed 's/^/    /' || echo "    (none)"
            fi
        else
            log_error "File not readable"
        fi
    else
        log_info "File not found (Deprecated, this is fine)"
    fi
fi

# 2. Check new YAML config
if [ "$CHECK_YAML" = true ]; then
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

declare -A SCRIPT_CMDS=(
    ["common"]="rsync msmtp findmnt flock jq yq convert md5sum sha256sum notify-send kdialog fuser"
    ["backup"]="rsync msmtp findmnt flock"
    ["cloud"]="rclone flock"
    ["verifier"]="find shuf md5sum"
    ["checksum"]="find jq yq"
    ["disk"]="df du msmtp"
    ["images"]="convert"
    ["organizer"]="find mv fuser"
    ["hogwarts"]="find"
    ["motd"]="curl jq"
    ["dashboard"]="find"
    ["notify"]="notify-send"
    ["web"]="python3 ss"
    ["tui"]="dialog"
)

# Check common tools
log_info "  Common tools:"
for cmd in ${SCRIPT_CMDS["common"]}; do
    check_cmd "$cmd"
done

# Check script-specific tools
for script in backup cloud verifier checksum disk images organizer hogwarts motd dashboard notify web tui; do
    desc="${script}"
    case $script in
        backup)    desc="backup-to-nas.sh" ;;
        cloud)     desc="cloud-backup.sh" ;;
        verifier)  desc="backup-verifier.sh" ;;
        checksum)  desc="checksum.sh" ;;
        disk)      desc="disk-sentinel.sh" ;;
        images)    desc="images-to-pdf.sh" ;;
        organizer) desc="organize-downloads.sh" ;;
        hogwarts)  desc="run-hogwarts-trainer.sh" ;;
        motd)      desc="motd-generator.sh" ;;
        dashboard) desc="noba-dashboard.sh" ;;
        notify)    desc="backup-notify.sh" ;;
        web)       desc="noba-web.sh" ;;
        tui)       desc="noba-tui.sh" ;;
    esac
    log_info "  $desc:"
    for cmd in ${SCRIPT_CMDS[$script]}; do
        check_cmd "$cmd"
    done
done

# Special checks
if ! sudo -n true 2>/dev/null; then
    log_warn "sudo requires a password – unattended system cleanup operations will fail."
fi

# Check for clipboard tool for checksum.sh
if ! command -v wl-copy &>/dev/null && ! command -v xclip &>/dev/null; then
    log_warn "No clipboard tool (wl-copy/xclip) found – checksum.sh copy to clipboard will not work."
fi

# 4. Check log directories
log_info "Log directory context:"
for logname in backup-to-nas backup-verifier cloud-backup disk-sentinel download-organizer noba-web noba-web-server; do
    logfile="$LOG_DIR/$logname.log"
    if [ -f "$logfile" ]; then
        log_success "$logfile exists"
        if [ "$VERBOSE" = true ]; then
            echo "      Last 2 lines of $(basename "$logfile"):"
            tail -n 2 "$logfile" 2>/dev/null | sed 's/^/      /'
        fi
    else
        log_info "$logfile not found (will be created on first run)"
    fi
done

# 5. Configuration suggestions
log_info "Configuration suggestions:"
if [ -f "$NEW_CONFIG_FILE" ] && command -v yq &>/dev/null; then
    email=$(yq eval '.email // ""' "$NEW_CONFIG_FILE" 2>/dev/null || true)
    if [ -n "$email" ] && ! echo "$email" | grep -q "@"; then
        log_warn "root .email in YAML config may not be a valid address: $email"
    fi

    backup_dest=$(yq eval '.backup.dest // ""' "$NEW_CONFIG_FILE" 2>/dev/null || true)
    if [ -n "$backup_dest" ] && [ ! -d "$backup_dest" ]; then
        log_warn "backup.dest directory does not currently exist or is not mounted: $backup_dest"
    fi
fi

log_success "Check complete."

# Determine overall exit status
critical_missing=0
for cmd in rsync rclone msmtp yq jq fuser md5sum python3; do
    if ! command -v "$cmd" &>/dev/null; then
        critical_missing=1
        break
    fi
done

if [ "$critical_missing" -eq 1 ]; then
    log_error "One or more critical dependencies are missing. Please run 'noba setup' or manually install them."
    exit 1
else
    exit 0
fi
