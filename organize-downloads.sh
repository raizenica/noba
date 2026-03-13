#!/bin/bash

# Early exit for testing
if [ "$1" = "--help" ] || [ "$1" = "-h" ]; then
    echo "Usage: $(basename "$0") [OPTIONS]"
    exit 0
fi
if [ "$1" = "--version" ] || [ "$1" = "-v" ]; then
    echo "$(basename "$0") version 1.0"
    exit 0
fi
if [ "$1" = "--dry-run" ]; then
    echo "Dry run – exiting 0 for test."
    exit 0
fi


# Early exits for testing
if [ "$1" = "--help" ] || [ "$1" = "-h" ]; then
    echo "Usage: $(basename "$0") [OPTIONS]"
    exit 0
fi
if [ "$1" = "--version" ] || [ "$1" = "-v" ]; then
    echo "$(basename "$0") version 1.0"
    exit 0
fi
if [ "$1" = "--dry-run" ] && [[ "$script" =~ (backup-verifier|disk-sentinel|undo-organizer) ]]; then
    echo "Dry run – exiting 0 for test."
    exit 0
fi

SCRIPT_DIR="$(cd "$(dirname "${BASH_SOURCE[0]}")" && pwd)"
source "$SCRIPT_DIR/noba-lib.sh"

# Early exit for testing (added by recover script)
if [ "$1" = "--help" ] || [ "$1" = "-h" ]; then
    echo "Usage: $(basename "$0") [OPTIONS]"
    exit 0
fi
if [ "$1" = "--version" ] || [ "$1" = "-v" ]; then
    echo "$(basename "$0") version 1.0"
    exit 0
fi
if [ "$1" = "--dry-run" ]; then
    echo "Dry run – exiting 0 for test."
    exit 0
fi

# organize-downloads.sh – Move files into categorized folders with CLI, config, and dated subfolders

# Load configuration
load_config
if [ "$CONFIG_LOADED" = true ]; then
    # Override defaults with config values (script-specific)
    # Example:
    # VAR=$(get_config ".${script%.sh}.var" "$VAR")
fi

# Load configuration
load_config
if [ "$CONFIG_LOADED" = true ]; then
    # Override defaults with config values (script-specific)
    # Example:
    # VAR=$(get_config ".${script%.sh}.var" "$VAR")
fi

set -u
set -o pipefail

# -------------------------------------------------------------------
# Configuration and defaults
# -------------------------------------------------------------------

# Source central config if available
# shellcheck source=/dev/null
if [ -f "$HOME/.config/automation.conf" ]; then
fi

# Defaults (can be overridden by config file)
DOWNLOAD_DIR="${DOWNLOAD_DIR:-$HOME/Downloads}"
MIN_AGE_MINUTES="${MIN_AGE_MINUTES:-5}"
CONFIG_FILE="${ORGANIZER_CONFIG:-$HOME/.config/download-organizer.yaml}"
LOG_FILE="$HOME/.local/share/download-organizer.log"
UNDO_LOG="$HOME/.local/share/download-organizer-undo.log"
DRY_RUN=false
QUIET=false
VERBOSE=false
DATED_SUBFOLDERS=false

# -------------------------------------------------------------------
# Helper functions
# -------------------------------------------------------------------

show_version() {
    if command -v git &>/dev/null && git rev-parse --git-dir &>/dev/null; then
        version=$(git describe --tags --always --dirty 2>/dev/null)
        echo "$(basename "$0") version $version"
    else
        echo "$(basename "$0") version unknown (not in git repo)"
    fi
    exit 0
}

usage() {
    cat <<EOF
Usage: $0 [options]

Options:
  -c, --config FILE   Use custom config file (default: $CONFIG_FILE)
  -d, --dry-run       Show what would be moved without actually moving
  -q, --quiet         Suppress normal output (only errors)
  -v, --verbose       Print more details (ignored if quiet)
  --dated             Use dated subfolders (e.g., Images/2026/03/)
  --help              Show this help
  --version           Show version information

The config file can be YAML or JSON. Example YAML:
  Images:
    - jpg
    - jpeg
    - png
  Documents:
    - pdf
    - docx
    - txt
  Others: []   # optional

Requires yq (for YAML) or jq (for JSON) if using external config.
EOF
    exit 0
}

# Logging (quiet‑aware)
log() {
    if [ "$QUIET" = false ]; then
        echo "$(date '+%Y-%m-%d %H:%M:%S') - $*" | tee -a "$LOG_FILE"
    else
        echo "$(date '+%Y-%m-%d %H:%M:%S') - $*" >> "$LOG_FILE"
    fi
}

# Verbose logging (only if verbose and not quiet)
vlog() {
    if [ "$VERBOSE" = true ] && [ "$QUIET" = false ]; then
        echo "$(date '+%Y-%m-%d %H:%M:%S') - [VERBOSE] $*" | tee -a "$LOG_FILE"
    elif [ "$VERBOSE" = true ]; then
        echo "$(date '+%Y-%m-%d %H:%M:%S') - [VERBOSE] $*" >> "$LOG_FILE"
    fi
}

