#!/bin/bash
# noba-lib.sh – Shared functions for Nobara automation scripts

# Configuration
CONFIG_FILE="${NOBA_CONFIG:-$HOME/.config/noba/config.yaml}"

# Colors (for output) – may be unused in this file, but used by sourcing scripts
# shellcheck disable=SC2034
RED='\033[0;31m'
GREEN='\033[0;32m'
YELLOW='\033[1;33m'
# shellcheck disable=SC2034
# shellcheck disable=SC2034
# shellcheck disable=SC2034
BLUE='\033[0;34m'
CYAN='\033[0;36m'
NC='\033[0m' # No Color

# Logging functions
log_info() {
    echo -e "${GREEN}[INFO]${NC} $*"
}

log_warn() {
    echo -e "${YELLOW}[WARN]${NC} $*" >&2
}

log_error() {
    echo -e "${RED}[ERROR]${NC} $*" >&2
}

log_debug() {
    if [ "${VERBOSE:-false}" = true ]; then
        echo -e "${CYAN}[DEBUG]${NC} $*"
    fi
}

# Load YAML configuration with fallback
# shellcheck disable=SC2034
# Usage: load_config [prefix]
# shellcheck disable=SC2034
# Sets global variables: CONFIG_LOADED=true if successful
# shellcheck disable=SC2034
load_config() {
    local prefix="${1:-}"
    # shellcheck disable=SC2034
    CONFIG_LOADED=false

    if ! command -v yq &>/dev/null; then
        log_debug "yq not installed, using defaults."
        return 1
    fi

    if [ ! -f "$CONFIG_FILE" ]; then
        log_debug "Config file $CONFIG_FILE not found, using defaults."
        return 1
    fi

    if [ ! -r "$CONFIG_FILE" ]; then
        log_warn "Config file $CONFIG_FILE exists but is not readable. Using defaults."
        return 1
    fi

    # Read a value from YAML
    # Usage: get_config key [default]
    get_config() {
        local key="$1"
        local default="${2:-}"
        local value
        value=$(yq eval "$key" "$CONFIG_FILE" 2>/dev/null)
        if [ -n "$value" ] && [ "$value" != "null" ]; then
            echo "$value"
        else
            echo "$default"
        fi
    }

    # Read an array from YAML (one line per element)
    # Usage: get_config_array key
# shellcheck disable=SC2034
    get_config_array() {
        local key="$1"
# shellcheck disable=SC2034
        # shellcheck disable=SC1087
        yq eval "$key[]" "$CONFIG_FILE" 2>/dev/null | grep -v '^null$'
# shellcheck disable=SC2034
    }

    CONFIG_LOADED=true
    log_debug "Loaded configuration from $CONFIG_FILE"
    return 0
}

# Check required commands
check_deps() {
    local missing=()
    for cmd in "$@"; do
        if ! command -v "$cmd" &>/dev/null; then
            missing+=("$cmd")
        fi
    done
    if [ ${#missing[@]} -gt 0 ]; then
        log_error "Missing required commands: ${missing[*]}"
        return 1
    fi
    return 0
}

# Portable temporary directory creation
make_temp_dir() {
    local base="${1:-/tmp}"
    mktemp -d "$base/noba.XXXXXXXXXX"
}

# Human-readable sizes
human_size() {
    local bytes=$1
    if command -v numfmt &>/dev/null; then
        numfmt --to=iec "$bytes"
    else
        echo "$bytes bytes"
    fi
}
