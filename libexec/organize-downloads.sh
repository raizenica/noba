#!/bin/bash
# Copyright (c) 2024-2026 Kevin Van Nieuwenhove. All rights reserved.
# NOBA Command Center — Licensed under Apache 2.0.
# organize-downloads.sh – Move files from Downloads into categorized folders
# Version: 1.1.0

set -euo pipefail

# -------------------------------------------------------------------
# Configuration & Defaults
# -------------------------------------------------------------------
SCRIPT_DIR="$(cd "$(dirname "${BASH_SOURCE[0]}")" && pwd)"
# shellcheck source=/dev/null
source "$SCRIPT_DIR/lib/noba-lib.sh"

DOWNLOAD_DIR="${HOME}/Downloads"
LOG_DIR="${HOME}/.local/share"
UNDO_LOG="$LOG_DIR/download-organizer-undo.log"
DRY_RUN=false
MAX_DEPTH=1
EXCLUDE_PATTERNS=""
MOVED_COUNT=0

declare -A CATEGORY_COUNTS=()

# Extension Map (defaults)
declare -A EXT_MAP=(
    ["jpg"]="Images" ["jpeg"]="Images" ["png"]="Images" ["gif"]="Images" ["svg"]="Images" ["webp"]="Images"
    ["bmp"]="Images" ["tiff"]="Images" ["ico"]="Images" ["heic"]="Images" ["raw"]="Images"
    ["mp4"]="Video" ["mkv"]="Video" ["avi"]="Video" ["mov"]="Video" ["webm"]="Video" ["flv"]="Video"
    ["mp3"]="Audio" ["wav"]="Audio" ["flac"]="Audio" ["m4a"]="Audio" ["ogg"]="Audio" ["aac"]="Audio"
    ["pdf"]="Documents" ["doc"]="Documents" ["docx"]="Documents" ["txt"]="Documents" ["md"]="Documents"
    ["xls"]="Documents" ["xlsx"]="Documents" ["ppt"]="Documents" ["pptx"]="Documents" ["odt"]="Documents"
    ["csv"]="Documents" ["rtf"]="Documents" ["epub"]="Documents"
    ["zip"]="Archives" ["tar"]="Archives" ["gz"]="Archives" ["rar"]="Archives" ["7z"]="Archives"
    ["bz2"]="Archives" ["xz"]="Archives" ["zst"]="Archives" ["tgz"]="Archives"
    ["iso"]="DiskImages" ["img"]="DiskImages" ["qcow2"]="DiskImages" ["vmdk"]="DiskImages"
    ["exe"]="Executables" ["AppImage"]="Executables" ["rpm"]="Executables" ["deb"]="Executables" ["msi"]="Executables" ["flatpak"]="Executables"
    ["py"]="Code" ["js"]="Code" ["ts"]="Code" ["sh"]="Code" ["c"]="Code" ["cpp"]="Code" ["java"]="Code"
    ["go"]="Code" ["rs"]="Code" ["html"]="Code" ["css"]="Code" ["json"]="Code" ["yaml"]="Code" ["yml"]="Code"
    ["xml"]="Code" ["sql"]="Code" ["toml"]="Code"
    ["torrent"]="Torrents"
    ["ttf"]="Fonts" ["otf"]="Fonts" ["woff"]="Fonts" ["woff2"]="Fonts"
)

# -------------------------------------------------------------------
# Load user configuration
# -------------------------------------------------------------------
if command -v get_config &>/dev/null; then
    DOWNLOAD_DIR="$(get_config ".downloads.dir" "$DOWNLOAD_DIR")"
    DOWNLOAD_DIR="${DOWNLOAD_DIR/#\~/$HOME}"

    config_log_dir="$(get_config ".logs.dir" "$LOG_DIR")"
    LOG_DIR="${config_log_dir/#\~/$HOME}"
    UNDO_LOG="$LOG_DIR/download-organizer-undo.log"

    _cfg_depth="$(get_config ".downloads.organize.max_depth" "")"
    [[ -n "$_cfg_depth" ]] && MAX_DEPTH="$_cfg_depth"

    _cfg_exclude="$(get_config ".downloads.organize.exclude" "")"
    [[ -n "$_cfg_exclude" ]] && EXCLUDE_PATTERNS="$_cfg_exclude"

    # Load custom extension rules (ext:Category pairs from config array)
    _custom_rules=$(get_config_array ".downloads.organize.custom_rules" 2>/dev/null || true)
    if [[ -n "$_custom_rules" ]]; then
        while IFS= read -r rule; do
            [[ -z "$rule" || "$rule" != *:* ]] && continue
            _ext="${rule%%:*}"
            _cat="${rule#*:}"
            _ext=$(echo "$_ext" | tr '[:upper:]' '[:lower:]' | xargs)
            _cat=$(echo "$_cat" | xargs)
            [[ -n "$_ext" && -n "$_cat" ]] && EXT_MAP["$_ext"]="$_cat"
        done <<< "$_custom_rules"
    fi