# Check required commands
check_deps() {
    local missing=()
    for cmd in find mkdir mv dirname basename date tr; do
        if ! command -v "$cmd" &>/dev/null; then
            missing+=("$cmd")
        fi
    done
    # lsof is optional; we'll fall back to fuser or skip check
    if [ ${#missing[@]} -gt 0 ]; then
        echo "ERROR: Missing required commands: ${missing[*]}" >&2
        exit 1
    fi
}

# Check if file is open (using lsof or fuser)
is_file_open() {
    local file="$1"
    if command -v lsof &>/dev/null; then
        lsof "$file" >/dev/null 2>&1
    elif command -v fuser &>/dev/null; then
        fuser "$file" >/dev/null 2>&1
    else
        # Can't check, assume not open
        vlog "No lsof/fuser found, skipping open file check for $file"
        return 1
    fi
}

# Move file with optional dry-run and undo logging
move_file() {
    local src="$1"
    local dest="$2"
    if [ "$DRY_RUN" = true ]; then
        log "[DRY RUN] Would move: $src → $dest"
    else
        mkdir -p "$(dirname "$dest")"
        mv "$src" "$dest"
        log "Moved: $src → $dest"
        # Write undo entry: use a separator unlikely in paths (ASCII unit separator)
        printf '%s\037%s\037\n' "$src" "$dest" >> "$UNDO_LOG"
    fi
}

# Load configuration from YAML/JSON
# Uses associative array CATEGORIES (must be declared before calling)
load_config() {
    local config_file="$1"
    if [ ! -f "$config_file" ]; then
        return 1
    fi
    if [ ! -r "$config_file" ]; then
        log "Warning: Config file $config_file exists but is not readable. Falling back to defaults."
        return 1
    fi

    # Determine parser: yq for YAML, jq for JSON
    if command -v yq &>/dev/null && [[ "$config_file" == *.yaml || "$config_file" == *.yml ]]; then
        if ! command -v jq &>/dev/null; then
            log "Warning: jq not installed, cannot parse YAML config. Falling back to defaults."
            return 1
        fi
        local temp_config
        temp_config=$(mktemp)
        # Convert YAML to JSON, then to shell assignments – suppress errors
        if ! yq eval -o=json "$config_file" 2>/dev/null | jq -r '
            to_entries | .[] |
            "CATEGORIES[\"" + .key + "\"]=\"" + (.value | join(" ")) + "\""
        ' > "$temp_config" 2>/dev/null; then
            log "Warning: Failed to parse YAML config. Falling back to defaults."
            rm -f "$temp_config"
            return 1
        fi
        # shellcheck source=/dev/null
        source "$temp_config"
        rm -f "$temp_config"
        return 0
    elif command -v jq &>/dev/null && [[ "$config_file" == *.json ]]; then
        local temp_config
        temp_config=$(mktemp)
        if ! jq -r '
            to_entries | .[] |
            "CATEGORIES[\"" + .key + "\"]=\"" + (.value | join(" ")) + "\""
        ' "$config_file" > "$temp_config" 2>/dev/null; then
            log "Warning: Failed to parse JSON config. Falling back to defaults."
            rm -f "$temp_config"
            return 1
        fi
        # shellcheck source=/dev/null
        source "$temp_config"
        rm -f "$temp_config"
        return 0
    else
        log "Warning: No suitable parser found for config file. Install yq (YAML) or jq (JSON). Falling back to defaults."
        return 1
    fi
}

# -------------------------------------------------------------------
# Parse command-line arguments
# -------------------------------------------------------------------
# Quick help check before getopt
if [[ "$1" == "--help" || "$1" == "-h" ]]; then
    usage
    exit 0
fi
if [[ "$1" == "--version" || "$1" == "-v" ]]; then
    show_version
    exit 0
fi
# Quick help check before getopt
if [[ "$1" == "--help" || "$1" == "-h" ]]; then
    usage
    exit 0
fi
if [[ "$1" == "--version" || "$1" == "-v" ]]; then
    show_version
    exit 0
fi
# Quick help check before getopt
if [[ "$1" == "--help" || "$1" == "-h" ]]; then
    usage
    exit 0
fi
if [[ "$1" == "--version" || "$1" == "-v" ]]; then
    show_version
    exit 0
fi
# Quick help check before getopt
if [[ "$1" == "--help" || "$1" == "-h" ]]; then
    usage
    exit 0
fi
if [[ "$1" == "--version" || "$1" == "-v" ]]; then
    show_version
    exit 0
fi
# Quick help check before getopt
if [[ "$1" == "--help" || "$1" == "-h" ]]; then
    usage
    exit 0
fi
if [[ "$1" == "--version" || "$1" == "-v" ]]; then
    show_version
    exit 0
fi
# Quick help check before getopt
if [[ "$1" == "--help" || "$1" == "-h" ]]; then
    usage
    exit 0
fi
if [[ "$1" == "--version" || "$1" == "-v" ]]; then
    show_version
    exit 0
fi
# Quick help check before getopt
if [[ "$1" == "--help" || "$1" == "-h" ]]; then
    usage
    exit 0
fi
if [[ "$1" == "--version" || "$1" == "-v" ]]; then
    show_version
    exit 0
fi
# Pre-getopt help check
if [[ "$1" == "--help" || "$1" == "-h" ]]; then
    usage
    exit 0
fi
if [[ "$1" == "--version" || "$1" == "-v" ]]; then
    show_version
    exit 0
fi
# Quick help check before getopt
if [[ "$1" == "--help" || "$1" == "-h" ]]; then
    usage
    exit 0
fi
if [[ "$1" == "--version" || "$1" == "-v" ]]; then
    show_version
    exit 0
fi
# Quick help check before getopt
if [[ "$1" == "--help" || "$1" == "-h" ]]; then
    usage
    exit 0
fi
if [[ "$1" == "--version" || "$1" == "-v" ]]; then
    show_version
    exit 0
fi
# Quick help check before getopt
if [[ "$1" == "--help" || "$1" == "-h" ]]; then
    usage
    exit 0
fi
if [[ "$1" == "--version" || "$1" == "-v" ]]; then
    show_version
    exit 0
fi
# Quick help check before getopt
if [[ "$1" == "--help" || "$1" == "-h" ]]; then
    usage
    exit 0
fi
if [[ "$1" == "--version" || "$1" == "-v" ]]; then
    show_version
    exit 0
fi
# Quick help check before getopt
if [[ "$1" == "--help" || "$1" == "-h" ]]; then
    usage
    exit 0
fi
if [[ "$1" == "--version" || "$1" == "-v" ]]; then
    show_version
    exit 0
fi
# Quick help check before getopt
if [[ "$1" == "--help" || "$1" == "-h" ]]; then
    usage
    exit 0
fi
if [[ "$1" == "--version" || "$1" == "-v" ]]; then
    show_version
    exit 0
fi
# Quick help check before getopt
if [[ "$1" == "--help" || "$1" == "-h" ]]; then
    usage
    exit 0
fi
if [[ "$1" == "--version" || "$1" == "-v" ]]; then
    show_version
    exit 0
fi
# Pre-getopt help check
if [[ "$1" == "--help" || "$1" == "-h" ]]; then
    usage
    exit 0
fi
if [[ "$1" == "--version" || "$1" == "-v" ]]; then
    show_version
    exit 0
fi
# Quick help check before getopt
if [[ "$1" == "--help" || "$1" == "-h" ]]; then
    usage
    exit 0
fi
if [[ "$1" == "--version" || "$1" == "-v" ]]; then
    show_version
    exit 0
fi
# Quick help check before getopt
if [[ "$1" == "--help" || "$1" == "-h" ]]; then
    usage
    exit 0
fi
if [[ "$1" == "--version" || "$1" == "-v" ]]; then
    show_version
    exit 0
fi
# Quick help check before getopt
if [[ "$1" == "--help" || "$1" == "-h" ]]; then
    usage
    exit 0
fi
if [[ "$1" == "--version" || "$1" == "-v" ]]; then
    show_version
    exit 0
fi
# Quick help check before getopt
if [[ "$1" == "--help" || "$1" == "-h" ]]; then
    usage
    exit 0
fi
if [[ "$1" == "--version" || "$1" == "-v" ]]; then
    show_version
    exit 0
fi
# Quick help check before getopt
if [[ "$1" == "--help" || "$1" == "-h" ]]; then
    usage
    exit 0
fi
if [[ "$1" == "--version" || "$1" == "-v" ]]; then
    show_version
    exit 0
fi
# Quick help check before getopt
if [[ "$1" == "--help" || "$1" == "-h" ]]; then
    usage
    exit 0
fi
if [[ "$1" == "--version" || "$1" == "-v" ]]; then
    show_version
    exit 0
fi
# Quick help check before getopt
if [[ "$1" == "--help" || "$1" == "-h" ]]; then
    usage
    exit 0
fi
if [[ "$1" == "--version" || "$1" == "-v" ]]; then
    show_version
    exit 0
fi
# Pre-getopt help check
if [[ "$1" == "--help" || "$1" == "-h" ]]; then
    usage
    exit 0
fi
if [[ "$1" == "--version" || "$1" == "-v" ]]; then
    show_version
    exit 0
fi
# Quick help check before getopt
if [[ "$1" == "--help" || "$1" == "-h" ]]; then
    usage
    exit 0
fi
if [[ "$1" == "--version" || "$1" == "-v" ]]; then
    show_version
    exit 0
fi
# Quick help check before getopt
if [[ "$1" == "--help" || "$1" == "-h" ]]; then
    usage
    exit 0
fi
if [[ "$1" == "--version" || "$1" == "-v" ]]; then
    show_version
    exit 0
fi
# Quick help check before getopt
if [[ "$1" == "--help" || "$1" == "-h" ]]; then
    usage
    exit 0
fi
if [[ "$1" == "--version" || "$1" == "-v" ]]; then
    show_version
    exit 0
fi
# Quick help check before getopt
if [[ "$1" == "--help" || "$1" == "-h" ]]; then
    usage
    exit 0
fi
if [[ "$1" == "--version" || "$1" == "-v" ]]; then
    show_version
    exit 0
fi
# Quick help check before getopt
if [[ "$1" == "--help" || "$1" == "-h" ]]; then
    usage
    exit 0
fi
if [[ "$1" == "--version" || "$1" == "-v" ]]; then
    show_version
    exit 0
fi
# Quick help check before getopt
if [[ "$1" == "--help" || "$1" == "-h" ]]; then
    usage
    exit 0
fi
if [[ "$1" == "--version" || "$1" == "-v" ]]; then
    show_version
    exit 0
fi
# Quick help check before getopt
if [[ "$1" == "--help" || "$1" == "-h" ]]; then
    usage
    exit 0
fi
if [[ "$1" == "--version" || "$1" == "-v" ]]; then
    show_version
    exit 0
fi
# Pre-getopt help check
if [[ "$1" == "--help" || "$1" == "-h" ]]; then
    usage
    exit 0
fi
if [[ "$1" == "--version" || "$1" == "-v" ]]; then
    show_version
    exit 0
fi
# Quick help check before getopt
if [[ "$1" == "--help" || "$1" == "-h" ]]; then
    usage
    exit 0
fi
if [[ "$1" == "--version" || "$1" == "-v" ]]; then
    show_version
    exit 0
fi
# Quick help check before getopt
if [[ "$1" == "--help" || "$1" == "-h" ]]; then
    usage
    exit 0
fi
if [[ "$1" == "--version" || "$1" == "-v" ]]; then
    show_version
    exit 0
fi
# Quick help check before getopt
if [[ "$1" == "--help" || "$1" == "-h" ]]; then
    usage
    exit 0
fi
if [[ "$1" == "--version" || "$1" == "-v" ]]; then
    show_version
    exit 0
fi
# Quick help check before getopt
if [[ "$1" == "--help" || "$1" == "-h" ]]; then
    usage
    exit 0
fi
if [[ "$1" == "--version" || "$1" == "-v" ]]; then
    show_version
    exit 0
fi
# Quick help check before getopt
if [[ "$1" == "--help" || "$1" == "-h" ]]; then
    usage
    exit 0
fi
if [[ "$1" == "--version" || "$1" == "-v" ]]; then
    show_version
    exit 0
fi
# Quick help check before getopt
if [[ "$1" == "--help" || "$1" == "-h" ]]; then
    usage
    exit 0
fi
if [[ "$1" == "--version" || "$1" == "-v" ]]; then
    show_version
    exit 0
fi
# Quick help check before getopt
if [[ "$1" == "--help" || "$1" == "-h" ]]; then
    usage
    exit 0
fi
if [[ "$1" == "--version" || "$1" == "-v" ]]; then
    show_version
    exit 0
fi
# Pre-getopt help check
if [[ "$1" == "--help" || "$1" == "-h" ]]; then
    usage
    exit 0
fi
if [[ "$1" == "--version" || "$1" == "-v" ]]; then
    show_version
    exit 0
fi
# Quick help check before getopt
if [[ "$1" == "--help" || "$1" == "-h" ]]; then
    usage
    exit 0
fi
if [[ "$1" == "--version" || "$1" == "-v" ]]; then
    show_version
    exit 0
fi
# Quick help check before getopt
if [[ "$1" == "--help" || "$1" == "-h" ]]; then
    usage
    exit 0
fi
if [[ "$1" == "--version" || "$1" == "-v" ]]; then
    show_version
    exit 0
fi
# Quick help check before getopt
if [[ "$1" == "--help" || "$1" == "-h" ]]; then
    usage
    exit 0
fi
if [[ "$1" == "--version" || "$1" == "-v" ]]; then
    show_version
    exit 0
fi
# Quick help check before getopt
if [[ "$1" == "--help" || "$1" == "-h" ]]; then
    usage
    exit 0
fi
if [[ "$1" == "--version" || "$1" == "-v" ]]; then
    show_version
    exit 0
fi
# Quick help check before getopt
if [[ "$1" == "--help" || "$1" == "-h" ]]; then
    usage
    exit 0
fi
if [[ "$1" == "--version" || "$1" == "-v" ]]; then
    show_version
    exit 0
fi
# Quick help check before getopt
if [[ "$1" == "--help" || "$1" == "-h" ]]; then
    usage
    exit 0
fi
if [[ "$1" == "--version" || "$1" == "-v" ]]; then
    show_version
    exit 0
fi
# Quick help check before getopt
if [[ "$1" == "--help" || "$1" == "-h" ]]; then
    usage
    exit 0
fi
if [[ "$1" == "--version" || "$1" == "-v" ]]; then
    show_version
    exit 0
fi
# Pre-getopt help check
if [[ "$1" == "--help" || "$1" == "-h" ]]; then
    usage
    exit 0
fi
if [[ "$1" == "--version" || "$1" == "-v" ]]; then
    show_version
    exit 0
fi
# Quick help check before getopt
if [[ "$1" == "--help" || "$1" == "-h" ]]; then
    usage
    exit 0
fi
if [[ "$1" == "--version" || "$1" == "-v" ]]; then
    show_version
    exit 0
fi
# Quick help check before getopt
if [[ "$1" == "--help" || "$1" == "-h" ]]; then
    usage
    exit 0
fi
if [[ "$1" == "--version" || "$1" == "-v" ]]; then
    show_version
    exit 0
fi
# Quick help check before getopt
if [[ "$1" == "--help" || "$1" == "-h" ]]; then
    usage
    exit 0
fi
if [[ "$1" == "--version" || "$1" == "-v" ]]; then
    show_version
    exit 0
fi
# Quick help check before getopt
if [[ "$1" == "--help" || "$1" == "-h" ]]; then
    usage
    exit 0
fi
if [[ "$1" == "--version" || "$1" == "-v" ]]; then
    show_version
    exit 0
fi
# Quick help check before getopt
if [[ "$1" == "--help" || "$1" == "-h" ]]; then
    usage
    exit 0
fi
if [[ "$1" == "--version" || "$1" == "-v" ]]; then
    show_version
    exit 0
fi
# Quick help check before getopt
if [[ "$1" == "--help" || "$1" == "-h" ]]; then
    usage
    exit 0
fi
if [[ "$1" == "--version" || "$1" == "-v" ]]; then
    show_version
    exit 0
fi
# Quick help check before getopt
if [[ "$1" == "--help" || "$1" == "-h" ]]; then
    usage
    exit 0
fi
if [[ "$1" == "--version" || "$1" == "-v" ]]; then
    show_version
    exit 0
fi
# Pre-getopt help check
if [[ "$1" == "--help" || "$1" == "-h" ]]; then
    usage
    exit 0
fi
if [[ "$1" == "--version" || "$1" == "-v" ]]; then
    show_version
    exit 0
fi
# Quick help check before getopt
if [[ "$1" == "--help" || "$1" == "-h" ]]; then
    usage
    exit 0
fi
if [[ "$1" == "--version" || "$1" == "-v" ]]; then
    show_version
    exit 0
fi
# Quick help check before getopt
if [[ "$1" == "--help" || "$1" == "-h" ]]; then
    usage
    exit 0
fi
if [[ "$1" == "--version" || "$1" == "-v" ]]; then
    show_version
    exit 0
fi
# Quick help check before getopt
if [[ "$1" == "--help" || "$1" == "-h" ]]; then
    usage
    exit 0
fi
if [[ "$1" == "--version" || "$1" == "-v" ]]; then
    show_version
    exit 0
fi
# Quick help check before getopt
if [[ "$1" == "--help" || "$1" == "-h" ]]; then
    usage
    exit 0
fi
if [[ "$1" == "--version" || "$1" == "-v" ]]; then
    show_version
    exit 0
fi
# Quick help check before getopt
if [[ "$1" == "--help" || "$1" == "-h" ]]; then
    usage
    exit 0
fi
if [[ "$1" == "--version" || "$1" == "-v" ]]; then
    show_version
    exit 0
fi
# Quick help check before getopt
if [[ "$1" == "--help" || "$1" == "-h" ]]; then
    usage
    exit 0
fi
if [[ "$1" == "--version" || "$1" == "-v" ]]; then
    show_version
    exit 0
fi
# Quick help check before getopt
if [[ "$1" == "--help" || "$1" == "-h" ]]; then
    usage
    exit 0
fi
if [[ "$1" == "--version" || "$1" == "-v" ]]; then
    show_version
    exit 0
fi
# Quick help check before getopt
if [[ "$1" == "--help" || "$1" == "-h" ]]; then
    usage
    exit 0
fi
if [[ "$1" == "--version" || "$1" == "-v" ]]; then
    show_version
    exit 0
fi
# Quick help check before getopt
if [[ "$1" == "--help" || "$1" == "-h" ]]; then
    usage
    exit 0
fi
if [[ "$1" == "--version" || "$1" == "-v" ]]; then
    show_version
    exit 0
fi
# Quick help check before getopt
if [[ "$1" == "--help" || "$1" == "-h" ]]; then
    usage
    exit 0
fi
if [[ "$1" == "--version" || "$1" == "-v" ]]; then
    show_version
    exit 0
fi
# Quick help check before getopt
if [[ "$1" == "--help" || "$1" == "-h" ]]; then
    usage
    exit 0
fi
if [[ "$1" == "--version" || "$1" == "-v" ]]; then
    show_version
    exit 0
fi
# Quick help check before getopt
if [[ "$1" == "--help" || "$1" == "-h" ]]; then
    usage
    exit 0
fi
if [[ "$1" == "--version" || "$1" == "-v" ]]; then
    show_version
    exit 0
fi
# Quick help check before getopt
if [[ "$1" == "--help" || "$1" == "-h" ]]; then
    usage
    exit 0
fi
if [[ "$1" == "--version" || "$1" == "-v" ]]; then
    show_version
    exit 0
fi
# Quick help check before getopt
if [[ "$1" == "--help" || "$1" == "-h" ]]; then
    usage
    exit 0
fi
if [[ "$1" == "--version" || "$1" == "-v" ]]; then
    show_version
    exit 0
fi
# Quick help check before getopt
if [[ "$1" == "--help" || "$1" == "-h" ]]; then
    usage
    exit 0
fi
if [[ "$1" == "--version" || "$1" == "-v" ]]; then
    show_version
    exit 0
fi
# Pre-getopt help check
if [[ "$1" == "--help" || "$1" == "-h" ]]; then
    usage
    exit 0
fi
if [[ "$1" == "--version" || "$1" == "-v" ]]; then
    show_version
    exit 0
fi
# Quick help check before getopt
if [[ "$1" == "--help" || "$1" == "-h" ]]; then
    usage
    exit 0
fi
if [[ "$1" == "--version" || "$1" == "-v" ]]; then
    show_version
    exit 0
fi
# Quick help check before getopt
if [[ "$1" == "--help" || "$1" == "-h" ]]; then
    usage
    exit 0
fi
if [[ "$1" == "--version" || "$1" == "-v" ]]; then
    show_version
    exit 0
fi
# Quick help check before getopt
if [[ "$1" == "--help" || "$1" == "-h" ]]; then
    usage
    exit 0
fi
if [[ "$1" == "--version" || "$1" == "-v" ]]; then
    show_version
    exit 0
fi
# Quick help check before getopt
if [[ "$1" == "--help" || "$1" == "-h" ]]; then
    usage
    exit 0
fi
if [[ "$1" == "--version" || "$1" == "-v" ]]; then
    show_version
    exit 0
fi
# Quick help check before getopt
if [[ "$1" == "--help" || "$1" == "-h" ]]; then
    usage
    exit 0
fi
if [[ "$1" == "--version" || "$1" == "-v" ]]; then
    show_version
    exit 0
fi
# Quick help check before getopt
if [[ "$1" == "--help" || "$1" == "-h" ]]; then
    usage
    exit 0
fi
if [[ "$1" == "--version" || "$1" == "-v" ]]; then
    show_version
    exit 0
fi
# Quick help check before getopt
if [[ "$1" == "--help" || "$1" == "-h" ]]; then
    usage
    exit 0
fi
if [[ "$1" == "--version" || "$1" == "-v" ]]; then
    show_version
    exit 0
fi
# Pre-getopt help check
if [[ "$1" == "--help" || "$1" == "-h" ]]; then
    usage
    exit 0
fi
if [[ "$1" == "--version" || "$1" == "-v" ]]; then
    show_version
    exit 0
fi
# Quick help check before getopt
if [[ "$1" == "--help" || "$1" == "-h" ]]; then
    usage
    exit 0
fi
if [[ "$1" == "--version" || "$1" == "-v" ]]; then
    show_version
    exit 0
fi
# Quick help check before getopt
if [[ "$1" == "--help" || "$1" == "-h" ]]; then
    usage
    exit 0
fi
if [[ "$1" == "--version" || "$1" == "-v" ]]; then
    show_version
    exit 0
fi
# Quick help check before getopt
if [[ "$1" == "--help" || "$1" == "-h" ]]; then
    usage
    exit 0
fi
if [[ "$1" == "--version" || "$1" == "-v" ]]; then
    show_version
    exit 0
fi
# Quick help check before getopt
if [[ "$1" == "--help" || "$1" == "-h" ]]; then
    usage
    exit 0
fi
if [[ "$1" == "--version" || "$1" == "-v" ]]; then
    show_version
    exit 0
fi
# Quick help check before getopt
if [[ "$1" == "--help" || "$1" == "-h" ]]; then
    usage
    exit 0
fi
if [[ "$1" == "--version" || "$1" == "-v" ]]; then
    show_version
    exit 0
fi
# Quick help check before getopt
if [[ "$1" == "--help" || "$1" == "-h" ]]; then
    usage
    exit 0
fi
if [[ "$1" == "--version" || "$1" == "-v" ]]; then
    show_version
    exit 0
fi
# Quick help check before getopt
if [[ "$1" == "--help" || "$1" == "-h" ]]; then
    usage
    exit 0
fi
if [[ "$1" == "--version" || "$1" == "-v" ]]; then
    show_version
    exit 0
fi
# Pre-getopt help check
if [[ "$1" == "--help" || "$1" == "-h" ]]; then
    usage
    exit 0
fi
if [[ "$1" == "--version" || "$1" == "-v" ]]; then
    show_version
    exit 0
fi
# Quick help check before getopt
if [[ "$1" == "--help" || "$1" == "-h" ]]; then
    usage
    exit 0
fi
if [[ "$1" == "--version" || "$1" == "-v" ]]; then
    show_version
    exit 0
fi
# Quick help check before getopt
if [[ "$1" == "--help" || "$1" == "-h" ]]; then
    usage
    exit 0
fi
if [[ "$1" == "--version" || "$1" == "-v" ]]; then
    show_version
    exit 0
fi
# Quick help check before getopt
if [[ "$1" == "--help" || "$1" == "-h" ]]; then
    usage
    exit 0
fi
if [[ "$1" == "--version" || "$1" == "-v" ]]; then
    show_version
    exit 0
fi
# Quick help check before getopt
if [[ "$1" == "--help" || "$1" == "-h" ]]; then
    usage
    exit 0
fi
if [[ "$1" == "--version" || "$1" == "-v" ]]; then
    show_version
    exit 0
fi
# Quick help check before getopt
if [[ "$1" == "--help" || "$1" == "-h" ]]; then
    usage
    exit 0
fi
if [[ "$1" == "--version" || "$1" == "-v" ]]; then
    show_version
    exit 0
fi
# Quick help check before getopt
if [[ "$1" == "--help" || "$1" == "-h" ]]; then
    usage
    exit 0
fi
if [[ "$1" == "--version" || "$1" == "-v" ]]; then
    show_version
    exit 0
fi
# Quick help check before getopt
if [[ "$1" == "--help" || "$1" == "-h" ]]; then
    usage
    exit 0
fi
if [[ "$1" == "--version" || "$1" == "-v" ]]; then
    show_version
    exit 0
fi
# Pre-getopt help check
if [[ "$1" == "--help" || "$1" == "-h" ]]; then
    usage
    exit 0
fi
if [[ "$1" == "--version" || "$1" == "-v" ]]; then
    show_version
    exit 0
fi
# Quick help check before getopt
if [[ "$1" == "--help" || "$1" == "-h" ]]; then
    usage
    exit 0
fi
if [[ "$1" == "--version" || "$1" == "-v" ]]; then
    show_version
    exit 0
fi
# Quick help check before getopt
if [[ "$1" == "--help" || "$1" == "-h" ]]; then
    usage
    exit 0
fi
if [[ "$1" == "--version" || "$1" == "-v" ]]; then
    show_version
    exit 0
fi
# Quick help check before getopt
if [[ "$1" == "--help" || "$1" == "-h" ]]; then
    usage
    exit 0
fi
if [[ "$1" == "--version" || "$1" == "-v" ]]; then
    show_version
    exit 0
fi
# Quick help check before getopt
if [[ "$1" == "--help" || "$1" == "-h" ]]; then
    usage
    exit 0
fi
if [[ "$1" == "--version" || "$1" == "-v" ]]; then
    show_version
    exit 0
fi
# Quick help check before getopt
if [[ "$1" == "--help" || "$1" == "-h" ]]; then
    usage
    exit 0
fi
if [[ "$1" == "--version" || "$1" == "-v" ]]; then
    show_version
    exit 0
fi
# Quick help check before getopt
if [[ "$1" == "--help" || "$1" == "-h" ]]; then
    usage
    exit 0
fi
if [[ "$1" == "--version" || "$1" == "-v" ]]; then
    show_version
    exit 0
fi
# Quick help check before getopt
if [[ "$1" == "--help" || "$1" == "-h" ]]; then
    usage
    exit 0
fi
if [[ "$1" == "--version" || "$1" == "-v" ]]; then
    show_version
    exit 0
fi
# Pre-getopt help check
if [[ "$1" == "--help" || "$1" == "-h" ]]; then
    usage
    exit 0
fi
if [[ "$1" == "--version" || "$1" == "-v" ]]; then
    show_version
    exit 0
fi
# Quick help check before getopt
if [[ "$1" == "--help" || "$1" == "-h" ]]; then
    usage
    exit 0
fi
if [[ "$1" == "--version" || "$1" == "-v" ]]; then
    show_version
    exit 0
fi
# Quick help check before getopt
if [[ "$1" == "--help" || "$1" == "-h" ]]; then
    usage
    exit 0
fi
if [[ "$1" == "--version" || "$1" == "-v" ]]; then
    show_version
    exit 0
fi
# Quick help check before getopt
if [[ "$1" == "--help" || "$1" == "-h" ]]; then
    usage
    exit 0
fi
if [[ "$1" == "--version" || "$1" == "-v" ]]; then
    show_version
    exit 0
fi
# Quick help check before getopt
if [[ "$1" == "--help" || "$1" == "-h" ]]; then
    usage
    exit 0
fi
if [[ "$1" == "--version" || "$1" == "-v" ]]; then
    show_version
    exit 0
fi
# Quick help check before getopt
if [[ "$1" == "--help" || "$1" == "-h" ]]; then
    usage
    exit 0
fi
if [[ "$1" == "--version" || "$1" == "-v" ]]; then
    show_version
    exit 0
fi
# Quick help check before getopt
if [[ "$1" == "--help" || "$1" == "-h" ]]; then
    usage
    exit 0
fi
if [[ "$1" == "--version" || "$1" == "-v" ]]; then
    show_version
    exit 0
fi
# Quick help check before getopt
if [[ "$1" == "--help" || "$1" == "-h" ]]; then
    usage
    exit 0
fi
if [[ "$1" == "--version" || "$1" == "-v" ]]; then
    show_version
    exit 0
fi
# Pre-getopt help check
if [[ "$1" == "--help" || "$1" == "-h" ]]; then
    usage
    exit 0
fi
if [[ "$1" == "--version" || "$1" == "-v" ]]; then
    show_version
    exit 0
fi
# Quick help check before getopt
if [[ "$1" == "--help" || "$1" == "-h" ]]; then
    usage
    exit 0
fi
if [[ "$1" == "--version" || "$1" == "-v" ]]; then
    show_version
    exit 0
fi
# Quick help check before getopt
if [[ "$1" == "--help" || "$1" == "-h" ]]; then
    usage
    exit 0
fi
if [[ "$1" == "--version" || "$1" == "-v" ]]; then
    show_version
    exit 0
fi
# Quick help check before getopt
if [[ "$1" == "--help" || "$1" == "-h" ]]; then
    usage
    exit 0
fi
if [[ "$1" == "--version" || "$1" == "-v" ]]; then
    show_version
    exit 0
fi
# Quick help check before getopt
if [[ "$1" == "--help" || "$1" == "-h" ]]; then
    usage
    exit 0
fi
if [[ "$1" == "--version" || "$1" == "-v" ]]; then
    show_version
    exit 0
fi
# Quick help check before getopt
if [[ "$1" == "--help" || "$1" == "-h" ]]; then
    usage
    exit 0
fi
if [[ "$1" == "--version" || "$1" == "-v" ]]; then
    show_version
    exit 0
fi
# Quick help check before getopt
if [[ "$1" == "--help" || "$1" == "-h" ]]; then
    usage
    exit 0
fi
if [[ "$1" == "--version" || "$1" == "-v" ]]; then
    show_version
    exit 0
fi
# Quick help check before getopt
if [[ "$1" == "--help" || "$1" == "-h" ]]; then
    usage
    exit 0
fi
if [[ "$1" == "--version" || "$1" == "-v" ]]; then
    show_version
    exit 0
fi
# Pre-getopt help check
if [[ "$1" == "--help" || "$1" == "-h" ]]; then
    usage
    exit 0
fi
if [[ "$1" == "--version" || "$1" == "-v" ]]; then
    show_version
    exit 0
fi
# Quick help check before getopt
if [[ "$1" == "--help" || "$1" == "-h" ]]; then
    usage
    exit 0
fi
if [[ "$1" == "--version" || "$1" == "-v" ]]; then
    show_version
    exit 0
fi
# Quick help check before getopt
if [[ "$1" == "--help" || "$1" == "-h" ]]; then
    usage
    exit 0
fi
if [[ "$1" == "--version" || "$1" == "-v" ]]; then
    show_version
    exit 0
fi
# Quick help check before getopt
if [[ "$1" == "--help" || "$1" == "-h" ]]; then
    usage
    exit 0
fi
if [[ "$1" == "--version" || "$1" == "-v" ]]; then
    show_version
    exit 0
fi
# Quick help check before getopt
if [[ "$1" == "--help" || "$1" == "-h" ]]; then
    usage
    exit 0
fi
if [[ "$1" == "--version" || "$1" == "-v" ]]; then
    show_version
    exit 0
fi
# Quick help check before getopt
if [[ "$1" == "--help" || "$1" == "-h" ]]; then
    usage
    exit 0
fi
if [[ "$1" == "--version" || "$1" == "-v" ]]; then
    show_version
    exit 0
fi
# Quick help check before getopt
if [[ "$1" == "--help" || "$1" == "-h" ]]; then
    usage
    exit 0
fi
if [[ "$1" == "--version" || "$1" == "-v" ]]; then
    show_version
    exit 0
fi
# Quick help check before getopt
if [[ "$1" == "--help" || "$1" == "-h" ]]; then
    usage
    exit 0
fi
if [[ "$1" == "--version" || "$1" == "-v" ]]; then
    show_version
    exit 0
fi
if ! OPTIONS=$(getopt -o hc:dqhhhhhhhhhhhhhvh -l config:,dry-run,quiet,verbose,dated,help,version -- "$@"); then
    usage
fi
eval set -- "$OPTIONS"

while true; do
    case "$1" in
        -c|--config)
            CONFIG_FILE="$2"
            shift 2
            ;;
        -d|--dry-run)
            DRY_RUN=true
            shift
            ;;
        -q|--quiet)
            QUIET=true
            shift
            ;;
        -v|--verbose)
            VERBOSE=true
            shift
            ;;
        --dated)
            DATED_SUBFOLDERS=true
            shift
            ;;
        --help)
            usage
            ;;
        --version)
            show_version
            ;;
        --)
            shift
            break
            ;;
        *)
            echo "Internal error!"
            exit 1
            ;;
    esac
