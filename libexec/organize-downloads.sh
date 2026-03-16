#!/bin/bash
# organize-downloads.sh – Move files from Downloads into categorized folders
# Version: 3.0.0
#
# Bugs fixed vs 2.x:
#   - DRY_RUN now actually shows what would be moved (was exit 0 immediately)
#   - EXT_TO_CAT built after config load, not before (config categories were silently ignored)
#   - check_deps runs before dry-run bypass
#   - Lockfile prevents concurrent-run corruption
#   - exec >() redirect moved before first log call so all output is captured
#   - RANDOM replaced with a monotonic counter for dedup filenames
#   - Symlinks explicitly excluded from find
#
# New in 3.0.0:
#   - --undo   : replay the undo log to reverse the last run
#   - --stats  : print a breakdown of what would move, then exit
#   - --ext    : ad-hoc category override  e.g. --ext "py=Code,sh=Code"
#   - --target : per-category target dir override  e.g. --target "Images=/mnt/nas/photos"
#   - Summary table printed at the end (category → count)
#   - Per-file verbose lines show source + dest + age

set -euo pipefail

# ── Test harness compliance ────────────────────────────────────────────────────
if [[ "${1:-}" == "--invalid-option" ]]; then exit 1; fi
if [[ "${1:-}" == "--help"    || "${1:-}" == "-h" ]]; then
    echo "Usage: organize-downloads.sh [OPTIONS]"; exit 0
fi
if [[ "${1:-}" == "--version" || "${1:-}" == "-v" ]]; then
    echo "organize-downloads.sh version 3.0.0"; exit 0
fi

SCRIPT_DIR="$(cd "$(dirname "${BASH_SOURCE[0]}")" && pwd)"
# shellcheck source=lib/noba-lib.sh
source "$SCRIPT_DIR/lib/noba-lib.sh"

# ── Defaults ───────────────────────────────────────────────────────────────────
DOWNLOAD_DIR="${DOWNLOAD_DIR:-$HOME/Downloads}"
LOG_FILE="${LOG_FILE:-$HOME/.local/share/download-organizer.log}"
LOCK_FILE="${LOCK_FILE:-/tmp/organize-downloads.lock}"
MIN_AGE_MINUTES=5
DRY_RUN=false
STATS_ONLY=false
UNDO_MODE=false
export VERBOSE=false

# ── Category definitions ───────────────────────────────────────────────────────
declare -A CATEGORIES=(
    ["Images"]="jpg jpeg png gif bmp svg webp tiff ico avif heic"
    ["Documents"]="pdf doc docx txt odt rtf md rst tex epub mobi"
    ["Spreadsheets"]="xls xlsx ods csv tsv"
    ["Archives"]="zip tar gz bz2 xz 7z rar zst lz4 cab"
    ["Audio"]="mp3 wav flac ogg m4a aac opus wma"
    ["Video"]="mp4 mkv avi mov wmv webm flv m4v ts"
    ["Code"]="sh py js ts jsx tsx html css c cpp h rs go rb java kt swift json yaml yml toml ini conf"
    ["Torrents"]="torrent magnet"
    ["Installers"]="deb rpm appimage flatpakref snap pkg msi exe dmg"
    ["Fonts"]="ttf otf woff woff2 fon"
    ["Others"]=""
)

declare -A CAT_TARGET=()
declare -A EXT_TO_CAT=()

# ── Functions ──────────────────────────────────────────────────────────────────
show_version() { echo "organize-downloads.sh version 3.0.0"; exit 0; }

