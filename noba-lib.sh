#!/bin/bash
# noba-lib.sh – Shared functions for Nobara automation scripts
# Version: 2.2.1
# This file should be sourced by other scripts, not executed directly.

# Prevent multiple inclusions
if [[ -n "${_NOBA_LIB_LOADED:-}" ]]; then
    return 0
fi
export _NOBA_LIB_LOADED=1
export NOBA_LIB_VERSION="2.2.1"

# -------------------------------------------------------------------
# Configuration file location (can be overridden by environment)
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
# Color support – disable if not a terminal or NO_COLOR is set
# -------------------------------------------------------------------
if [[ -t 1 ]] && [[ -z "${NO_COLOR:-}" ]]; then
    export RED='\033[0;31m'
    export GREEN='\033[0;32m'
    export YELLOW='\033[1;33m'
    export BLUE='\033[0;34m'
    export CYAN='\033[0;36m'
    export NC='\033[0m'  # No Color
else
    export RED='' GREEN='' YELLOW='' BLUE='' CYAN='' NC=''
fi

# -------------------------------------------------------------------
# Logging functions (Includes Timestamps for Automation)
# -------------------------------------------------------------------
_timestamp() { date +'%Y-%m-%d %H:%M:%S'; }

log_info() {
    printf "${GREEN}[%s] [INFO]${NC} %s\n" "$(_timestamp)" "$*"
}
log_warn() {
    printf "${YELLOW}[%s] [WARN]${NC} %s\n" "$(_timestamp)" "$*" >&2
}
log_error() {
    printf "${RED}[%s] [ERROR]${NC} %s\n" "$(_timestamp)" "$*" >&2
}
log_debug() {
    if [[ "${VERBOSE:-false}" == true ]]; then
        printf "${CYAN}[%s] [DEBUG]${NC} %s\n" "$(_timestamp)" "$*"
    fi
}
log_success() {
    printf "${GREEN}[%s] [SUCCESS]${NC} %s\n" "$(_timestamp)" "$*"
}
die() {
    log_error "$*"
    exit 1
}

# -------------------------------------------------------------------
# Configuration helpers
# -------------------------------------------------------------------
# Get a scalar value from the YAML config. Usage:
#   value=$(get_config ".some.key" "default")
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

# Get an array from the YAML config (one element per line). Usage:
#   while IFS= read -r item; do ...; done < <(get_config_array ".some.list")
get_config_array() {
    local key="$1"
    if [[ "$_NOBA_YQ_AVAILABLE" == true && -f "$CONFIG_FILE" && -r "$CONFIG_FILE" ]]; then
        yq eval "${key}[]" "$CONFIG_FILE" 2>/dev/null | grep -v '^null$' || true
    fi
}

# -------------------------------------------------------------------
# Utility functions
# -------------------------------------------------------------------
# Check that required commands are available. Exits with error if any missing.
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

# Create a temporary directory safely. Usage:
#   temp_dir=$(make_temp_dir) || exit 1
make_temp_dir() {
    local base="${1:-/tmp}"
    local template="${2:-noba.XXXXXXXXXX}"
    if [[ ! -d "$base" ]]; then
        log_error "Base directory '$base' does not exist"
        return 1
    fi
    mktemp -d "$base/$template"
}

# Create a temporary directory and safely append it to the EXIT trap.
make_temp_dir_auto() {
    local temp_dir
    temp_dir=$(make_temp_dir "$@") || return 1

    # Extract existing trap, if any, and append our cleanup routine safely
    local existing_trap
    existing_trap=$(trap -p EXIT | sed "s/^trap -- '//;s/' EXIT$//")

    # shellcheck disable=SC2064
    trap "${existing_trap:+$existing_trap; }rm -rf \"$temp_dir\"" EXIT

    echo "$temp_dir"
}

# Convert bytes to human-readable format
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

# Interactive confirmation prompt.
confirm() {
    local prompt="$1"
    local default="${2:-n}"

    # Non-interactive guard: check if stdin and stdout are terminals
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

# Check if the script is running as root.
check_root() {
    if [[ $EUID -ne 0 ]]; then
        die "This script must be run as root."
    fi
}

# -------------------------------------------------------------------
# Optional: source additional local overrides if they exist
# -------------------------------------------------------------------
if [[ -f "$HOME/.config/noba/noba-lib.local.sh" ]]; then
    # shellcheck source=/dev/null
    source "$HOME/.config/noba/noba-lib.local.sh"
fi