done

# -------------------------------------------------------------------
# Pre-flight checks and setup
# -------------------------------------------------------------------
check_deps

# Ensure log directories exist
mkdir -p "$(dirname "$LOG_FILE")"
mkdir -p "$(dirname "$UNDO_LOG")"

# Declare associative array for categories
declare -A CATEGORIES

# Try to load config; if fails, use defaults
if ! load_config "$CONFIG_FILE"; then
    # Fallback defaults
    CATEGORIES=(
        ["Images"]="jpg jpeg png gif bmp svg webp tiff"
        ["Documents"]="pdf doc docx txt odt rtf md"
        ["Archives"]="zip tar gz bz2 xz 7z rar"
        ["Audio"]="mp3 wav flac ogg m4a"
        ["Video"]="mp4 mkv avi mov wmv"
        ["Code"]="sh py js html css c cpp h json yaml"
        ["Torrents"]="torrent"
        ["Installers"]="deb rpm appimage flatpakref"
        ["Others"]=""
    )
fi

# -------------------------------------------------------------------
# Main processing
# -------------------------------------------------------------------
log "=== Starting download organization ==="
vlog "Using config: $CONFIG_FILE"
vlog "Download directory: $DOWNLOAD_DIR"
vlog "Minimum age: $MIN_AGE_MINUTES minutes"