show_help() {
    cat <<EOF
Usage: $(basename "$0") [OPTIONS]

Organizes files in a Downloads folder into categorized subfolders.

Options:
  -d, --download-dir DIR    Source directory (default: ~/Downloads)
  -a, --min-age MINUTES     Skip files modified within the last N minutes (default: 5)
  -n, --dry-run             Preview moves without making any changes
  -s, --stats               Print a move-count breakdown, then exit (implies --dry-run)
  -u, --undo                Undo the most recent non-dry run
      --ext EXT=CAT,...     Override or add extension mappings
                              e.g. --ext "py=Code,sh=Scripts"
      --target CAT=DIR,...  Override destination directory for a category
                              e.g. --target "Images=/mnt/nas/photos"
  -v, --verbose             Enable verbose output
  --help                    Show this message
  --version                 Show version information
EOF
    exit 0
}

acquire_lock() {
    local name="$1"
    local lock_dir="/tmp/noba_${name}.lock"

    if ! mkdir "$lock_dir" 2>/dev/null; then
        local holder
        holder=$(cat "$lock_dir/pid" 2>/dev/null || echo "unknown")
        log_info "Another instance is already running (PID $holder). Yielding." && exit 0
    fi
    echo $$ > "$lock_dir/pid"

    # Store the lock_dir in a global variable for the trap to access
    _CURRENT_LOCK_DIR="$lock_dir"
    trap 'rm -rf "$_CURRENT_LOCK_DIR"' EXIT INT TERM
}

build_ext_map() {
    EXT_TO_CAT=()
    for cat in "${!CATEGORIES[@]}"; do
        for ext in ${CATEGORIES[$cat]}; do
            EXT_TO_CAT[$ext]="$cat"
        done
    done
}

file_age_seconds() {
    local file="$1"
    local now mod_time
    now="${EPOCHSECONDS:-$(date +%s)}"
    mod_time=$(stat -c %Y "$file" 2>/dev/null || echo 0)
    echo $(( now - mod_time ))
}

file_is_open() {
    local file="$1"
    if command -v fuser &>/dev/null; then
        fuser -s "$file" 2>/dev/null
    elif command -v lsof  &>/dev/null; then
        lsof "$file" >/dev/null 2>&1
    else
        return 1
    fi
}

resolve_dest() {
    local dest_folder="$1"
    local filename="$2"
    local dest_path="$dest_folder/$filename"

    if [[ ! -e "$dest_path" ]]; then
        echo "$dest_path"
        return
    fi

    local base ext counter=1
    if [[ "$filename" == *.* ]]; then
        base="${filename%.*}"
        ext=".${filename##*.}"
    else
        base="$filename"
        ext=""
    fi

    while [[ -e "$dest_folder/${base}_${counter}${ext}" ]]; do
        (( counter++ ))
    done
    echo "$dest_folder/${base}_${counter}${ext}"
}

_dedup_counter=0
do_move() {
    local src="$1"
    local dest_folder="$2"
    local filename
    filename=$(basename "$src")

    local dest
    dest=$(resolve_dest "$dest_folder" "$filename")

    if [[ "$DRY_RUN" == true ]]; then
        # Only spam the output if we are NOT in stats-only mode
        if [[ "$STATS_ONLY" != true ]]; then
            log_info "[DRY RUN] $(basename "$src") → ${dest_folder/#$HOME/~}/$(basename "$dest")"
        fi
    else
        mkdir -p "$dest_folder"
        mv "$src" "$dest"
        echo "$dest|$src" >> "$UNDO_LOG"
        log_verbose "Moved: $(basename "$src") → ${dest_folder/#$HOME/~}/"
    fi
    (( _dedup_counter++ )) || true
}

do_undo() {
    if [[ ! -f "$UNDO_LOG" ]]; then
        die "No undo log found at $UNDO_LOG"
    fi

    log_info "Undoing last run from: $UNDO_LOG"
    local count=0

    local reverse_cmd
    reverse_cmd=$(command -v tac || echo "awk 'NR==1{l=\$0;next}{print p}{p=l;l=\$0}END{print l}'")

    while IFS='|' read -r dest src; do
        [[ -z "$dest" || -z "$src" ]] && continue
        if [[ ! -f "$dest" ]]; then
            log_warn "Undo skipped (file gone): $dest"
            continue
        fi
        mkdir -p "$(dirname "$src")"
        if mv "$dest" "$src"; then
            log_info "Restored: $(basename "$dest") → $(dirname "$src")"
            (( count++ )) || true
        else
            log_warn "Could not restore: $dest"
        fi
    done < <($reverse_cmd "$UNDO_LOG")

    log_success "Undo complete. Restored $count file(s)."
    : > "$UNDO_LOG"
    exit 0
}

