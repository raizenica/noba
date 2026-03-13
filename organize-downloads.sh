#!/bin/bash
# organize-downloads.sh – Move files from Downloads into categorized folders

set -euo pipefail

SCRIPT_DIR="$(cd "$(dirname "${BASH_SOURCE[0]}")" && pwd)"
# shellcheck source=/dev/null
source "$SCRIPT_DIR/noba-lib.sh"

# -------------------------------------------------------------------
# Default configuration
# -------------------------------------------------------------------
DOWNLOAD_DIR="${DOWNLOAD_DIR:-$HOME/Downloads}"
LOG_FILE="${LOG_FILE:-$HOME/.local/share/download-organizer.log}"
MIN_AGE_MINUTES=5
DRY_RUN=false

# Category definitions: folder name -> space-separated extensions
declare -A CATEGORIES=(
    ["Images"]="jpg jpeg png gif bmp svg webp tiff"
    ["Documents"]="pdf doc docx txt odt rtf md"
    ["Archives"]="zip tar gz bz2 xz 7z rar"
    ["Audio"]="mp3 wav flac ogg m4a"
    ["Video"]="mp4 mkv avi mov wmv"
    ["Code"]="sh py js html css c cpp h json yaml"
    ["Torrents"]="torrent"
    ["Installers"]="deb rpm appimage flatpakref"
    ["Others"]=""   # catch-all for unclassified
)

# -------------------------------------------------------------------
# Load user configuration (if any)
# -------------------------------------------------------------------
load_config
if [ "$CONFIG_LOADED" = true ]; then
    DOWNLOAD_DIR="$(get_config ".downloads.dir" "$DOWNLOAD_DIR")"
    MIN_AGE_MINUTES="$(get_config ".downloads.min_age_minutes" "$MIN_AGE_MINUTES")"
    LOG_FILE="$(get_config ".logs.dir" "$(dirname "$LOG_FILE")")/download-organizer.log"
    # Optionally load categories from config (advanced) – not implemented here
fi

# -------------------------------------------------------------------
# Helper functions
# -------------------------------------------------------------------
show_version() {
    echo "organize-downloads.sh version 1.0"
    exit 0
}

show_help() {
    cat <<EOF
Usage: $0 [OPTIONS]

Organize files in Downloads folder into categorized subfolders.

Options:
  -d, --download-dir DIR   Target download directory (default: $DOWNLOAD_DIR)
  -a, --min-age MINUTES    Skip files modified within last MINUTES (default: $MIN_AGE_MINUTES)
  -n, --dry-run            Perform trial run with no changes
  -v, --verbose            Enable verbose output
  --help                   Show this help message
  --version                Show version information
EOF
    exit 0
}

# Check if file is open (using lsof, fallback if not installed)
is_file_open() {
    if command -v lsof &>/dev/null; then
        lsof "$1" >/dev/null 2>&1
    else
        # No lsof, assume not open (best effort)
        log_debug "lsof not installed – skipping open file check for $1"
        return 1
    fi
}

# Get file age in seconds
file_age_seconds() {
    local file="$1"
    local now mod_time
    now=$(date +%s)
    mod_time=$(stat -c %Y "$file" 2>/dev/null || echo 0)
    echo $((now - mod_time))
}

# Move file (or simulate)
move_file() {
    local src="$1"
    local dest="$2"
    if [ "$DRY_RUN" = true ]; then
        log_info "[DRY RUN] Would move: $src → $dest"
    else
        mkdir -p "$(dirname "$dest")"
        mv "$src" "$dest"
        log_info "Moved: $src → $dest"
    fi
}

# -------------------------------------------------------------------
# Parse command-line arguments
# -------------------------------------------------------------------
PARSED_ARGS=$(getopt -o d:a:nv -l download-dir:,min-age:,dry-run,verbose,help,version -- "$@")
if ! some_command; then
    show_help
fi
eval set -- "$PARSED_ARGS"

while true; do
    case "$1" in
        -d|--download-dir) DOWNLOAD_DIR="$2"; shift 2 ;;
        -a|--min-age)      MIN_AGE_MINUTES="$2"; shift 2 ;;
        -n|--dry-run)      DRY_RUN=true; shift ;;
        -v|--verbose)      VERBOSE=true; shift ;;
        --help)            show_help ;;
        --version)         show_version ;;
        --)                shift; break ;;
        *)                 break ;;
    esac
done

# -------------------------------------------------------------------
# Pre-flight checks
# -------------------------------------------------------------------
check_deps find mkdir dirname basename stat date tr
if command -v lsof &>/dev/null; then
    log_debug "lsof available – will check open files."
else
    log_warn "lsof not installed – open file checks will be skipped."
fi

# Validate min age
if ! [[ "$MIN_AGE_MINUTES" =~ ^[0-9]+$ ]]; then
    log_error "MIN_AGE_MINUTES must be a positive integer."
    exit 1
fi

mkdir -p "$(dirname "$LOG_FILE")"
exec > >(tee -a "$LOG_FILE") 2>&1

log_info "========== Download organizer started at $(date) =========="
log_info "Download dir: $DOWNLOAD_DIR"
log_info "Min age: $MIN_AGE_MINUTES minutes"
log_info "Dry run: $DRY_RUN"

# -------------------------------------------------------------------
# Main loop
# -------------------------------------------------------------------
# Use find with null separator to handle spaces and special characters safely
find "$DOWNLOAD_DIR" -maxdepth 1 -type f -not -path '*/\.*' -print0 | while IFS= read -r -d '' file; do
    log_debug "Processing: $file"

    # Skip files newer than MIN_AGE_MINUTES
    age_seconds=$(file_age_seconds "$file")
    age_minutes=$((age_seconds / 60))
    if [ "$age_minutes" -lt "$MIN_AGE_MINUTES" ]; then
        log_debug "Skipping $file (modified $age_minutes minutes ago, threshold $MIN_AGE_MINUTES)"
        continue
    fi

    # Skip open files
    if is_file_open "$file"; then
        log_debug "Skipping $file (file is open)"
        continue
    fi

    # Get extension (lowercase)
    filename=$(basename "$file")
    ext="${filename##*.}"
    if [ "$ext" = "$filename" ]; then
        ext=""  # no extension
    else
        ext=$(echo "$ext" | tr '[:upper:]' '[:lower:]')
    fi

    # Find category
    dest_folder="$DOWNLOAD_DIR/Others"
    for cat in "${!CATEGORIES[@]}"; do
        if [[ " ${CATEGORIES[$cat]} " =~ " $ext " ]]; then
            dest_folder="$DOWNLOAD_DIR/$cat"
            break
        fi
    done

    # Skip if already in the correct folder
    current_dir=$(dirname "$file")
    if [ "$current_dir" = "$dest_folder" ]; then
        log_debug "Skipping $file (already in correct folder)"
        continue
    fi

    # Handle duplicate filename
    dest_path="$dest_folder/$filename"
    if [ -e "$dest_path" ]; then
        base="${filename%.*}"
        new_filename="${base}_$(date +%Y%m%d_%H%M%S).$ext"
        dest_path="$dest_folder/$new_filename"
        log_debug "Filename conflict, renaming to $new_filename"
    fi

    move_file "$file" "$dest_path"
done

log_info "========== Organization complete =========="
