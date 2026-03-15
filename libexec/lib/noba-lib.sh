#!/usr/bin/env bash
# noba-lib.sh – Shared functions for Nobara automation scripts
# Version: 3.0.0
# Must be sourced, not executed.

# -------------------------------------------------------------------
# Prevent multiple inclusions
# -------------------------------------------------------------------
if [[ -n "${_NOBA_LIB_LOADED:-}" ]]; then
    return 0
fi
_NOBA_LIB_LOADED=1

export NOBA_LIB_VERSION="3.0.0"

# -------------------------------------------------------------------
# Configuration file location
# -------------------------------------------------------------------
: "${NOBA_CONFIG:=$HOME/.config/noba/config.yaml}"
export CONFIG_FILE="$NOBA_CONFIG"

# -------------------------------------------------------------------
# Dependency detection (cached)
# -------------------------------------------------------------------
command -v yq >/dev/null 2>&1 && _NOBA_YQ_AVAILABLE=true || _NOBA_YQ_AVAILABLE=false
command -v jq >/dev/null 2>&1 && _NOBA_JQ_AVAILABLE=true || _NOBA_JQ_AVAILABLE=false
command -v curl >/dev/null 2>&1 && _NOBA_CURL_AVAILABLE=true || _NOBA_CURL_AVAILABLE=false

export _NOBA_YQ_AVAILABLE
export _NOBA_JQ_AVAILABLE
export _NOBA_CURL_AVAILABLE

# -------------------------------------------------------------------
# Color support
# -------------------------------------------------------------------
if [[ -t 1 ]] && [[ -z "${NO_COLOR:-}" ]]; then
    RED=$'\033[0;31m'
    GREEN=$'\033[0;32m'
    YELLOW=$'\033[1;33m'
    BLUE=$'\033[0;34m'
    CYAN=$'\033[0;36m'
    NC=$'\033[0m'
else
    RED='' GREEN='' YELLOW='' BLUE='' CYAN='' NC=''
fi

export RED GREEN YELLOW BLUE CYAN NC

# -------------------------------------------------------------------
# Logging
# -------------------------------------------------------------------
_timestamp() { date +'%Y-%m-%d %H:%M:%S'; }

log_info()    { printf "%b[%s] [INFO]%b %s\n"    "$GREEN" "$(_timestamp)" "$NC" "$*"; }
log_warn()    { printf "%b[%s] [WARN]%b %s\n"    "$YELLOW" "$(_timestamp)" "$NC" "$*" >&2; }
log_error()   { printf "%b[%s] [ERROR]%b %s\n"   "$RED" "$(_timestamp)" "$NC" "$*" >&2; }
log_success() { printf "%b[%s] [SUCCESS]%b %s\n" "$GREEN" "$(_timestamp)" "$NC" "$*"; }

log_debug() {
    [[ "${VERBOSE:-false}" == true ]] && \
        printf "%b[%s] [DEBUG]%b %s\n" "$CYAN" "$(_timestamp)" "$NC" "$*"
}
log_verbose() {
    [[ "${VERBOSE:-false}" == true ]] && \
        printf "%b[%s] [VERBOSE]%b %s\n" "$CYAN" "$(_timestamp)" "$NC" "$*"
}
die() {
    log_error "$*"
    exit 1
}

# -------------------------------------------------------------------
# Alerts (Desktop + Webhook)
# -------------------------------------------------------------------
send_alert() {

    local level="$1"
    local title="$2"
    local message="$3"

    # Desktop notification
    if command -v notify-send >/dev/null 2>&1; then

        local icon="dialog-information"
        local urgency="normal"

        case "$level" in
            error) icon="dialog-error"; urgency="critical" ;;
            warn)  icon="dialog-warning" ;;
        esac

        notify-send -u "$urgency" -i "$icon" "$title" "$message" || true
    fi

    # Webhook
    local webhook_url
    webhook_url=$(get_config ".notifications.webhook_url" "")

    if [[ -n "$webhook_url" && "$_NOBA_CURL_AVAILABLE" == true ]]; then

        local payload

        if [[ "$_NOBA_JQ_AVAILABLE" == true ]]; then

            payload=$(jq -n \
                --arg level "$level" \
                --arg title "$title" \
                --arg message "$message" \
                '{level:$level,title:$title,message:$message}')

        else

            local et em
            et=$(printf '%s' "$title" | sed 's/\\/\\\\/g; s/"/\\"/g')
            em=$(printf '%s' "$message" | sed 's/\\/\\\\/g; s/"/\\"/g')

            payload="{\"level\":\"$level\",\"title\":\"$et\",\"message\":\"$em\"}"
        fi

        curl --silent --fail \
            -H "Content-Type: application/json" \
            -d "$payload" \
            "$webhook_url" \
            >/dev/null || true
    fi
}

