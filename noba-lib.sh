#!/bin/bash
# noba-lib.sh – Shared functions for Nobara automation scripts
# Version: 2.3.0
# This file should be sourced by other scripts, not executed directly.

# Prevent multiple inclusions
if [[ -n "${_NOBA_LIB_LOADED:-}" ]]; then
    return 0
fi
_NOBA_LIB_LOADED=1
export NOBA_LIB_VERSION="2.3.0"

# -------------------------------------------------------------------
# Configuration file location
# -------------------------------------------------------------------
: "${NOBA_CONFIG:=$HOME/.config/noba/config.yaml}"
export CONFIG_FILE="$NOBA_CONFIG"

# Cache dependency checks on load
if command -v yq &>/dev/null; then
    export _NOBA_YQ_AVAILABLE=true
else
    export _NOBA_YQ_AVAILABLE=false
fi

# -------------------------------------------------------------------
# Color support
# -------------------------------------------------------------------
if [[ -t 1 ]] && [[ -z "${NO_COLOR:-}" ]]; then
    export RED='\033[0;31m'
    export GREEN='\033[0;32m'
    export YELLOW='\033[1;33m'
    export BLUE='\033[0;34m'
    export CYAN='\033[0;36m'
    export NC='\033[0m'
else
    export RED='' GREEN='' YELLOW='' BLUE='' CYAN='' NC=''
fi

# -------------------------------------------------------------------
# Logging & Alerting Functions
# -------------------------------------------------------------------
_timestamp() { date +'%Y-%m-%d %H:%M:%S'; }

log_info() { printf "${GREEN}[%s] [INFO]${NC} %s\n" "$(_timestamp)" "$*"; }
log_warn() { printf "${YELLOW}[%s] [WARN]${NC} %s\n" "$(_timestamp)" "$*" >&2; }
log_error() { printf "${RED}[%s] [ERROR]${NC} %s\n" "$(_timestamp)" "$*" >&2; }
log_debug() { if [[ "${VERBOSE:-false}" == true ]]; then printf "${CYAN}[%s] [DEBUG]${NC} %s\n" "$(_timestamp)" "$*"; fi; }
log_success() { printf "${GREEN}[%s] [SUCCESS]${NC} %s\n" "$(_timestamp)" "$*"; }

die() {
    log_error "$*"
    exit 1
}

# Universal Alerting (Triggers KDE UI + optional n8n Webhook)
send_alert() {
    local level="$1"  # info, warn, error
    local title="$2"
    local message="$3"

    # 1. Trigger KDE Desktop Notification
    if command -v notify-send &>/dev/null; then
        local icon="dialog-information"
        local urgency="normal"
        if [ "$level" = "error" ]; then icon="dialog-error"; urgency="critical"; fi
        if [ "$level" = "warn" ]; then icon="dialog-warning"; fi
        notify-send -u "$urgency" -i "$icon" "$title" "$message" || true
    fi

    # 2. Trigger remote n8n/Discord Webhook (if defined in config)
    local webhook_url
    webhook_url=$(get_config ".notifications.webhook_url" "")
    if [[ -n "$webhook_url" ]] && command -v curl &>/dev/null; then
        # Simple JSON payload, adjust based on what your n8n expects
        curl -s -X POST -H "Content-Type: application/json" \
             -d "{\"level\":\"$level\",\"title\":\"$title\",\"message\":\"$message\"}" \
             "$webhook_url" -o /dev/null || true
    fi
}

# -------------------------------------------------------------------
# Configuration helpers
# -------------------------------------------------------------------
get_config() {
    local key="$1"
    local default="${2:-}"

    if [[ "$_NOBA_YQ_AVAILABLE" == true && -f "$CONFIG_FILE" && -r "$CONFIG_FILE" ]]; then
        local value
        value=$(yq eval "$key" "$CONFIG_FILE" 2>/dev/null)
        if [[ -n "$value" && "$value" != "null" ]]; then
            echo "$value"
            return 0
        fi
    fi
    echo "$default"
}