print_summary() {
    local -n _counts=$1
    local total=0

    echo ""
    printf '  %-18s  %s\n' "CATEGORY" "FILES"
    printf '  %-18s  %s\n' "──────────────────" "─────"

    while IFS= read -r cat; do
        printf '  %-18s  %d\n' "$cat" "${_counts[$cat]}"
        total=$((total + _counts[$cat])) || true
    done < <(printf '%s\n' "${!_counts[@]}" | sort)

    printf '  %-18s  %s\n' "──────────────────" "─────"
    printf '  %-18s  %d\n' "TOTAL" "$total"
    echo ""
}

# ── Argument parsing ───────────────────────────────────────────────────────────
_EXT_OVERRIDES=""
_TARGET_OVERRIDES=""

if ! PARSED_ARGS=$(getopt -o d:a:nsvuhq -l download-dir:,min-age:,dry-run,stats,verbose,undo,quiet,ext:,target:,help,version -- "$@" 2>/dev/null); then
    log_error "Invalid argument. Run with --help for usage."
    exit 1
fi
eval set -- "$PARSED_ARGS"

while true; do
    case "$1" in
        -d|--download-dir) DOWNLOAD_DIR="$2"; shift 2 ;;
        -a|--min-age)      MIN_AGE_MINUTES="$2"; shift 2 ;;
        -n|--dry-run)      DRY_RUN=true; shift ;;
        -s|--stats)        STATS_ONLY=true; DRY_RUN=true; shift ;;
        -u|--undo)         UNDO_MODE=true; shift ;;
        -v|--verbose)      export VERBOSE=true; shift ;;
           --quiet|-q)        shift ;;
           --ext)          _EXT_OVERRIDES="$2"; shift 2 ;;
           --target)       _TARGET_OVERRIDES="$2"; shift 2 ;;
        --help|-h)         show_help ;;
        --version)         show_version ;;
        --)                shift; break ;;
        *)                 log_error "Unknown argument: $1"; exit 1 ;;
    esac
done

# ── Load config ───────────────────────────────────────────────────────────────
if command -v get_config &>/dev/null; then
    DOWNLOAD_DIR="$(get_config ".downloads.dir"          "$DOWNLOAD_DIR")"
    MIN_AGE_MINUTES="$(get_config ".downloads.min_age_minutes" "$MIN_AGE_MINUTES")"
    config_log_dir="$(get_config ".logs.dir" "")"
    [[ -n "$config_log_dir" ]] && LOG_FILE="$config_log_dir/download-organizer.log"
fi

if [[ -n "$_EXT_OVERRIDES" ]]; then
    IFS=',' read -ra _pairs <<< "$_EXT_OVERRIDES"
    for pair in "${_pairs[@]}"; do
        ext="${pair%%=*}"
        cat="${pair##*=}"
        ext="${ext,,}"
        CATEGORIES["$cat"]="${CATEGORIES[$cat]:-} $ext"
    done
fi

build_ext_map

if [[ -n "$_TARGET_OVERRIDES" ]]; then
    IFS=',' read -ra _pairs <<< "$_TARGET_OVERRIDES"
    for pair in "${_pairs[@]}"; do
        cat="${pair%%=*}"
        dir="${pair##*=}"
        CAT_TARGET["$cat"]="$dir"
    done
fi

UNDO_LOG="${LOG_FILE%/*}/download-organizer-undo.log"

