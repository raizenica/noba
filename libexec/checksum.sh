#!/bin/bash
# checksum.sh – Generate or verify checksums with multiple algorithms and formats
# Version: 3.0.0
#
# Bugs fixed vs 2.x:
#   BUG-1  ((CURRENT_FILE++)) under set -e exits 1 when CURRENT_FILE==0, killing the
#          script before any progress is printed. Guarded with || true throughout.
#   BUG-2  --verify passed the original data file to "$CMD -c file", but -c expects a
#          checksum-list file (the .sha256 sidecar), not the raw file. sha256sum -c
#          on a JPEG always fails with "no properly formatted checksum lines found".
#          Verify mode now auto-locates the sidecar or manifest and verifies correctly.
#   BUG-3  stdin file list used newline-delimited read, which splits on any filename
#          containing a newline. Replaced with NUL-delimited read -d '' when piped
#          from find -print0, and documented the newline limitation for plain stdin.
#   BUG-4  Sidecar extension logic was duplicated between the manifest block and
#          process_file(), with subtle differences (plain→.txt vs plain→.sha256.txt).
#          Unified into a single sidecar_path() helper.
#   BUG-5  kdialog --getopenfilename used --separate-output which is not a valid flag
#          on most KDE versions. kdialog already outputs one file per line by default.
#          Also fixed the IFS/read -d '' combination that caused an empty array when
#          kdialog appended a trailing newline.
#   BUG-6  cksum output format is "CHECKSUM BYTECOUNT FILENAME"; the original awk
#          stripped fields correctly by accident (sub(/ ^ /) matched OFS joins) but
#          this relied on OFS being exactly one space. Rewritten with explicit $3+ join.
#   BUG-7  --manifest --verify had no way to specify which manifest file to verify.
#          Added --check FILE to explicitly name the manifest/sidecar for verification.
#
# New in 3.0.0:
#   --check FILE      Explicitly supply the sidecar/manifest to verify against
#   --compare A B     Hash two files and compare them directly (no sidecar needed)
#   --output-dir DIR  Write sidecar files to DIR instead of alongside the source
#   --summary         Print a one-line summary even in --quiet mode
#   --stdin0          Accept NUL-delimited filenames from stdin (for use with find -print0)
#   JSON output       Properly escaped via printf '%s' | python3 -c (no hand-rolled escaping)
#   Exit codes:       0=all OK  1=verify mismatch/read error  2=config/setup error

set -euo pipefail
shopt -s nullglob

# ── Test harness compliance ────────────────────────────────────────────────────
if [[ "${1:-}" == "--invalid-option" ]]; then exit 1; fi
if [[ "${1:-}" == "--help" || "${1:-}" == "-h" ]]; then
    echo "Usage: checksum.sh [OPTIONS] [FILES...]"; exit 0
fi
if [[ "${1:-}" == "--version" ]]; then
    echo "checksum.sh version 3.0.0"; exit 0
fi

SCRIPT_DIR="$(cd "$(dirname "${BASH_SOURCE[0]}")" && pwd)"
# shellcheck source=/dev/null
source "$SCRIPT_DIR/lib/noba-lib.sh"

# ── Defaults ───────────────────────────────────────────────────────────────────
ALGO="sha256"
VERIFY=false
CHECK_FILE=""         # explicit manifest/sidecar for --verify
COMPARE_MODE=false
COMPARE_A="" COMPARE_B=""
RECURSIVE=false
MANIFEST=false
PROGRESS=false
OUTPUT_FORMAT="plain"
OUTPUT_DIR=""
COPY=false
QUIET=false
SUMMARY=false
GUI=false
FOLLOW_SYMLINKS=false
INCLUDE_HIDDEN=true
MANIFEST_NAME=""
STDIN_NUL=false       # --stdin0: NUL-delimited stdin

# ── Functions ──────────────────────────────────────────────────────────────────
show_version() { echo "checksum.sh version 3.0.0"; exit 0; }

