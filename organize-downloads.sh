#!/bin/bash
# Download organizer – move files into categorized folders with CLI, config, and dated subfolders

set -u
set -o pipefail

# Source central config if available
if [ -f "$HOME/.config/automation.conf" ]; then
    source "$HOME/.config/automation.conf"
fi

# Defaults (with central config overrides)
DOWNLOAD_DIR="${DOWNLOAD_DIR:-$HOME/Downloads}"
MIN_AGE_MINUTES="${MIN_AGE_MINUTES:-5}"
CONFIG_FILE="${ORGANIZER_CONFIG:-$HOME/.config/download-organizer.yaml}"
LOG_FILE="$HOME/.local/share/download-organizer.log"
UNDO_LOG="$HOME/.local/share/download-organizer-undo.log"
DRY_RUN=false
QUIET=false
DATED_SUBFOLDERS=false

# Function to show version
show_version() {
    if command -v git &>/dev/null && git rev-parse --git-dir &>/dev/null; then
        version=$(git describe --tags --always --dirty 2>/dev/null)
        echo "$(basename "$0") version $version"
    else
        echo "$(basename "$0") version unknown (not in git repo)"
    fi
    exit 0
}

# Usage function
usage() {
    cat <<EOF
Usage: $0 [options]

Options:
  -c, --config FILE   Use custom config file (default: $CONFIG_FILE)
  -d, --dry-run       Show what would be moved without actually moving
  -q, --quiet         Suppress normal output (only errors)
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

# Parse command-line arguments
OPTIONS=$(getopt -o c:dq -l config:,dry-run,quiet,dated,help,version -- "$@")
if [ $? -ne 0 ]; then
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

# Ensure log directories exist
mkdir -p "$(dirname "$LOG_FILE")"
mkdir -p "$(dirname "$UNDO_LOG")"

# Logging function
log() {
    local msg="$1"
    if [ "$QUIET" = false ]; then
        echo "$(date '+%Y-%m-%d %H:%M:%S') - $msg" >> "$LOG_FILE"
        echo "$msg"
    else
        echo "$(date '+%Y-%m-%d %H:%M:%S') - $msg" >> "$LOG_FILE"
    fi
}

# Undo logging
undo_log() {
    echo "$1|$2" >> "$UNDO_LOG"
}

# Check if file is open
is_file_open() {
    lsof "$1" >/dev/null 2>&1
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
        undo_log "$src" "$dest"
    fi
}

# Load configuration from YAML/JSON if available
declare -A CATEGORIES=()   # global associative array

load_config() {
    local config_file="$1"
    if [ ! -f "$config_file" ]; then
        return 1
    fi

    # Determine parser: yq for YAML, jq for JSON
    if command -v yq &>/dev/null && [[ "$config_file" == *.yaml || "$config_file" == *.yml ]]; then
        # Use yq to convert YAML to JSON, then jq to extract
        if command -v jq &>/dev/null; then
            local temp_config
            temp_config=$(mktemp)
            yq eval -o=json "$config_file" | jq -r 'to_entries | .[] | "CATEGORIES[\"" + .key + "\"]=\"" + (.value | join(" ")) + "\""' > "$temp_config"
            source "$temp_config"
            rm -f "$temp_config"
            return 0
        else
            log "Warning: jq not installed, cannot parse YAML config. Falling back to defaults."
            return 1
        fi
    elif command -v jq &>/dev/null && [[ "$config_file" == *.json ]]; then
        local temp_config
        temp_config=$(mktemp)
        jq -r 'to_entries | .[] | "CATEGORIES[\"" + .key + "\"]=\"" + (.value | join(" ")) + "\""' "$config_file" > "$temp_config"
        source "$temp_config"
        rm -f "$temp_config"
        return 0
    else
        log "Warning: No suitable parser found for config file. Install yq (YAML) or jq (JSON). Falling back to defaults."
        return 1
    fi
}

# Try to load config; if fails, use defaults
if ! load_config "$CONFIG_FILE"; then
    # Fallback defaults
    declare -A CATEGORIES=(
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

# Main loop
log "=== Starting download organization ==="

find "$DOWNLOAD_DIR" -maxdepth 1 -type f -not -path '*/\.*' | while read -r file; do
    # Skip files newer than MIN_AGE_MINUTES
    if [ "$(find "$file" -mmin -"$MIN_AGE_MINUTES" -print)" ]; then
        log "Skipping $file (modified within last $MIN_AGE_MINUTES minutes)"
        continue
    fi

    # Skip open files
    if is_file_open "$file"; then
        log "Skipping $file (file is open)"
        continue
    fi

    # Get extension (lowercase)
    ext="${file##*.}"
    ext_lower=$(echo "$ext" | tr '[:upper:]' '[:lower:]')
    filename=$(basename "$file")

    # Find category
    dest_folder="$DOWNLOAD_DIR/Others"
    for cat in "${!CATEGORIES[@]}"; do
        if [[ " ${CATEGORIES[$cat]} " == *" $ext_lower "* ]]; then
            dest_folder="$DOWNLOAD_DIR/$cat"
            break
        fi
    done

    # If dated subfolders enabled, append year/month
    if [ "$DATED_SUBFOLDERS" = true ] && [ "$dest_folder" != "$DOWNLOAD_DIR/Others" ]; then
        year=$(date +%Y)
        month=$(date +%m)
        dest_folder="$dest_folder/$year/$month"
    fi

    # Skip if already in the correct folder
    if [[ "$(dirname "$file")" == "$dest_folder" ]]; then
        log "Skipping $file (already in correct folder)"
        continue
    fi

    # Handle duplicate filename
    dest_path="$dest_folder/$filename"
    if [ -e "$dest_path" ]; then
        base="${filename%.*}"
        new_filename="${base}_$(date +%Y%m%d_%H%M%S).$ext"
        dest_path="$dest_folder/$new_filename"
        log "Filename conflict, renaming to $new_filename"
    fi

    move_file "$file" "$dest_path"
done

log "=== Organization complete ==="

# If undo log is non-empty, suggest undo command
if [ -s "$UNDO_LOG" ] && [ "$DRY_RUN" = false ]; then
    echo "To undo this run, use: ~/.local/bin/undo-organizer.sh"
fi
