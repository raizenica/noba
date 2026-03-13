#!/bin/bash
# noba-lib.sh – Shared functions for Nobara automation scripts
# Version: 2.1.0
# This file should be sourced by other scripts, not executed directly.

# Prevent multiple inclusions
if [[ -n "${_NOBA_LIB_LOADED:-}" ]]; then
    return 0
fi
_NOBA_LIB_LOADED=1

# Library version
readonly NOBA_LIB_VERSION="2.1.0"

# -------------------------------------------------------------------
# Configuration file location (can be overridden by environment)
# -------------------------------------------------------------------
: "${NOBA_CONFIG:=$HOME/.config/noba/config.yaml}"
CONFIG_FILE="$NOBA_CONFIG"

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
# Logging functions (using printf for reliability)
# -------------------------------------------------------------------
log_info() {
    printf "${GREEN}[INFO]${NC} %s\n" "$*"
}
log_warn() {
    printf "${YELLOW}[WARN]${NC} %s\n" "$*" >&2
}
log_error() {
    printf "${RED}[ERROR]${NC} %s\n" "$*" >&2
}
log_debug() {
    if [[ "${VERBOSE:-false}" = true ]]; then
        printf "${CYAN}[DEBUG]${NC} %s\n" "$*"
    fi
}
log_success() {
    printf "${GREEN}[SUCCESS]${NC} %s\n" "$*"
}
die() {
    log_error "$*"
    exit 1
}

# -------------------------------------------------------------------
# Configuration helpers – always check yq availability on the fly
# -------------------------------------------------------------------
# Get a scalar value from the YAML config. Usage:
#   value=$(get_config ".some.key" "default")
get_config() {
    local key="$1"
    local default="${2:-}"
    if command -v yq &>/dev/null && [[ -f "$CONFIG_FILE" && -r "$CONFIG_FILE" ]]; then
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
    if command -v yq &>/dev/null && [[ -f "$CONFIG_FILE" && -r "$CONFIG_FILE" ]]; then
        yq eval "$key[]" "$CONFIG_FILE" 2>/dev/null | grep -v '^null$' || true
    fi
    # else return nothing
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
# Optionally specify a base directory (default: /tmp) and a template (default: noba.XXXXXXXXXX)
make_temp_dir() {
    local base="${1:-/tmp}"
    local template="${2:-noba.XXXXXXXXXX}"
    if [[ ! -d "$base" ]]; then
        log_error "Base directory '$base' does not exist"
        return 1
    fi
    mktemp -d "$base/$template"
}

# Create a temporary directory and automatically remove it on script exit.
# Usage:
#   temp_dir=$(make_temp_dir_auto) || exit 1
#   # ... use temp_dir ...
#   # No need to clean up manually
make_temp_dir_auto() {
    local temp_dir
    temp_dir=$(make_temp_dir "$@") || return 1
    trap 'rm -rf "$temp_dir"' EXIT
    echo "$temp_dir"
}

# Convert bytes to human-readable format (e.g., 1048576 -> 1.0 MiB)
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

# Interactive confirmation prompt. Returns 0 (true) if user answers y/Y.
# In non‑interactive mode, returns default (y or n) without prompting.
# Usage:
#   if confirm "Continue?"; then ...
confirm() {
    local prompt="$1"
    local default="${2:-n}"   # default can be "y" or "n"
    if [[ ! -t 0 ]]; then
        # Non‑interactive: use default
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

# Check if the script is running as root. If not, exit with error.
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