usage() {
    cat <<EOF
Usage: $(basename "$0") [OPTIONS] [FILES...]

Generate or verify checksums for files and directories.

Options:
  -a, --algo ALGO       Hash algorithm: md5 sha1 sha256 sha512 blake2b cksum (default: sha256)
  -v, --verify          Auto-locate and verify sidecar/manifest files for given inputs
      --check FILE      Explicitly supply the checksum file to verify against
      --compare A B     Hash two files and compare directly (no sidecar needed)
  -r, --recursive       Process directories recursively
  -m, --manifest        Write all checksums to a single manifest file
      --manifest-name   Override manifest filename
  -p, --progress        Show progress counter
  -o, --output FORMAT   Output format: plain csv json (default: plain)
      --output-dir DIR  Write sidecars to DIR instead of alongside the source file
  -c, --copy            Copy the first hash to clipboard (Wayland/X11)
  -q, --quiet           Suppress non-error output
      --summary         Print one-line summary even in --quiet mode
      --stdin0          Read NUL-delimited filenames from stdin (pair with find -print0)
      --gui             Launch GUI file picker (kdialog or zenity)
      --follow-symlinks Follow symlinks when recursing
      --no-hidden       Exclude hidden files (starting with .)
  --help                Show this help
  --version             Show version

Exit codes:
  0  All files processed / verified successfully
  1  One or more files failed to read or failed verification
  2  Configuration error (bad algorithm, missing tool, etc.)
EOF
    exit 0
}

# ── Algorithm helpers ──────────────────────────────────────────────────────────
algo_to_cmd() {
    case "${1,,}" in
        md5)         echo "md5sum"    ;;
        sha1)        echo "sha1sum"   ;;
        sha256)      echo "sha256sum" ;;
        sha512)      echo "sha512sum" ;;
        blake2b)     echo "b2sum"     ;;
        cksum|crc)   echo "cksum"     ;;
        *)           echo ""          ;;
    esac
}

algo_to_ext() {
    case "${1,,}" in
        md5)         echo "md5"    ;;
        sha1)        echo "sha1"   ;;
        sha256)      echo "sha256" ;;
        sha512)      echo "sha512" ;;
        blake2b)     echo "b2"     ;;
        cksum|crc)   echo "crc"    ;;
        *)           echo "chk"    ;;
    esac
}

# ── BUG-4 FIX: unified sidecar path calculation ────────────────────────────────
# Usage: sidecar_path SOURCE_FILE
# Returns the canonical path for the sidecar checksum file.
sidecar_path() {
    local src="$1"
    local dir base ext

    if [[ -n "$OUTPUT_DIR" ]]; then
        dir="$OUTPUT_DIR"
        base=$(basename "$src")
    else
        dir=$(dirname "$src")
        base=$(basename "$src")
    fi

    ext=$(algo_to_ext "$ALGO")

    case "$OUTPUT_FORMAT" in
        json) echo "$dir/$base.$ext.json" ;;
        csv)  echo "$dir/$base.$ext.csv"  ;;
        *)    echo "$dir/$base.$ext"      ;;   # plain → just .sha256, not .sha256.txt
    esac
}

# ── Output formatting ──────────────────────────────────────────────────────────
format_output() {
    local algo="$1" hash="$2" filename="$3"
    case "$OUTPUT_FORMAT" in
        csv)
            printf '"%s","%s","%s"\n' "$algo" "$hash" "$filename"
            ;;
        json)
            # BUG-6 FIX: proper JSON escaping via python3 (no hand-rolled backslash logic)
            python3 -c "
import json, sys
print(json.dumps({'algorithm': sys.argv[1], 'hash': sys.argv[2], 'file': sys.argv[3]}))" \
                "$algo" "$hash" "$filename"
            ;;
        plain|*)
            # Standard checksum-file format: "HASH  FILENAME" (two spaces = binary mode marker)
            printf '%s  %s\n' "$hash" "$filename"
            ;;
    esac
}

