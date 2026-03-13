#!/bin/bash
# shellcheck disable=SC2329
# noba-lib.sh – Shared functions for Nobara automation scripts

CONFIG_FILE="${NOBA_CONFIG:-$HOME/.config/noba/config.yaml}"

# Colors (may be unused in this file, but used by sourcing scripts)
RED='\033[0;31m'
GREEN='\033[0;32m'
YELLOW='\033[1;33m'
BLUE='\033[0;34m'
CYAN='\033[0;36m'
NC='\033[0m' # No Color

# -------------------------------------------------------------------
# Logging functions
# -------------------------------------------------------------------
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
log_success() {
    echo -e "${GREEN}[SUCCESS]${NC} $*"
}

# -------------------------------------------------------------------
# Configuration helpers (with fallback if yq not available)
# -------------------------------------------------------------------
# Fallback versions (used if yq is missing)
get_config() {
    echo "$2"   # just return the default
}
get_config_array() {
    return 0    # return nothing
}

load_config() {
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

    # Override get_config with real yq version
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

    get_config_array() {
        local key="$1"
        yq eval "$key[]" "$CONFIG_FILE" 2>/dev/null | grep -v '^null$'
    }

    CONFIG_LOADED=true
    log_debug "Loaded configuration from $CONFIG_FILE"
    return 0
}

# -------------------------------------------------------------------
# Utility functions
# -------------------------------------------------------------------
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

make_temp_dir() {
    local base="${1:-/tmp}"
    mktemp -d "$base/noba.XXXXXXXXXX"
}

human_size() {
    local bytes=$1
    if command -v numfmt &>/dev/null; then
        numfmt --to=iec "$bytes"
    else
        echo "$bytes bytes"
    fi
}
