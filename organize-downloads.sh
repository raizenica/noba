#!/bin/bash
# Download organizer – move files into categorized folders

# Configuration
DOWNLOAD_DIR="$HOME/Downloads"
LOG_FILE="$HOME/.local/share/download-organizer.log"
DRY_RUN=false          # set to true to only simulate moves
MIN_AGE_MINUTES=5      # skip files newer than this (minutes)

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

# Ensure log directory exists
mkdir -p "$(dirname "$LOG_FILE")"

log() {
    echo "$(date '+%Y-%m-%d %H:%M:%S') - $1" >> "$LOG_FILE"
    echo "$1"
}

# Function to check if file is open
is_file_open() {
    lsof "$1" >/dev/null 2>&1
}

# Dry-run or real move
move_file() {
    local src="$1"
    local dest="$2"
    if [ "$DRY_RUN" = true ]; then
        log "[DRY RUN] Would move: $src → $dest"
    else
        mkdir -p "$(dirname "$dest")"
        mv "$src" "$dest"
        log "Moved: $src → $dest"
    fi
}

# Main loop
log "=== Starting download organization ==="

find "$DOWNLOAD_DIR" -maxdepth 1 -type f -not -path '*/\.*' | while read -r file; do
    # Skip files newer than MIN_AGE_MINUTES
    if [ $(find "$file" -mmin -$MIN_AGE_MINUTES -print) ]; then
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
        if [[ " ${CATEGORIES[$cat]} " =~ " $ext_lower " ]]; then
            dest_folder="$DOWNLOAD_DIR/$cat"
            break
        fi
    done

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
