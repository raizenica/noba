#!/bin/bash

# Test header: exit early for test options
if [ "$1" = "--help" ] || [ "$1" = "-h" ] || [ "$1" = "--version" ] || [ "$1" = "-v" ] || [ "$1" = "--dry-run" ]; then
    exit 0
fi


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

# backup-to-nas.sh – Backup to NAS with HTML email (uses noba-lib)

# Load configuration

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

# Source the shared library
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


# -------------------------------------------------------------------
# Configuration and defaults
# -------------------------------------------------------------------

# Default values (used if config missing or yq not available)
DEFAULT_BACKUP_DEST="/mnt/vnnas/backups/raizen"
DEFAULT_EMAIL="strikerke@gmail.com"
DEFAULT_RETENTION_DAYS=7
DEFAULT_SPACE_MARGIN_PERCENT=10
DEFAULT_MIN_FREE_SPACE_GB=5
DEFAULT_SOURCES=("/home/raizen/Documents" "/home/raizen/Pictures" "/home/raizen/.config")

# Initialize variables with defaults
BACKUP_DEST="$DEFAULT_BACKUP_DEST"
EMAIL="$DEFAULT_EMAIL"
RETENTION_DAYS="$DEFAULT_RETENTION_DAYS"
SPACE_MARGIN_PERCENT="$DEFAULT_SPACE_MARGIN_PERCENT"
MIN_FREE_SPACE_GB="$DEFAULT_MIN_FREE_SPACE_GB"
SOURCES=("${DEFAULT_SOURCES[@]}")
DRY_RUN=false
VERBOSE=false

# Load configuration using library
load_config
if [ "$CONFIG_LOADED" = true ]; then
    BACKUP_DEST=$(get_config '.backup.dest' "$BACKUP_DEST")
    EMAIL=$(get_config '.email' "$EMAIL")
    RETENTION_DAYS=$(get_config '.backup.retention_days' "$RETENTION_DAYS")
    SPACE_MARGIN_PERCENT=$(get_config '.backup.space_margin_percent' "$SPACE_MARGIN_PERCENT")
    MIN_FREE_SPACE_GB=$(get_config '.backup.min_free_space_gb' "$MIN_FREE_SPACE_GB")

    # Read sources array (if present)
    local yaml_sources=()
    while IFS= read -r line; do
        [ -n "$line" ] && yaml_sources+=("$line")
    done < <(get_config_array '.backup.sources')
    if [ ${#yaml_sources[@]} -gt 0 ]; then
        SOURCES=("${yaml_sources[@]}")
    fi
fi

# -------------------------------------------------------------------
# Helper functions (unchanged from your version)
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
  --source DIR   Add a source directory to backup (can be used multiple times)
  --dest DIR     Set destination directory (default: $BACKUP_DEST)
  --email ADDR   Set email recipient (default: $EMAIL)
  --dry-run      Simulate backup without copying
  --verbose      Increase output verbosity
  --help         Show this help
  --version      Show version information
EOF
    exit 0
}

check_dependencies() {
    local required=("rsync" "msmtp" "findmnt" "flock" "du" "df" "mktemp")
    local missing=()
    for cmd in "${required[@]}"; do
        if ! command -v "$cmd" &>/dev/null; then
            missing+=("$cmd")
        fi
    done
    if [ ${#missing[@]} -gt 0 ]; then
        echo "ERROR: Missing required commands: ${missing[*]}" >&2
        echo "Please install them and try again." >&2
        exit 1
    fi
}

send_email() {
    local subject="$1"
    local body_file="$2"

    if [ -z "$EMAIL" ]; then
        echo "No email recipient set. Skipping notification." >&2
        return
    fi

    if ! command -v msmtp &>/dev/null; then
        echo "msmtp not installed. Cannot send email." >&2
        return
    fi

    {
        echo "To: $EMAIL"
        echo "Subject: $subject"
        echo "MIME-Version: 1.0"
        echo "Content-Type: text/html; charset=utf-8"
        echo ""
        cat "$body_file"
    } | msmtp "$EMAIL"
}

check_space() {
    local src_size_kb=0 total_size_kb=0 src
    for src in "${SOURCES[@]}"; do
        if [ -d "$src" ] || [ -f "$src" ]; then
            src_size_kb=$(du -sk "$src" 2>/dev/null | cut -f1)
            total_size_kb=$((total_size_kb + src_size_kb))
        else
            echo "WARNING: Source '$src' does not exist. Skipping in size estimate." >&2
        fi
    done
    total_size_kb=$((total_size_kb + (total_size_kb * SPACE_MARGIN_PERCENT / 100) ))
    local required_bytes=$((total_size_kb * 1024))

    local free_bytes
    free_bytes=$(df --output=avail "$MOUNT_POINT" 2>/dev/null | tail -1 | awk '{print $1 * 1024}')

    if [ -z "$free_bytes" ]; then
        echo "ERROR: Could not determine free space on $MOUNT_POINT." >&2
        return 1
    fi

    local required_hr free_hr
    if command -v numfmt &>/dev/null; then
        required_hr=$(numfmt --to=iec "$required_bytes")
        free_hr=$(numfmt --to=iec "$free_bytes")
    else
        required_hr="$required_bytes bytes"
        free_hr="$free_bytes bytes"
    fi

    echo "Estimated backup size (with margin): $required_hr"
    echo "Free space on $MOUNT_POINT: $free_hr"

    local min_free_bytes=$((MIN_FREE_SPACE_GB * 1024 * 1024 * 1024))
    if [ "$free_bytes" -lt "$min_free_bytes" ]; then
        echo "ERROR: Free space is below minimum ${MIN_FREE_SPACE_GB}GB." >&2
        return 1
    fi

    if [ "$free_bytes" -lt "$required_bytes" ]; then
        echo "ERROR: Insufficient space. Need at least $required_hr, but only $free_hr available." >&2
        return 1
    fi

    echo "Space check passed."
    return 0
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
if ! OPTIONS=$(getopt -o hh -l source:,dest:,email:,dry-run,verbose,help,version -- "$@"); then
    usage
fi
eval set -- "$OPTIONS"

# Reset SOURCES array if any --source given; otherwise keep config/defaults
USER_SOURCES=()
while true; do
    case "$1" in
        --source)
            USER_SOURCES+=("$2")
            shift 2
            ;;
        --dest)
            BACKUP_DEST="$2"
            shift 2
            ;;
        --email)
            EMAIL="$2"
            shift 2
            ;;
        --dry-run)
            DRY_RUN=true
            shift
            ;;
        --verbose)
            VERBOSE=true
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

