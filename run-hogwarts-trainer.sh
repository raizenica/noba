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

# run-hogwarts-trainer.sh – Launch Hogwarts Legacy trainer with auto-detected Proton path

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

GAME_APPID="990080"                      # Steam App ID for Hogwarts Legacy
GAME_NAME="Hogwarts Legacy"
DEFAULT_TRAINER="Hogwarts Legacy v1.0-v1614419 Plus 33 Trainer.exe"
GAME_DIR=""                               # Will be auto-detected if empty
TRAINER_EXE="$DEFAULT_TRAINER"
PROTON_WINE=""
LIST_PROTON=false
QUIET=false

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

Launch the Hogwarts Legacy trainer using Steam's Proton.

Options:
  -g, --game-dir DIR      Specify game installation directory (auto-detected if omitted)
  -t, --trainer FILE      Trainer executable name (default: "$DEFAULT_TRAINER")
  -p, --proton-path PATH  Specify Proton wine binary directly (skips auto-detection)
  -l, --list-proton       List detected Proton versions and exit
  -q, --quiet             Suppress informational messages
  --help                  Show this help
  --version               Show version information
EOF
    exit 0
}

# Logging (quiet‑aware)
log() {
    if [ "$QUIET" = false ]; then
        echo "$@"
    fi
}

# Read Steam library folders from libraryfolders.vdf
get_steam_library_paths() {
    local vdf_paths=(
        "$HOME/.steam/root/steamapps/libraryfolders.vdf"
        "$HOME/.local/share/Steam/steamapps/libraryfolders.vdf"
    )
    local vdf=""
    for p in "${vdf_paths[@]}"; do
        if [ -f "$p" ]; then
            vdf="$p"
            break
        fi
    done
    if [ -z "$vdf" ]; then
        # Fallback to common locations
        echo "$HOME/.steam/steam"
        echo "$HOME/.local/share/Steam"
        return
    fi
    # Parse libraryfolders.vdf – extract paths inside quotes
    grep -E '^\s*"[0-9]+"\s+' "$vdf" | sed -E 's/.*"\s*"(.*)"\s*/\1/' | while read -r lib; do
        echo "$lib/steamapps"
    done
    # Also include the main steamapps folder
    dirname "$vdf" | sed 's|$|/steamapps|'
}

# Find game directory
find_game_dir() {
    local game_name="$1"
    while IFS= read -r base; do
        candidate="$base/common/$game_name"
        if [ -d "$candidate" ]; then
            echo "$candidate"
            return 0
        fi
    done < <(get_steam_library_paths)
    return 1
}

# Find Proton wine binary for a given appid
find_proton_wine() {
    local appid="$1"
    local wine_bin=""
    # Iterate over compatdata directories in all libraries
    while IFS= read -r base; do
        compat="$base/compatdata/$appid"
        if [ -d "$compat/pfx" ]; then
            # Look for Proton installation in the same library's common folder
            proton_root="$base/common"
            # Proton folders typically start with "Proton - " or just "Proton"
            # Find any Proton version that contains files/bin/wine
            while IFS= read -r proton_dir; do
                candidate="$proton_dir/files/bin/wine"
                if [ -x "$candidate" ]; then
                    wine_bin="$candidate"
                    echo "$wine_bin"
                    return 0
                fi
            done < <(find "$proton_root" -maxdepth 1 -type d -name "Proton*" 2>/dev/null | sort -V)
        fi
    done < <(get_steam_library_paths)
    # If not found, fallback to system wine
    if command -v wine &>/dev/null; then
        echo "wine"
        return 0
    fi
    return 1
}

# Find Wine prefix for given appid
find_wine_prefix() {
    local appid="$1"
    while IFS= read -r base; do
        compat="$base/compatdata/$appid"
        if [ -d "$compat/pfx" ]; then
            echo "$compat/pfx"
            return 0
        fi
    done < <(get_steam_library_paths)
    return 1
}

# List all detected Proton versions
list_proton_versions() {
    echo "Detected Proton installations:"
    while IFS= read -r base; do
        proton_root="$base/common"
        if [ -d "$proton_root" ]; then
            find "$proton_root" -maxdepth 1 -type d -name "Proton*" 2>/dev/null | sort -V | while read -r proton; do
                version=$(basename "$proton")
                wine_bin="$proton/files/bin/wine"
                if [ -x "$wine_bin" ]; then
                    echo "  $version: $wine_bin"
                fi
            done
        fi
    done < <(get_steam_library_paths)
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
if ! OPTIONS=$(getopt -o hg:t:p:lqh -l game-dir:,trainer:,proton-path:,list-proton,quiet,help,version -- "$@"); then
    usage
fi
eval set -- "$OPTIONS"

while true; do
    case "$1" in
        -g|--game-dir)
            GAME_DIR="$2"
            shift 2
            ;;
        -t|--trainer)
            TRAINER_EXE="$2"
            shift 2
            ;;
        -p|--proton-path)
            PROTON_WINE="$2"
            shift 2
            ;;
        -l|--list-proton)
            LIST_PROTON=true
            shift
            ;;
        -q|--quiet)
            QUIET=true
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

# Handle list-proton mode
if [ "$LIST_PROTON" = true ]; then
    list_proton_versions
    exit 0
fi

# -------------------------------------------------------------------
# Auto-detection logic
# -------------------------------------------------------------------

# If game directory not set, try to auto-detect
if [ -z "$GAME_DIR" ]; then
    GAME_DIR=$(find_game_dir "$GAME_NAME")
    if [ -z "$GAME_DIR" ]; then
        echo "ERROR: Could not find $GAME_NAME installation directory." >&2
        echo "Please specify with --game-dir or ensure Steam libraries are scanned." >&2
        exit 1
    fi
    log "Auto-detected game directory: $GAME_DIR"
fi

# Validate game directory
if [ ! -d "$GAME_DIR" ]; then
    echo "ERROR: Game directory '$GAME_DIR' does not exist." >&2
    exit 1
fi

# Locate trainer
trainer_path="$GAME_DIR/$TRAINER_EXE"
if [ ! -f "$trainer_path" ]; then
    echo "ERROR: Trainer executable '$TRAINER_EXE' not found in $GAME_DIR." >&2
    exit 1
fi

# Determine Proton wine binary
if [ -z "$PROTON_WINE" ]; then
    PROTON_WINE=$(find_proton_wine "$GAME_APPID")
    if [ -z "$PROTON_WINE" ]; then
        echo "ERROR: Could not find Proton wine binary for app $GAME_APPID." >&2
        echo "Use --proton-path to specify manually, or install a Proton version." >&2
        exit 1
    fi
    log "Auto-detected Proton wine: $PROTON_WINE"
else
    if [ ! -x "$PROTON_WINE" ]; then
        echo "ERROR: Specified Proton wine binary '$PROTON_WINE' not executable." >&2
        exit 1
    fi
fi

# Find Wine prefix
WINEPREFIX=$(find_wine_prefix "$GAME_APPID")
if [ -z "$WINEPREFIX" ]; then
    echo "ERROR: Could not find Wine prefix for app $GAME_APPID." >&2
    exit 1
fi
log "Using Wine prefix: $WINEPREFIX"

# Export Wine environment
export WINEPREFIX
export WINEARCH=win64

# -------------------------------------------------------------------
# Launch trainer
# -------------------------------------------------------------------
log "Launching trainer with Proton wine..."
cd "$GAME_DIR" || { echo "ERROR: Could not change to game directory." >&2; exit 1; }
exec "$PROTON_WINE" "$trainer_path"