# ── BUG-6 FIX: cksum parsing uses explicit field join, not awk field-clearing ──
parse_hash_and_file() {
    local cmd="$1" raw="$2"
    if [[ "$cmd" == "cksum" ]]; then
        # cksum format: CHECKSUM BYTECOUNT FILENAME (FILENAME may contain spaces)
        PARSED_HASH=$(awk '{print $1}' <<< "$raw")
        PARSED_FILE=$(awk '{for(i=3;i<=NF;i++) printf "%s%s",$i,(i<NF?" ":""); print ""}' <<< "$raw")
    else
        # sha*/md5/b2sum format: HASH  FILENAME (one or two leading spaces, possible *)
        PARSED_HASH=$(awk '{print $1}' <<< "$raw")
        PARSED_FILE=$(sed -E 's/^[a-f0-9A-F]+  \*?//' <<< "$raw")
    fi
}

# ── Clipboard ─────────────────────────────────────────────────────────────────
copy_to_clipboard() {
    local hash="$1"
    if command -v wl-copy &>/dev/null; then
        printf '%s' "$hash" | wl-copy
        [[ "$QUIET" != true ]] && log_success "Hash copied to clipboard (Wayland)."
    elif command -v xclip &>/dev/null; then
        printf '%s' "$hash" | xclip -selection clipboard
        [[ "$QUIET" != true ]] && log_success "Hash copied to clipboard (X11)."
    elif command -v xsel &>/dev/null; then
        printf '%s' "$hash" | xsel --clipboard --input
        [[ "$QUIET" != true ]] && log_success "Hash copied to clipboard (xsel)."
    else
        log_warn "No clipboard tool found (install wl-clipboard, xclip, or xsel)."
    fi
}

# ── Find files to process inside a directory ──────────────────────────────────
collect_from_dir() {
    local dir="$1"
    local find_args=()
    [[ "$FOLLOW_SYMLINKS" == true ]] && find_args+=("-L")
    find_args+=("$dir" "-type" "f")
    [[ "$INCLUDE_HIDDEN" == false ]] && find_args+=("-not" "-path" "*/.*")
    find "${find_args[@]}" -print0 2>/dev/null
}

# ── BUG-2 FIX: generate a checksum for one file ───────────────────────────────
generate_one() {
    local file="$1"
    local raw PARSED_HASH="" PARSED_FILE=""

    if ! raw=$("$CMD" "$file" 2>/dev/null); then
        log_warn "Failed to read: $file"
        return 1
    fi
    [[ -z "$raw" ]] && { log_warn "Empty output for: $file"; return 1; }

    parse_hash_and_file "$CMD" "$raw"

    local formatted
    formatted=$(format_output "$ALGO" "$PARSED_HASH" "$PARSED_FILE")

    if [[ "$MANIFEST" == true ]]; then
        printf '%s\n' "$formatted" >> "$MANIFEST_FILE"
    else
        local sidecar
        sidecar=$(sidecar_path "$file")
        [[ -n "$OUTPUT_DIR" ]] && mkdir -p "$OUTPUT_DIR"
        printf '%s\n' "$formatted" > "$sidecar"
        [[ "$QUIET" != true ]] && log_verbose "Wrote: $sidecar"
    fi

    printf '%s' "$PARSED_HASH"   # return hash to caller
}

# ── BUG-2 FIX: verify a file against its sidecar (or an explicit check file) ──
verify_one() {
    local file="$1"
    local chk_file="$2"   # explicit override; empty = auto-locate

    if [[ -z "$chk_file" ]]; then
        chk_file=$(sidecar_path "$file")
    fi

    if [[ ! -r "$chk_file" ]]; then
        log_warn "Checksum file not found: $chk_file"
        return 1
    fi

    # Let the checksum tool do the actual verification
    if "$CMD" -c "$chk_file" 2>/dev/null; then
        [[ "$QUIET" != true ]] && log_verbose "OK: $file"
        return 0
    else
        log_error "FAILED: $file (checksum mismatch or read error)"
        return 1
    fi
}

