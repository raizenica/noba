#!/bin/bash
# checksum.sh – Generate or verify checksums with multiple algorithms and formats
# Version: 2.2.0

set -euo pipefail
shopt -s nullglob

SCRIPT_DIR="$(cd "$(dirname "${BASH_SOURCE[0]}")" && pwd)"
# shellcheck source=/dev/null
source "$SCRIPT_DIR/noba-lib.sh"

# -------------------------------------------------------------------
# Configuration and defaults
# -------------------------------------------------------------------
ALGO="sha256"
VERIFY=false
RECURSIVE=false
MANIFEST=false
PROGRESS=false
OUTPUT_FORMAT="plain"
COPY=false
QUIET=false
GUI=false
FOLLOW_SYMLINKS=false
INCLUDE_HIDDEN=true
MANIFEST_NAME=""

# -------------------------------------------------------------------
# Helper functions
# -------------------------------------------------------------------
show_version() {
    echo "checksum.sh version 2.2.0"
    exit 0
}

usage() {
    cat <<EOF
Usage: $0 [options] [files...]

Generate or verify checksums for files and directories.

Options:
  -a, --algo ALGO       Hash algorithm: md5, sha1, sha256, sha512, blake2b, cksum (default: sha256)
  -v, --verify          Verify checksums from files
  -r, --recursive       Process directories recursively
  -m, --manifest        Generate a single manifest file (all checksums in one file)
  -p, --progress        Show progress (file count)
  -o, --output FORMAT   Output format: plain, csv, json (default: plain)
  -c, --copy            Copy the first hash to clipboard (X11/Wayland)
  -q, --quiet           Suppress non-error output
  --gui                 Launch GUI file picker (supports kdialog or zenity)
  --follow-symlinks     Follow symbolic links when recursing
  --no-hidden           Exclude hidden files (those starting with .)
  --manifest-name NAME  Custom name for manifest file (ignored without --manifest)
  --help                Show this help
  --version             Show version information
EOF
    exit 0
}

algo_to_cmd() {
    case "${1,,}" in
        md5)       echo "md5sum" ;;
        sha1)      echo "sha1sum" ;;
        sha256)    echo "sha256sum" ;;
        sha512)    echo "sha512sum" ;;
        blake2b)   echo "b2sum" ;;
        cksum|crc) echo "cksum" ;;
        *)         echo "unsupported" ;;
    esac
}

algo_to_ext() {
    case "${1,,}" in
        md5)       echo "md5" ;;
        sha1)      echo "sha1" ;;
        sha256)    echo "sha256" ;;
        sha512)    echo "sha512" ;;
        blake2b)   echo "b2" ;;
        cksum|crc) echo "crc" ;;
        *)         echo "txt" ;;
    esac
}

format_output() {
    local algo="$1"
    local hash="$2"
    local filename="$3"
    case "$OUTPUT_FORMAT" in
        csv)
            printf '"%s","%s","%s"\n' "$algo" "$hash" "$filename"
            ;;
        json)
            # Basic JSON escaping for the filename
            local safe_file="${filename//\"/\\\"}"
            printf '{"algorithm":"%s","hash":"%s","file":"%s"}\n' "$algo" "$hash" "$safe_file"
            ;;
        plain|*)
            printf '%s  %s\n' "$hash" "$filename"
            ;;
    esac
}

# -------------------------------------------------------------------
# Parse command-line arguments
# -------------------------------------------------------------------
if ! PARSED_ARGS=$(getopt -o a:vrmpo:cq -l algo:,verify,recursive,manifest,progress,output:,copy,quiet,gui,follow-symlinks,no-hidden,manifest-name:,help,version -- "$@"); then
    usage
fi
eval set -- "$PARSED_ARGS"

while true; do
    case "$1" in
        -a|--algo)          ALGO="${2,,}"; shift 2 ;;
        -v|--verify)        VERIFY=true; shift ;;
        -r|--recursive)     RECURSIVE=true; shift ;;
        -m|--manifest)      MANIFEST=true; shift ;;
        -p|--progress)      PROGRESS=true; shift ;;
        -o|--output)        OUTPUT_FORMAT="$2"; shift 2 ;;
        -c|--copy)          COPY=true; shift ;;
        -q|--quiet)         QUIET=true; shift ;;
        --gui)              GUI=true; shift ;;
        --follow-symlinks)  FOLLOW_SYMLINKS=true; shift ;;
        --no-hidden)        INCLUDE_HIDDEN=false; shift ;;
        --manifest-name)    MANIFEST_NAME="$2"; shift 2 ;;
        --help)             usage ;;
        --version)          show_version ;;
        --)                 shift; break ;;
        *)                  break ;;
    esac