fi

# -------------------------------------------------------------------
# Argument Parsing
# -------------------------------------------------------------------
while [[ $# -gt 0 ]]; do
    case "$1" in
        --dry-run)    DRY_RUN=true; shift ;;
        --max-depth)  MAX_DEPTH="$2"; shift 2 ;;
        --exclude)    EXCLUDE_PATTERNS="$2"; shift 2 ;;
        -v|--verbose) export VERBOSE=true; shift ;;
        --help)
            echo "Usage: organize-downloads.sh [OPTIONS]"
            echo "  --dry-run          Show what would happen without moving files"
            echo "  --max-depth N      Directory depth to scan (default: 1)"
            echo "  --exclude PATS     Comma-separated exclude patterns (e.g. '*.part,*.crdownload')"
            exit 0 ;;
        *) log_error "Unknown flag: $1"; exit 1 ;;
    esac
done

if [[ ! -d "$DOWNLOAD_DIR" ]]; then
    log_error "Download directory does not exist: $DOWNLOAD_DIR"
    exit 1
fi

# -------------------------------------------------------------------
# Execution
# -------------------------------------------------------------------
log_info "Organizing downloads in: $DOWNLOAD_DIR"
log_info "  Max depth: $MAX_DEPTH"
[[ -n "$EXCLUDE_PATTERNS" ]] && log_info "  Exclude: $EXCLUDE_PATTERNS"
[[ "$DRY_RUN" == true ]] && log_info "[DRY RUN MODE] No files will actually be moved."

# Build find exclusions
FIND_EXCLUDES=()
if [[ -n "$EXCLUDE_PATTERNS" ]]; then
    IFS=',' read -ra _pats <<< "$EXCLUDE_PATTERNS"
    for pat in "${_pats[@]}"; do
        pat=$(echo "$pat" | xargs)  # trim whitespace
        [[ -n "$pat" ]] && FIND_EXCLUDES+=(-not -name "$pat")
    done
fi

# Build list of known category folders to skip scanning into
declare -A _seen_cats=()
for _v in "${EXT_MAP[@]}"; do _seen_cats["$_v"]=1; done
_seen_cats["Other"]=1
FIND_PRUNE=()
for _cat in "${!_seen_cats[@]}"; do
    FIND_PRUNE+=(-not -path "$DOWNLOAD_DIR/$_cat/*")
done

mkdir -p "$LOG_DIR"
_UNDO_TMP="${UNDO_LOG}.tmp"
> "$_UNDO_TMP"

while IFS= read -r -d '' file; do
    filename=$(basename "$file")

    # Skip directories
    [[ -d "$file" ]] && continue

    # Get extension
    ext="${filename##*.}"
    ext=$(echo "$ext" | tr '[:upper:]' '[:lower:]')

    # Find category, default to 'Other'
    category="${EXT_MAP[$ext]:-Other}"

    dest_folder="$DOWNLOAD_DIR/$category"

    # Skip if already in correct folder
    if [[ "$(dirname "$file")" == "$dest_folder" ]]; then
        continue
    fi

    if [[ "$DRY_RUN" == true ]]; then
        log_info "[DRY RUN] Would move: $filename -> $category/"
    else
        mkdir -p "$dest_folder"

        # Handle collisions securely
        dest_file="$dest_folder/$filename"
        if [[ -e "$dest_file" ]]; then
            dest_file="$dest_folder/${filename%.*}_$(date +%s).${ext}"
        fi

        if mv "$file" "$dest_file"; then
            echo "${dest_file}|${file}" >> "$_UNDO_TMP"
            log_verbose "Moved: $filename -> $category/"
        else
            log_error "Failed to move: $filename"
        fi
    fi

    CATEGORY_COUNTS["$category"]=$(( ${CATEGORY_COUNTS["$category"]:-0} + 1 ))
    (( MOVED_COUNT++ )) || true

done < <(find "$DOWNLOAD_DIR" -maxdepth "$MAX_DEPTH" -type f -not -name '.*' "${FIND_EXCLUDES[@]}" "${FIND_PRUNE[@]}" -print0 2>/dev/null)

# -------------------------------------------------------------------
# Wrap up
# -------------------------------------------------------------------
if [[ "$DRY_RUN" != true && -s "$_UNDO_TMP" ]]; then
    cat "$_UNDO_TMP" >> "$UNDO_LOG"
fi
rm -f "$_UNDO_TMP"

log_info "=========================================="
log_info "  Finished Organizing"
log_info "  Total moved: $MOVED_COUNT file(s)"
for cat in "${!CATEGORY_COUNTS[@]}"; do
    log_info "    - $cat: ${CATEGORY_COUNTS[$cat]}"
done
log_info "=========================================="