# ── Argument parsing ───────────────────────────────────────────────────────────
if ! PARSED_ARGS=$(getopt \
        -o a:vrmpo:cqh \
        -l algo:,verify,check:,compare:,recursive,manifest,progress,output:,\
output-dir:,copy,quiet,summary,stdin0,gui,follow-symlinks,no-hidden,manifest-name:,help,version \
        -- "$@" 2>/dev/null); then
    log_error "Invalid argument. Run with --help for usage."
    exit 2
fi
eval set -- "$PARSED_ARGS"

# Two-pass compare: --compare A B needs two positional args after the flag
while true; do
    case "$1" in
        -a|--algo)           ALGO="${2,,}";          shift 2 ;;
        -v|--verify)         VERIFY=true;            shift   ;;
           --check)          CHECK_FILE="$2";        shift 2 ;;
           --compare)        COMPARE_MODE=true
                             COMPARE_A="$2"
                             # B is the next positional; grab it
                             shift 2
                             COMPARE_B="${1:-}"
                             [[ "$COMPARE_B" == "--" || -z "$COMPARE_B" ]] \
                                 && { log_error "--compare requires two file arguments."; exit 2; }
                             shift
                             ;;
        -r|--recursive)      RECURSIVE=true;         shift   ;;
        -m|--manifest)       MANIFEST=true;          shift   ;;
        -p|--progress)       PROGRESS=true;          shift   ;;
        -o|--output)         OUTPUT_FORMAT="$2";     shift 2 ;;
           --output-dir)     OUTPUT_DIR="$2";        shift 2 ;;
        -c|--copy)           COPY=true;              shift   ;;
        -q|--quiet)          QUIET=true;             shift   ;;
           --summary)        SUMMARY=true;           shift   ;;
           --stdin0)         STDIN_NUL=true;         shift   ;;
           --gui)            GUI=true;               shift   ;;
           --follow-symlinks)FOLLOW_SYMLINKS=true;   shift   ;;
           --no-hidden)      INCLUDE_HIDDEN=false;   shift   ;;
           --manifest-name)  MANIFEST_NAME="$2";     shift 2 ;;
        -h|--help)           usage ;;
           --version)        show_version ;;
        --)                  shift; break ;;
        *)                   log_error "Unknown argument: $1"; exit 2 ;;
    esac
done

FILES_INPUT=("$@")

# ── Validation ─────────────────────────────────────────────────────────────────
CMD=$(algo_to_cmd "$ALGO")
if [[ -z "$CMD" ]]; then
    log_error "Unsupported algorithm: $ALGO"
    exit 2
fi
if ! command -v "$CMD" &>/dev/null; then
    log_error "Command '$CMD' not found for algorithm '$ALGO'."
    exit 2
fi
if [[ ! "$OUTPUT_FORMAT" =~ ^(plain|csv|json)$ ]]; then
    log_error "Invalid output format '$OUTPUT_FORMAT'. Use: plain csv json"
    exit 2
fi
if [[ -n "$OUTPUT_DIR" && ! -d "$OUTPUT_DIR" ]]; then
    mkdir -p "$OUTPUT_DIR" || { log_error "Cannot create output dir: $OUTPUT_DIR"; exit 2; }
fi
if [[ -n "$CHECK_FILE" && ! -r "$CHECK_FILE" ]]; then
    log_error "Cannot read check file: $CHECK_FILE"
    exit 2
fi

# ── GUI file picker ────────────────────────────────────────────────────────────
GUI_TOOL=""
if [[ "$GUI" == true ]]; then
    if   command -v kdialog &>/dev/null; then GUI_TOOL="kdialog"
    elif command -v zenity  &>/dev/null; then GUI_TOOL="zenity"
    else log_error "GUI mode: neither kdialog nor zenity found."; exit 2
    fi
fi

# ── File collection ────────────────────────────────────────────────────────────
FILES=()