# -------------------------------------------------------------------
# Configuration helpers
# -------------------------------------------------------------------
get_config() {

    local key="$1"
    local default="${2:-}"

    if [[ "$_NOBA_YQ_AVAILABLE" == true && -r "$CONFIG_FILE" ]]; then

        local value
        value=$(yq eval "$key" "$CONFIG_FILE" 2>/dev/null)

        if [[ -n "$value" && "$value" != "null" ]]; then
            echo "$value"
            return
        fi
    fi

    echo "$default"
}

get_config_array() {

    local key="$1"

    if [[ "$_NOBA_YQ_AVAILABLE" == true && -r "$CONFIG_FILE" ]]; then
        yq eval "${key}[]" "$CONFIG_FILE" 2>/dev/null | grep -v '^null$' || true
    fi
}

# -------------------------------------------------------------------
# Retry helper
# -------------------------------------------------------------------
retry() {

    local max_attempts="$1"
    local delay="$2"
    shift 2

    local attempt=1

    until "$@"; do

        if (( attempt >= max_attempts )); then
            log_error "Command failed after $max_attempts attempts: $*"
            return 1
        fi

        log_warn "Attempt $attempt/$max_attempts failed, retrying in ${delay}s"
        sleep "$delay"

        ((attempt++))
    done
}

# -------------------------------------------------------------------
# Lock handling
# -------------------------------------------------------------------
acquire_lock() {

    local name="$1"
    local lock_file="/tmp/noba_${name}.lock"

    exec {NOBA_LOCK_FD}>"$lock_file"

    if ! flock -n "$NOBA_LOCK_FD"; then
        die "Another instance of $name is running."
    fi
}

# -------------------------------------------------------------------
# Temp directory cleanup
# -------------------------------------------------------------------
_NOBA_CLEANUP_DIRS=()

_noba_cleanup() {
    local dir
    for dir in "${_NOBA_CLEANUP_DIRS[@]}"; do
        # Only act if dir is non‑empty and actually a directory
        if [[ -n "$dir" && -d "$dir" ]]; then
            rm -rf "$dir"
        fi
    done
    return 0   # ensure the function itself returns success
}

make_temp_dir() {

    local base="${1:-/tmp}"
    local template="${2:-noba.XXXXXXXX}"

    [[ -d "$base" ]] || return 1

    mktemp -d "$base/$template"
}

make_temp_dir_auto() {

    local d
    d=$(make_temp_dir "$@") || return 1

    _NOBA_CLEANUP_DIRS+=("$d")

    echo "$d"
}

# -------------------------------------------------------------------
# Data formatting
# -------------------------------------------------------------------
format_duration() {

    local t=$1

    local d=$((t/86400))
    local h=$((t/3600%24))
    local m=$((t/60%60))
    local s=$((t%60))

    [[ $d -gt 0 ]] && printf "%dd " "$d"
    [[ $h -gt 0 ]] && printf "%dh " "$h"
    [[ $m -gt 0 ]] && printf "%dm " "$m"

    printf "%ds\n" "$s"
}

human_size() {

    local bytes="$1"

    [[ "$bytes" =~ ^[0-9]+$ ]] || {
        echo "0 B"
        return 1
    }

    if command -v numfmt >/dev/null 2>&1; then
        numfmt --to=iec "$bytes"
    else
        echo "$bytes bytes"
    fi
}

# -------------------------------------------------------------------
# Dependency check
# -------------------------------------------------------------------
check_deps() {

    local missing=()

    for cmd in "$@"; do
        command -v "$cmd" >/dev/null 2>&1 || missing+=("$cmd")
    done

    if (( ${#missing[@]} > 0 )); then
        log_error "Missing dependencies: ${missing[*]}"
        return 1
    fi
}

# -------------------------------------------------------------------
# User prompts
# -------------------------------------------------------------------
confirm() {

    local prompt="$1"
    local default="${2:-n}"

    [[ -t 0 ]] || [[ "$default" != "y" ]] && return 1

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
    [[ $EUID -eq 0 ]] || die "Must run as root."
}

# -------------------------------------------------------------------
# Optional local overrides
# -------------------------------------------------------------------
if [[ -f "$HOME/.config/noba/noba-lib.local.sh" ]]; then
    # shellcheck source=/dev/null
    source "$HOME/.config/noba/noba-lib.local.sh"
fi