get_config_array() {
    local key="$1"
    if [[ "$_NOBA_YQ_AVAILABLE" == true && -f "$CONFIG_FILE" && -r "$CONFIG_FILE" ]]; then
        yq eval "${key}[]" "$CONFIG_FILE" 2>/dev/null | grep -v '^null$' || true
    fi
}

# -------------------------------------------------------------------
# Reliability Utilities (Locks & Retries)
# -------------------------------------------------------------------

# Retries a command up to N times with a static delay.
# Usage: retry 3 5 ping -c 1 vdhnas.vannieuwenhove.org
retry() {
    local max_attempts="$1"
    local delay="$2"
    shift 2
    local attempt=1

    while ! "$@"; do
        if (( attempt >= max_attempts )); then
            log_error "Command failed after $max_attempts attempts: $*"
            return 1
        fi
        log_warn "Attempt $attempt/$max_attempts failed. Retrying in ${delay}s: $*"
        sleep "$delay"
        ((attempt++))
    done
    return 0
}

# Prevents a script from running twice concurrently.
# Usage: acquire_lock "my_script_name"
acquire_lock() {
    local lock_name="$1"
    local lock_file="/tmp/noba_${lock_name}.lock"
    # Use File Descriptor 200 for locking
    eval "exec 200>\"$lock_file\""
    if ! flock -n 200; then
        die "Another instance of $lock_name is currently running."
    fi
}

# -------------------------------------------------------------------
# Data Formatting Utilities
# -------------------------------------------------------------------

# Converts seconds into a human-readable string (e.g., "1h 5m 12s")
format_duration() {
    local t=$1
    local d=$((t/86400))
    local h=$((t/3600%24))
    local m=$((t/60%60))
    local s=$((t%60))
    [[ $d -gt 0 ]] && printf "%dd " $d
    [[ $h -gt 0 ]] && printf "%dh " $h
    [[ $m -gt 0 ]] && printf "%dm " $m
    printf "%ds\n" $s
}

human_size() {
    local bytes="$1"
    if [[ ! "$bytes" =~ ^[0-9]+$ ]]; then
        echo "0 B"
        return 1
    fi
    if command -v numfmt &>/dev/null; then
        numfmt --to=iec "$bytes"
    else
        echo "$bytes bytes"
    fi
}

# -------------------------------------------------------------------
# System Utilities
# -------------------------------------------------------------------
check_deps() {
    local missing=()
    local cmd
    for cmd in "$@"; do
        if ! command -v "$cmd" &>/dev/null; then
            missing+=("$cmd")
        fi
    done
    if [[ ${#missing[@]} -gt 0 ]]; then
        log_error "Missing required commands: ${missing[*]}"
        return 1
    fi
    return 0
}

make_temp_dir() {
    local base="${1:-/tmp}"
    local template="${2:-noba.XXXXXXXXXX}"
    if [[ ! -d "$base" ]]; then
        log_error "Base directory '$base' does not exist"
        return 1
    fi
    mktemp -d "$base/$template"
}

make_temp_dir_auto() {
    local temp_dir
    temp_dir=$(make_temp_dir "$@") || return 1

    local existing_trap
    existing_trap=$(trap -p EXIT | sed "s/^trap -- '//;s/' EXIT$//")
    # shellcheck disable=SC2064
    trap "${existing_trap:+$existing_trap; }rm -rf \"$temp_dir\"" EXIT

    echo "$temp_dir"
}

confirm() {
    local prompt="$1"
    local default="${2:-n}"

    if [[ ! -t 0 ]] || [[ ! -t 1 ]]; then
        [[ "$default" == "y" ]] && return 0 || return 1
    fi

    local answer
    while true; do
        read -rp "$prompt (y/n) [${default}]: " answer
        case "${answer:-$default}" in
            [Yy]*) return 0 ;;
            [Nn]*) return 1 ;;
            *) echo "Please answer y or n." ;;
        esac
    done
}

check_root() {
    if [[ $EUID -ne 0 ]]; then
        die "This script must be run as root."
    fi
}

# -------------------------------------------------------------------
# Optional Overrides
# -------------------------------------------------------------------
if [[ -f "$HOME/.config/noba/noba-lib.local.sh" ]]; then
    # shellcheck source=/dev/null
    source "$HOME/.config/noba/noba-lib.local.sh"
fi