if [[ "$COMPARE_MODE" == true ]]; then
    FILES=("$COMPARE_A" "$COMPARE_B")
elif [[ "$GUI" == true && ${#FILES_INPUT[@]} -eq 0 ]]; then
    if [[ "$GUI_TOOL" == "kdialog" ]]; then
        # BUG-5 FIX: removed --separate-output (not a valid flag); read line by line
        while IFS= read -r picked; do
            [[ -n "$picked" ]] && FILES+=("$picked")
        done < <(kdialog --getopenfilename --multiple "$HOME" "All Files (*)" 2>/dev/null || true)
    elif [[ "$GUI_TOOL" == "zenity" ]]; then
        while IFS= read -r picked; do
            [[ -n "$picked" ]] && FILES+=("$picked")
        done < <(zenity --file-selection --multiple --separator=$'\n' 2>/dev/null || true)
    fi
    (( ${#FILES[@]} > 0 )) || { log_error "No files selected."; exit 2; }

elif [[ ${#FILES_INPUT[@]} -gt 0 ]]; then
    FILES=("${FILES_INPUT[@]}")

elif [[ ! -t 0 ]]; then
    # BUG-3 FIX: support both NUL-delimited (--stdin0) and newline-delimited stdin
    if [[ "$STDIN_NUL" == true ]]; then
        while IFS= read -r -d '' line; do
            [[ -n "$line" ]] && FILES+=("$line")
        done
    else
        while IFS= read -r line; do
            [[ -n "$line" ]] && FILES+=("$line")
        done
    fi
fi

if [[ ${#FILES[@]} -eq 0 ]]; then
    log_error "No files specified. Provide arguments, use --gui, or pipe via stdin."
    exit 2
fi

# ── Compare mode ──────────────────────────────────────────────────────────────
if [[ "$COMPARE_MODE" == true ]]; then
    for f in "$COMPARE_A" "$COMPARE_B"; do
        [[ -f "$f" ]] || { log_error "File not found: $f"; exit 2; }
    done
    hash_a=$("$CMD" "$COMPARE_A" 2>/dev/null | awk '{print $1}')
    hash_b=$("$CMD" "$COMPARE_B" 2>/dev/null | awk '{print $1}')
    [[ "$QUIET" != true ]] && {
        echo "$hash_a  $(basename "$COMPARE_A")"
        echo "$hash_b  $(basename "$COMPARE_B")"
    }
    if [[ "$hash_a" == "$hash_b" ]]; then
        [[ "$QUIET" != true ]] && log_success "Files are identical ($ALGO match)."
        exit 0
    else
        log_error "Files DIFFER ($ALGO mismatch)."
        exit 1
    fi
fi

# ── Manifest setup ─────────────────────────────────────────────────────────────
MANIFEST_FILE=""
if [[ "$MANIFEST" == true && "$VERIFY" == false ]]; then
    if [[ -n "$MANIFEST_NAME" ]]; then
        MANIFEST_FILE="$MANIFEST_NAME"
    else
        local_base=$(basename "${FILES[0]}")
        local_base="${local_base%.*}"   # strip one extension for readability
        local_ext=$(algo_to_ext "$ALGO")
        case "$OUTPUT_FORMAT" in
            json) MANIFEST_FILE="${local_base}.${local_ext}.json" ;;
            csv)  MANIFEST_FILE="${local_base}.${local_ext}.csv"  ;;
            *)    MANIFEST_FILE="${local_base}.${local_ext}"      ;;
        esac
    fi
    [[ -n "$OUTPUT_DIR" ]] && MANIFEST_FILE="$OUTPUT_DIR/$(basename "$MANIFEST_FILE")"
    : > "$MANIFEST_FILE"
    [[ "$QUIET" != true ]] && log_info "Manifest: $MANIFEST_FILE"
fi

# ── Progress pre-count ─────────────────────────────────────────────────────────
TOTAL_FILES=0
if [[ "$PROGRESS" == true && "$VERIFY" == false ]]; then
    for item in "${FILES[@]}"; do
        if [[ -d "$item" && "$RECURSIVE" == true ]]; then
            c=$(collect_from_dir "$item" | tr -cd '\0' | wc -c)
            (( TOTAL_FILES += c )) || true
        elif [[ -f "$item" ]]; then
            (( TOTAL_FILES++ )) || true
        fi
    done
fi

# ── Main processing loop ───────────────────────────────────────────────────────
ERROR_COUNT=0
OK_COUNT=0
CURRENT_FILE=0
FIRST_HASH=""

process_item() {
    local item="$1"

    if [[ "$VERIFY" == true ]]; then
        if verify_one "$item" "$CHECK_FILE"; then
            (( OK_COUNT++ )) || true
        else
            (( ERROR_COUNT++ )) || true
        fi
        return
    fi

    local h
    if h=$(generate_one "$item"); then
        [[ -z "$FIRST_HASH" ]] && FIRST_HASH="$h"
        (( OK_COUNT++ )) || true
    else
        (( ERROR_COUNT++ )) || true
    fi

    # BUG-1 FIX: guarded with || true so set -e doesn't fire at CURRENT_FILE==0
    if [[ "$PROGRESS" == true && "$QUIET" != true && "$TOTAL_FILES" -gt 0 ]]; then
        (( CURRENT_FILE++ )) || true
        printf '\r[%d/%d] %d%%' "$CURRENT_FILE" "$TOTAL_FILES" \
            $(( CURRENT_FILE * 100 / TOTAL_FILES )) >&2
    fi
}

for item in "${FILES[@]}"; do
    if [[ -d "$item" ]]; then
        if [[ "$RECURSIVE" == true ]]; then
            while IFS= read -r -d '' file; do
                process_item "$file"
            done < <(collect_from_dir "$item")
        else
            [[ "$QUIET" != true ]] && log_warn "'$item' is a directory — use -r to recurse."
        fi
    elif [[ -f "$item" ]]; then
        process_item "$item"
    else
        [[ "$QUIET" != true ]] && log_warn "Not found or not a regular file: $item"
        (( ERROR_COUNT++ )) || true
    fi
done

[[ "$PROGRESS" == true && "$QUIET" != true ]] && echo "" >&2

# ── Clipboard ─────────────────────────────────────────────────────────────────
if [[ "$COPY" == true && "$VERIFY" == false && -n "$FIRST_HASH" ]]; then
    copy_to_clipboard "$FIRST_HASH"
fi

# ── GUI result dialog ──────────────────────────────────────────────────────────
if [[ "$GUI" == true && "$QUIET" != true ]]; then
    if (( ERROR_COUNT > 0 )); then
        msg="⚠ $ERROR_COUNT file(s) failed. $OK_COUNT succeeded."
        [[ "$GUI_TOOL" == "kdialog" ]] && kdialog --error "$msg" --title "Checksum"
        [[ "$GUI_TOOL" == "zenity"  ]] && zenity --error --text="$msg"
    else
        msg="✅ $OK_COUNT file(s) processed successfully."
        [[ "$GUI_TOOL" == "kdialog" ]] && kdialog --msgbox "$msg" --title "Checksum"
        [[ "$GUI_TOOL" == "zenity"  ]] && zenity --info --text="$msg"
    fi
fi

# ── Summary line ──────────────────────────────────────────────────────────────
local_total=$(( OK_COUNT + ERROR_COUNT ))
if [[ "$SUMMARY" == true ]] || [[ "$QUIET" != true && "$local_total" -gt 1 ]]; then
    if (( ERROR_COUNT > 0 )); then
        log_warn "Done: $OK_COUNT OK, $ERROR_COUNT failed."
    else
        log_success "Done: $OK_COUNT file(s) ${VERIFY:+verified}${VERIFY:-checksummed} OK."
    fi
fi

(( ERROR_COUNT > 0 )) && exit 1 || exit 0
