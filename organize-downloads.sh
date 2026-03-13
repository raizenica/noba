#!/bin/bash
# organize-downloads.sh – Move files from Downloads into categorized folders
# Version: 2.2.0

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
VERBOSE=false

# Category definitions
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

# Build reverse mapping extension -> category for O(1) lookup
declare -A EXT_TO_CAT
for cat in "${!CATEGORIES[@]}"; do
    for ext in ${CATEGORIES[$cat]}; do
        EXT_TO_CAT[$ext]="$cat"
    done
done

# -------------------------------------------------------------------
# Load configuration
# -------------------------------------------------------------------
if command -v get_config &>/dev/null; then
    DOWNLOAD_DIR="$(get_config ".downloads.dir" "$DOWNLOAD_DIR")"
    MIN_AGE_MINUTES="$(get_config ".downloads.min_age_minutes" "$MIN_AGE_MINUTES")"

    # Safely derive log file if configured, otherwise use default
    config_log_dir="$(get_config ".logs.dir" "")"
    if [ -n "$config_log_dir" ]; then
        LOG_FILE="$config_log_dir/download-organizer.log"
    fi
fi

# -------------------------------------------------------------------
# Helper functions
# -------------------------------------------------------------------
show_version() {
    echo "organize-downloads.sh version 2.2.0 (noba-lib $NOBA_LIB_VERSION)"
    exit 0
}

show_help() {
    cat <<EOF
Usage: $0 [OPTIONS]

Organize files in Downloads folder into categorized subfolders.

Options:
  -d, --download-dir DIR  Target download directory (default: $DOWNLOAD_DIR)
  -a, --min-age MINUTES   Skip files modified within last MINUTES (default: $MIN_AGE_MINUTES)
  -n, --dry-run           Perform trial run with no changes
  -v, --verbose           Enable verbose output
  --help                  Show this help message
  --version               Show version information
EOF
    exit 0
}

is_file_open() {
    local file="$1"
    # fuser is significantly faster than lsof for single file checks
    if command -v fuser &>/dev/null; then
        fuser -s "$file"
        return $?
    elif command -v lsof &>/dev/null; then
        lsof "$file" >/dev/null 2>&1
        return $?
    else
        return 1 # Cannot check, assume closed
    fi
}

file_age_seconds() {
    local file="$1"
    local now mod_time
    # Use bash 5.0 EPOCHSECONDS if available, fallback to date
    now="${EPOCHSECONDS:-$(date +%s)}"
    mod_time=$(stat -c %Y "$file" 2>/dev/null || echo 0)
    echo $((now - mod_time))
}

move_file() {
    local src="$1"
    local dest="$2"
    if [ "$DRY_RUN" = true ]; then
        log_info "[DRY RUN] Would move: $src → $dest"
    else
        mkdir -p "$(dirname "$dest")"
        mv "$src" "$dest"
        log_info "Moved: $(basename "$src") → $(basename "$(dirname "$dest")")/"
    fi
}

# -------------------------------------------------------------------
# Parse command-line arguments
# -------------------------------------------------------------------
if ! PARSED_ARGS=$(getopt -o d:a:nv -l download-dir:,min-age:,dry-run,verbose,help,version -- "$@"); then
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
check_deps find mkdir dirname basename stat date

if ! [[ "$MIN_AGE_MINUTES" =~ ^[0-9]+$ ]]; then
    die "MIN_AGE_MINUTES must be a positive integer."
fi

if [ ! -d "$DOWNLOAD_DIR" ]; then
    die "Download directory $DOWNLOAD_DIR does not exist."
fi

# Prepare logging
mkdir -p "$(dirname "$LOG_FILE")"
exec > >(tee -a "$LOG_FILE") 2>&1

log_info "========== Download organizer started at $(date) =========="
log_info "Download dir: $DOWNLOAD_DIR"
log_info "Min age: $MIN_AGE_MINUTES minutes"
log_info "Dry run: $DRY_RUN"

# -------------------------------------------------------------------
# Main loop
# -------------------------------------------------------------------
MOVED_COUNT=0

# Process substitution ensures MOVED_COUNT persists after the loop
while IFS= read -r -d '' file; do
    log_debug "Processing: $file"

    age_seconds=$(file_age_seconds "$file")
    age_minutes=$((age_seconds / 60))
    if [ "$age_minutes" -lt "$MIN_AGE_MINUTES" ]; then
        log_debug "Skipping $file (modified $age_minutes minutes ago, threshold $MIN_AGE_MINUTES)"
        continue
    fi

    if is_file_open "$file"; then
        log_debug "Skipping $file (file is currently in use)"
        continue
    fi

    filename=$(basename "$file")
    ext="${filename##*.}"
    if [[ "$ext" == "$filename" ]]; then
        ext=""
    else
        ext="${ext,,}" # Native Bash 4+ lowercase
    fi

    category="${EXT_TO_CAT[$ext]:-Others}"
    dest_folder="$DOWNLOAD_DIR/$category"

    # Handle duplicate filename with $RANDOM to prevent rapid-execution race conditions
    dest_path="$dest_folder/$filename"
    if [ -e "$dest_path" ]; then
        base="${filename%.*}"
        [[ -z "$base" ]] && base="$filename" # Handle hidden files like .gitignore

        timestamp=$(date +%Y%m%d_%H%M%S)
        if [ -z "$ext" ]; then
            new_filename="${base}_${timestamp}_${RANDOM}"
        else
            new_filename="${base}_${timestamp}_${RANDOM}.$ext"
        fi
        dest_path="$dest_folder/$new_filename"
        log_debug "Filename conflict, renaming to $new_filename"
    fi

    move_file "$file" "$dest_path"
    ((MOVED_COUNT++))

done < <(find "$DOWNLOAD_DIR" -maxdepth 1 -type f -not -path '*/\.*' -print0)

log_info "========== Organization complete. Moved $MOVED_COUNT files. =========="