done

# Collect remaining positional arguments as files
FILES_INPUT=("$@")

# -------------------------------------------------------------------
# Pre-flight checks
# -------------------------------------------------------------------
CMD=$(algo_to_cmd "$ALGO")
if [ "$CMD" = "unsupported" ]; then
    die "Unsupported algorithm '$ALGO'."
fi
if ! command -v "$CMD" &>/dev/null; then
    die "Command '$CMD' not available for algorithm '$ALGO'."
fi
if [[ ! "$OUTPUT_FORMAT" =~ ^(plain|csv|json)$ ]]; then
    die "Invalid output format '$OUTPUT_FORMAT'. Use plain, csv, or json."
fi

# Determine GUI Tool
GUI_TOOL=""
if [ "$GUI" = true ]; then
    if command -v kdialog &>/dev/null; then GUI_TOOL="kdialog"
    elif command -v zenity &>/dev/null; then GUI_TOOL="zenity"
    else die "GUI mode requested but neither kdialog nor zenity is installed."
    fi
fi

# -------------------------------------------------------------------
# File Collection
# -------------------------------------------------------------------
FILES=()
if [ "$GUI" = true ] && [ ${#FILES_INPUT[@]} -eq 0 ]; then
    if [ "$GUI_TOOL" = "kdialog" ]; then
        IFS=$'\n' read -d '' -r -a FILES < <(kdialog --getopenfilename --multiple --separate-output "$HOME" "All Files (*)" 2>/dev/null || true)
    elif [ "$GUI_TOOL" = "zenity" ]; then
        IFS='|' read -r -a FILES < <(zenity --file-selection --multiple --separator="|" 2>/dev/null || true)
    fi

    if [ ${#FILES[@]} -eq 0 ]; then
        die "No files selected."
    fi
elif [ ${#FILES_INPUT[@]} -gt 0 ]; then
    FILES=("${FILES_INPUT[@]}")
elif [ ! -t 0 ]; then
    while IFS= read -r line; do
        [[ -n "$line" ]] && FILES+=("$line")
    done
fi

if [ ${#FILES[@]} -eq 0 ]; then
    die "No files specified. Use --gui, provide arguments, or pipe files via stdin."
fi

# -------------------------------------------------------------------
# Main processing
# -------------------------------------------------------------------
ERROR_OCCURRED=false
TOTAL_FILES=0
CURRENT_FILE=0
FIRST_HASH="" # Captured purely for clipboard

MANIFEST_FILE=""
if [ "$MANIFEST" = true ] && [ "$VERIFY" = false ]; then
    if [ -n "$MANIFEST_NAME" ]; then
        MANIFEST_FILE="$MANIFEST_NAME"
    else
        base=$(basename "${FILES[0]%.*}")
        MANIFEST_FILE="${base}.$(algo_to_ext "$ALGO").${OUTPUT_FORMAT}"
        # Standardize plain text to .txt
        [[ "$OUTPUT_FORMAT" == "plain" ]] && MANIFEST_FILE="${base}.$(algo_to_ext "$ALGO").txt"
    fi
    : > "$MANIFEST_FILE"
    [ "$QUIET" = false ] && log_info "Writing manifest to: $MANIFEST_FILE"
fi

# Pre-calculate file count for progress bar
if [ "$PROGRESS" = true ] && [ "$VERIFY" = false ]; then
    for item in "${FILES[@]}"; do
        if [ -d "$item" ] && [ "$RECURSIVE" = true ]; then
            find_args=()
            [ "$FOLLOW_SYMLINKS" = true ] && find_args+=("-L")
            [ "$INCLUDE_HIDDEN" = false ] && find_args+=("-not" "-path" "*/.*")

            # Fast count without word-splitting vulnerabilities
            count=$(find "${find_args[@]}" "$item" -type f -printf '.' 2>/dev/null | wc -c)
            TOTAL_FILES=$((TOTAL_FILES + count))
        elif [ -f "$item" ]; then
            TOTAL_FILES=$((TOTAL_FILES + 1))
        fi
    done
fi

process_file() {
    local file="$1"

    if [ "$VERIFY" = true ]; then
        if ! "$CMD" -c "$file" 2>/dev/null; then
            ERROR_OCCURRED=true
        fi
        return
    fi

    # Generate mode
    local raw_output hash filename
    raw_output=$("$CMD" "$file" 2>/dev/null || true)

    if [ -z "$raw_output" ]; then
        log_warn "Failed to read: $file" >&2
        ERROR_OCCURRED=true
        return
    fi

    # Parse based on tool (cksum vs standard md5/sha tools)
    if [ "$CMD" = "cksum" ]; then
        hash=$(echo "$raw_output" | awk '{print $1}')
        filename=$(echo "$raw_output" | awk '{$1=""; $2=""; sub(/^  /, ""); print}')
    else
        hash=$(echo "$raw_output" | awk '{print $1}')
        # Remove the hash and the specific spacing (usually two spaces or ' *')
        filename=$(echo "$raw_output" | sed -E "s/^[a-f0-9]+ [ *]?//")
    fi

    # Capture very first hash for the clipboard
    if [ -z "$FIRST_HASH" ]; then
        FIRST_HASH="$hash"
    fi

    local formatted
    formatted=$(format_output "$ALGO" "$hash" "$filename")

    if [ "$MANIFEST" = true ]; then
        echo "$formatted" >> "$MANIFEST_FILE"
    else
        local out_ext
        [[ "$OUTPUT_FORMAT" == "plain" ]] && out_ext="txt" || out_ext="$OUTPUT_FORMAT"
        echo "$formatted" > "${file}.$(algo_to_ext "$ALGO").${out_ext}"
    fi

    # Update progress
    if [ "$PROGRESS" = true ] && [ "$QUIET" = false ] && [ "$TOTAL_FILES" -gt 0 ]; then
        ((CURRENT_FILE++))
        printf "\r[%d/%d] %d%% %s" "$CURRENT_FILE" "$TOTAL_FILES" $((CURRENT_FILE * 100 / TOTAL_FILES)) "$hash" >&2
    fi
}

for item in "${FILES[@]}"; do
    if [ -d "$item" ]; then
        if [ "$RECURSIVE" = true ]; then
            find_args=()
            [ "$FOLLOW_SYMLINKS" = true ] && find_args+=("-L")
            [ "$INCLUDE_HIDDEN" = false ] && find_args+=("-not" "-path" "*/.*")

            while IFS= read -r -d '' file; do
                process_file "$file"
            done < <(find "${find_args[@]}" "$item" -type f -print0)
        else
            [ "$QUIET" = false ] && log_warn "'$item' is a directory. Use -r to recurse." >&2
        fi
    elif [ -f "$item" ]; then
        process_file "$item"
    else
        [ "$QUIET" = false ] && log_warn "'$item' not found or not a regular file." >&2
    fi
done

if [ "$PROGRESS" = true ] && [ "$QUIET" = false ]; then
    echo "" >&2
fi

# -------------------------------------------------------------------
# Clipboard Handling
# -------------------------------------------------------------------
if [ "$COPY" = true ] && [ "$VERIFY" = false ] && [ -n "$FIRST_HASH" ]; then
    if command -v wl-copy &>/dev/null; then
        echo -n "$FIRST_HASH" | wl-copy
        [ "$QUIET" = false ] && log_success "Hash copied to clipboard (Wayland)."
    elif command -v xclip &>/dev/null; then
        echo -n "$FIRST_HASH" | xclip -selection clipboard
        [ "$QUIET" = false ] && log_success "Hash copied to clipboard (X11)."
    else
        log_warn "No clipboard tool found (install wl-clipboard or xclip)." >&2
    fi
fi

# GUI Notification
if [ "$GUI" = true ] && [ "$VERIFY" = false ] && [ "$QUIET" = false ]; then
    if [ "$ERROR_OCCURRED" = true ]; then
        [ "$GUI_TOOL" = "kdialog" ] && kdialog --error "⚠ Errors occurred while generating checksums."
        [ "$GUI_TOOL" = "zenity" ] && zenity --error --text="⚠ Errors occurred while generating checksums."
    else
        [ "$GUI_TOOL" = "kdialog" ] && kdialog --msgbox "✅ Checksums generated successfully."
        [ "$GUI_TOOL" = "zenity" ] && zenity --info --text="✅ Checksums generated successfully."
    fi
fi

if [ "$ERROR_OCCURRED" = true ]; then
    exit 1
fi