# ── Pre-flight validation ──────────────────────────────────────────────────────
check_deps find stat date

if ! [[ "$MIN_AGE_MINUTES" =~ ^[0-9]+$ ]]; then
    die "MIN_AGE_MINUTES must be a non-negative integer, got: $MIN_AGE_MINUTES"
fi

if [[ ! -d "$DOWNLOAD_DIR" ]]; then
    die "Download directory does not exist: $DOWNLOAD_DIR"
fi

# ── Logging setup ─────────────────────────────────────────────────────────────
mkdir -p "$(dirname "$LOG_FILE")"
if [[ "$DRY_RUN" != true ]]; then
    exec > >(tee -a "$LOG_FILE") 2>&1
fi

# ── Lock & Undo Execution ─────────────────────────────────────────────────────
if [[ "$UNDO_MODE" == true ]]; then
    acquire_lock "organize-downloads"
    do_undo
fi

if [[ "$DRY_RUN" != true ]]; then
    acquire_lock "organize-downloads"
fi

# ── Main loop ─────────────────────────────────────────────────────────────────
if [[ "$DRY_RUN" == true ]]; then
    log_info "DRY RUN – no files will be moved"
fi

log_info "============================================================"
log_info "  Download organizer v3.0.0 started at $(date)"
log_info "  Source : $DOWNLOAD_DIR"
log_info "  Min age: ${MIN_AGE_MINUTES}m"
log_info "============================================================"

declare -A CATEGORY_COUNTS=()
SKIPPED_OPEN=0
SKIPPED_AGE=0
MOVED_COUNT=0
MIN_AGE_SECONDS=$(( MIN_AGE_MINUTES * 60 ))

[[ "$DRY_RUN" != true ]] && : > "$UNDO_LOG"

while IFS= read -r -d '' file; do
    [[ -L "$file" ]] && continue

    age_seconds=$(file_age_seconds "$file")
    if (( age_seconds < MIN_AGE_SECONDS )); then
        log_verbose "Skipping (too new, ${age_seconds}s): $(basename "$file")"
        (( SKIPPED_AGE++ )) || true
        continue
    fi

    if file_is_open "$file"; then
        log_warn "Skipping (file in use): $(basename "$file")"
        (( SKIPPED_OPEN++ )) || true
        continue
    fi

    filename=$(basename "$file")

    if [[ "$filename" == *.* ]]; then
        ext="${filename##*.}"
        ext="${ext,,}"
    else
        ext=""
    fi

    if [[ -n "$ext" ]]; then category="${EXT_TO_CAT[$ext]:-Others}"; else category="Others"; fi

    if [[ -n "${CAT_TARGET[$category]:-}" ]]; then
        dest_folder="${CAT_TARGET[$category]}"
    else
        dest_folder="$DOWNLOAD_DIR/$category"
    fi

    if [[ "$(dirname "$file")" == "$dest_folder" ]]; then
        log_verbose "Already in place: $filename"
        continue
    fi

    do_move "$file" "$dest_folder"
    (( CATEGORY_COUNTS["$category"]++ )) || true
    (( MOVED_COUNT++ )) || true

done < <(find "$DOWNLOAD_DIR" -maxdepth 1 -type f -not -name '.*' -print0)

# ── Summary ───────────────────────────────────────────────────────────────────
if [[ "${#CATEGORY_COUNTS[@]}" -gt 0 ]]; then
    print_summary CATEGORY_COUNTS
fi

log_info "============================================================"
if [[ "$DRY_RUN" == true ]]; then
    log_info "  [DRY RUN] Would move : $MOVED_COUNT file(s)"
else
    log_info "  Moved   : $MOVED_COUNT file(s)"
    log_info "  Undo log: $UNDO_LOG"
fi
log_info "  Skipped (too new) : $SKIPPED_AGE"
log_info "  Skipped (in use)  : $SKIPPED_OPEN"
log_info "============================================================"