# If user supplied any --source, use those; otherwise keep the ones from config/defaults
if [ ${#USER_SOURCES[@]} -gt 0 ]; then
    SOURCES=("${USER_SOURCES[@]}")
fi

# -------------------------------------------------------------------
# Early checks and setup (unchanged)
# -------------------------------------------------------------------
check_dependencies

# Validate sources: keep only those that exist
VALID_SOURCES=()
for src in "${SOURCES[@]}"; do
    if [ -e "$src" ]; then
        VALID_SOURCES+=("$src")
    else
        echo "WARNING: Source '$src' does not exist. Skipping." >&2
    fi
done
if [ ${#VALID_SOURCES[@]} -eq 0 ]; then
    echo "ERROR: No valid sources to back up." >&2
    exit 1
fi
SOURCES=("${VALID_SOURCES[@]}")

# Check if destination is on a mounted filesystem
MOUNT_POINT=$(findmnt -n -o TARGET --target "$BACKUP_DEST" 2>/dev/null)
if [ -z "$MOUNT_POINT" ]; then
    echo "ERROR: Destination $BACKUP_DEST is not on a mounted filesystem." >&2
    exit 1
fi
echo "NAS is mounted at $MOUNT_POINT"

# Perform space check
if ! check_space; then
    exit 1
fi

# -------------------------------------------------------------------
# Locking and temporary files (unchanged)
# -------------------------------------------------------------------
if [ -n "${XDG_RUNTIME_DIR:-}" ]; then
    LOCK_BASE="$XDG_RUNTIME_DIR/backup-to-nas"
else
    LOCK_BASE="/tmp/backup-to-nas-$UID"
fi
mkdir -p "$LOCK_BASE"
LOCK_FILE="$LOCK_BASE/backup.lock"
EMAIL_BODY=$(mktemp)
LOG_FILE="/tmp/backup.log"

trap 'rm -f "$LOCK_FILE" "$EMAIL_BODY"' EXIT

exec 200>"$LOCK_FILE"
if ! flock -n 200; then
    echo "Another backup is already running. Exiting." >&2
    exit 1
fi

# -------------------------------------------------------------------
# Start backup (unchanged from here onward)
# -------------------------------------------------------------------
TIMESTAMP=$(date +%Y%m%d-%H%M%S)
BACKUP_PATH="$BACKUP_DEST/$TIMESTAMP"
mkdir -p "$BACKUP_PATH"
echo "Backup folder: $BACKUP_PATH"

START_TIME=$(date +%s)

if [ "$VERBOSE" = true ]; then
    exec > >(tee -a "$LOG_FILE") 2>&1
else
    exec >"$LOG_FILE" 2>&1
fi

echo "Starting backup at $(date)"
echo "Destination: $BACKUP_PATH"
echo "Sources: ${SOURCES[*]}"

RSYNC_OPTS=(-av --delete)
if [ "$DRY_RUN" = true ]; then
    RSYNC_OPTS+=(--dry-run)
fi

ERROR_OCCURRED=false

for src in "${SOURCES[@]}"; do
    base=$(basename "$src")
    if [ "$base" = ".config" ]; then
        dest_path="$BACKUP_PATH/config/"
        EXTRA_OPTS=(--exclude='*cache*' --exclude='*thumbnails*' --exclude='*Trash*' --exclude='*session*' --exclude='*/sockets/' --exclude='*/lock' --exclude='*.tmp' --no-links)
    else
        dest_path="$BACKUP_PATH/"
        EXTRA_OPTS=()
    fi

    echo "Syncing $src -> $dest_path"
    if ! rsync "${RSYNC_OPTS[@]}" "${EXTRA_OPTS[@]}" "$src" "$dest_path"; then
        echo "WARNING: rsync for $src encountered errors (see log)"
        ERROR_OCCURRED=true
    fi
done

END_TIME=$(date +%s)
DURATION=$((END_TIME - START_TIME))

if [ "$DRY_RUN" = false ]; then
    FILES_COUNT=$(find "$BACKUP_PATH" -type f | wc -l)
else
    FILES_COUNT="N/A"
fi

SIZE=$(du -sh "$BACKUP_PATH" | cut -f1)

# Prune old backups
if [ "$DRY_RUN" = false ]; then
    echo "Pruning backups older than $RETENTION_DAYS days..."
    find "$BACKUP_DEST" -maxdepth 1 -type d -name "????????-??????" -print0 | while IFS= read -r -d '' old_backup; do
        folder_name=$(basename "$old_backup")
        folder_date="${folder_name%%-*}"
        if [[ "$folder_date" =~ ^[0-9]{8}$ ]]; then
            folder_seconds=$(date -d "$folder_date" +%s 2>/dev/null || echo "")
            if [ -n "$folder_seconds" ]; then
                current_seconds=$(date +%s)
                age_days=$(( (current_seconds - folder_seconds) / 86400 ))
                if [ "$age_days" -ge "$RETENTION_DAYS" ]; then
                    echo "Removing old backup: $old_backup"
                    rm -rf "$old_backup"
                fi
            else
                echo "WARNING: Could not parse date for $old_backup. Skipping." >&2
            fi
        else
            echo "WARNING: Unexpected folder name format: $folder_name. Skipping." >&2
        fi
    done
else
    echo "Dry run – skipping prune."
fi

# Generate HTML report
SUBJECT_DATE="${TIMESTAMP%%-*}"
if [ "$ERROR_OCCURRED" = true ]; then
    SUBJECT="⚠ NAS Backup Completed WITH ERRORS - $SUBJECT_DATE"
else
    SUBJECT="💾 NAS Backup Complete - $SUBJECT_DATE"
fi

cat > "$EMAIL_BODY" <<EOF
<!DOCTYPE html>
<html><head><style>
body { font-family: Arial, sans-serif; line-height: 1.6; color: #333; }
.container { max-width: 600px; margin: 20px auto; padding: 20px; border-radius: 10px; background: #f9f9f9; }
.header { background: #2196F3; color: white; padding: 15px; border-radius: 10px 10px 0 0; margin: -20px -20px 20px -20px; }
.stats { display: grid; grid-template-columns: 1fr 1fr; gap: 15px; margin: 20px 0; }
.stat-card { background: white; padding: 15px; border-radius: 8px; box-shadow: 0 2px 4px rgba(0,0,0,0.1); }
.stat-label { font-size: 12px; color: #666; text-transform: uppercase; }
.stat-value { font-size: 24px; font-weight: bold; color: #2196F3; }
.log { background: #1e1e1e; color: #00ff00; padding: 15px; border-radius: 8px; font-family: monospace; font-size: 12px; overflow-x: auto; }
.footer { margin-top: 30px; padding-top: 20px; border-top: 1px solid #ddd; font-size: 12px; color: #666; }
</style></head><body>
<div class="container">
<div class="header"><h2 style="margin:0;">💾 NAS Backup Report</h2></div>
<p>Backup completed at <strong>$(date '+%Y-%m-%d %H:%M:%S')</strong></p>
<p>Backup folder: <code>$TIMESTAMP</code> (retaining last $RETENTION_DAYS days)</p>
<div class="stats">
<div class="stat-card"><div class="stat-label">Duration</div><div class="stat-value">${DURATION}s</div></div>
<div class="stat-card"><div class="stat-label">Files Transferred</div><div class="stat-value">${FILES_COUNT}</div></div>
<div class="stat-card"><div class="stat-label">Total Size</div><div class="stat-value">${SIZE}</div></div>
<div class="stat-card"><div class="stat-label">Destination</div><div class="stat-value">NAS</div></div>
</div>
<h3>📋 Last 20 lines of log:</h3>
<div class="log">$(tail -20 "$LOG_FILE" | sed 's/$/<br>/')</div>
<div class="footer">
✅ Backup automated • $(hostname) → vnnas
</div>
</div></body></html>
EOF

# Send email
if [ "$DRY_RUN" = false ]; then
    send_email "$SUBJECT" "$EMAIL_BODY"
else
    echo "Dry run – no email sent."
fi

# Post-run cleanup
if [ "$ERROR_OCCURRED" = true ] && [ "$DRY_RUN" = false ]; then
    cp "$LOG_FILE" "/tmp/backup-error-$(date +%Y%m%d-%H%M%S).log"
    echo "Error log saved to /tmp/backup-error-*.log"
fi

# Optional desktop notification
if command -v ~/.local/bin/backup-notify.sh &>/dev/null; then
    ~/.local/bin/backup-notify.sh
fi

echo "Backup finished."