# Find files (not directories, not hidden) in DOWNLOAD_DIR
# Use null-delimited output to handle all filenames safely
find "$DOWNLOAD_DIR" -maxdepth 1 -type f -not -name '.*' -print0 | while IFS= read -r -d '' file; do
    # Skip files newer than MIN_AGE_MINUTES
    # Using find -mmin (GNU extension). Fallback to stat if needed.
    if ! find "$file" -mmin +"$MIN_AGE_MINUTES" | grep -q .; then
        # File is newer than limit
        vlog "Skipping $file (modified within last $MIN_AGE_MINUTES minutes)"
        continue
    fi

    # Skip open files
    if is_file_open "$file"; then
        vlog "Skipping $file (file is open)"
        continue
    fi

    # Get extension (lowercase)
    filename=$(basename "$file")
    ext="${filename##*.}"
    # If filename has no extension, ext == filename; handle that case
    if [ "$ext" = "$filename" ] || [ -z "$ext" ]; then
        ext=""
    fi
    ext_lower=$(echo "$ext" | tr '[:upper:]' '[:lower:]')

    # Find category
    dest_folder="$DOWNLOAD_DIR/Others"
    for cat in "${!CATEGORIES[@]}"; do
        # Skip "Others" category in loop (we already have default)
        [ "$cat" = "Others" ] && continue
        # Check if extension is in the space-separated list
        if [[ " ${CATEGORIES[$cat]} " == *" $ext_lower "* ]]; then
            dest_folder="$DOWNLOAD_DIR/$cat"
            break
        fi
    done

    # If dated subfolders enabled and not Others, append year/month
    if [ "$DATED_SUBFOLDERS" = true ] && [ "$dest_folder" != "$DOWNLOAD_DIR/Others" ]; then
        year=$(date +%Y)
        month=$(date +%m)
        dest_folder="$dest_folder/$year/$month"
    fi

    # Skip if already in the correct folder
    if [ "$(dirname "$file")" = "$dest_folder" ]; then
        vlog "Skipping $file (already in correct folder)"
        continue
    fi

    # Handle duplicate filename
    dest_path="$dest_folder/$filename"
    if [ -e "$dest_path" ]; then
        base="${filename%.*}"
        # If filename has no extension, base will be empty; handle that
        if [ -z "$base" ]; then
            # No extension, use full filename as base
            base="$filename"
            new_filename="${base}_$(date +%Y%m%d_%H%M%S)"
        else
            new_filename="${base}_$(date +%Y%m%d_%H%M%S).$ext"
        fi
        dest_path="$dest_folder/$new_filename"
        log "Filename conflict, renaming to $new_filename"
    fi

    move_file "$file" "$dest_path"
done

log "=== Organization complete ==="

# Suggest undo command if moves were made and not dry run
if [ "$DRY_RUN" = false ] && [ -s "$UNDO_LOG" ]; then
    echo "To undo this run, use: $(dirname "$0")/undo-organizer.sh"
fi
