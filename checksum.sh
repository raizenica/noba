
# Help handling

# Help handling

# Help handling

# Help handling

# Help handling

# Help handling

# Help handling
if [ "$1" = "--help" ] || [ "$1" = "-h" ]; then
    echo "Usage: $(basename "$0") [OPTIONS]"
    echo "For detailed help, see the script documentation."
    exit 0
fi
if [ "$1" = "--version" ] || [ "$1" = "-v" ]; then
    echo "$(basename "$0") version 1.0"
    exit 0
fi

if [ "$1" = "--help" ] || [ "$1" = "-h" ]; then
    echo "Usage: $(basename "$0") [OPTIONS]"
    echo "For detailed help, see the script documentation."
    exit 0
fi
if [ "$1" = "--version" ] || [ "$1" = "-v" ]; then
    echo "$(basename "$0") version 1.0"
    exit 0
fi

if [ "$1" = "--help" ] || [ "$1" = "-h" ]; then
    echo "Usage: $(basename "$0") [OPTIONS]"
    echo "For detailed help, see the script documentation."
    exit 0
fi
if [ "$1" = "--version" ] || [ "$1" = "-v" ]; then
    echo "$(basename "$0") version 1.0"
    exit 0
fi

if [ "$1" = "--help" ] || [ "$1" = "-h" ]; then
    echo "Usage: $(basename "$0") [OPTIONS]"
    echo "For detailed help, see the script documentation."
    exit 0
fi
if [ "$1" = "--version" ] || [ "$1" = "-v" ]; then
    echo "$(basename "$0") version 1.0"
    exit 0
fi

if [ "$1" = "--help" ] || [ "$1" = "-h" ]; then
    echo "Usage: $(basename "$0") [OPTIONS]"
    echo "For detailed help, see the script documentation."
    exit 0
fi
if [ "$1" = "--version" ] || [ "$1" = "-v" ]; then
    echo "$(basename "$0") version 1.0"
    exit 0
fi

if [ "$1" = "--help" ] || [ "$1" = "-h" ]; then
    echo "Usage: $(basename "$0") [OPTIONS]"
    echo "For detailed help, see the script documentation."
    exit 0
fi
if [ "$1" = "--version" ] || [ "$1" = "-v" ]; then
    echo "$(basename "$0") version 1.0"
    exit 0
fi

if [ "$1" = "--help" ] || [ "$1" = "-h" ]; then
    echo "Usage: $(basename "$0") [OPTIONS]"
    echo "For detailed help, see the script documentation."
    exit 0
fi
if [ "$1" = "--version" ] || [ "$1" = "-v" ]; then
    echo "$(basename "$0") version 1.0"
    exit 0
fi

#!/bin/bash
SCRIPT_DIR="$(cd "$(dirname "${BASH_SOURCE[0]}")" && pwd)"
source "$SCRIPT_DIR/noba-lib.sh"
# checksum.sh – Generate or verify checksums with multiple algorithms, recursive manifests, and progress

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
shopt -s nullglob

# -------------------------------------------------------------------
# Configuration and defaults
# -------------------------------------------------------------------

# Source central config if available
# shellcheck source=/dev/null
if [ -f "$HOME/.config/automation.conf" ]; then
fi

# Defaults
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
MANIFEST_NAME=""           # if empty, auto-generate

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
Usage: $0 [options] [files...]

Generate or verify checksums for files and directories.

Options:
  -a, --algo ALGO       Hash algorithm: md5, sha1, sha256, sha512, blake2b, crc32 (default: sha256)
  -v, --verify          Verify checksums from .sha256 files (or matching algo)
  -r, --recursive       Process directories recursively
  -m, --manifest        Generate a single manifest file (all checksums in one file)
  -p, --progress        Show progress (file count)
  -o, --output FORMAT   Output format: plain, csv, json (default: plain)
  -c, --copy            Copy the first hash to clipboard (X11/Wayland)
  -q, --quiet           Suppress non‑error output
  --gui                 Launch GUI file picker (requires kdialog)
  --follow-symlinks     Follow symbolic links when recursing
  --no-hidden           Exclude hidden files (those starting with .)
  --manifest-name NAME  Custom name for manifest file (ignored without --manifest)
  --help                Show this help
  --version             Show version information

If no files are given and --gui is used, a file picker appears.
Otherwise, reads from stdin (one file per line) if no files and not GUI.
EOF
    exit 0
}

# Map algorithm to command
algo_to_cmd() {
    case "${1,,}" in        # lowercase
        md5)        echo "md5sum" ;;
        sha1)       echo "sha1sum" ;;
        sha256)     echo "sha256sum" ;;
        sha512)     echo "sha512sum" ;;
        blake2b)    echo "b2sum" ;;
        crc32)      echo "cksum" ;;
        *)          echo "unsupported" ;;
    esac
}

# Map algorithm to typical file extension
algo_to_ext() {
    case "${1,,}" in
        md5)        echo "md5" ;;
        sha1)       echo "sha1" ;;
        sha256)     echo "sha256" ;;
        sha512)     echo "sha512" ;;
        blake2b)    echo "b2" ;;
        crc32)      echo "crc" ;;
        *)          echo "txt" ;;
    esac
}

# Check required commands
check_deps() {
    local missing=()
    for cmd in find sort wc mktemp dirname cut printf; do
        if ! command -v "$cmd" &>/dev/null; then
            missing+=("$cmd")
        fi
    done
    # Checksum command will be checked later based on selected algorithm
    if [ ${#missing[@]} -gt 0 ]; then
        echo "ERROR: Missing required commands: ${missing[*]}" >&2
        exit 1
    fi
}

# Logging (quiet‑aware)
log() {
    if [ "$QUIET" = false ]; then
        echo "$@"
    fi
}

# shellcheck disable=SC2329
vlog() {
    if [ "$VERBOSE" = true ] && [ "$QUIET" = false ]; then
        echo "[VERBOSE]" "$@"
    fi
}

# Progress display (simple file counter)
progress_start() {
    if [ "$PROGRESS" = true ] && [ "$QUIET" = false ] && [ "$TOTAL_FILES" -gt 0 ]; then
        CURRENT_FILE=0
    fi
}

progress_tick() {
    if [ "$PROGRESS" = true ] && [ "$QUIET" = false ] && [ "$TOTAL_FILES" -gt 0 ]; then
        ((CURRENT_FILE++))
        printf "\rProgress: %d/%d (%d%%)" "$CURRENT_FILE" "$TOTAL_FILES" $((CURRENT_FILE * 100 / TOTAL_FILES)) >&2
    fi
}

progress_end() {
    if [ "$PROGRESS" = true ] && [ "$QUIET" = false ] && [ "$TOTAL_FILES" -gt 0 ]; then
        echo >&2   # newline
    fi
}

# Generate checksum for a single file
generate_one() {
    local file="$1"
    local cmd="$2"
    if [ ! -f "$file" ]; then
        echo "WARNING: '$file' is not a regular file, skipping." >&2
        return 1
    fi
    "$cmd" "$file" 2>/dev/null
}

# Verify a single checksum file (or a file containing checksums)
verify_one() {
    local file="$1"
    local cmd="$2"
    if [ ! -f "$file" ]; then
        echo "WARNING: '$file' not found, skipping." >&2
        return 1
    fi
    if [[ "$file" == *.md5 || "$file" == *.sha1 || "$file" == *.sha256 || "$file" == *.sha512 || "$file" == *.b2 || "$file" == *.crc ]]; then
        "$cmd" -c "$file" 2>/dev/null
    else
        echo "WARNING: '$file' is not a recognized checksum file, skipping." >&2
        return 1
    fi
}

# Format output line according to selected format
format_output() {
    local algo="$1"
    local hash="$2"
    local filename="$3"
    case "$OUTPUT_FORMAT" in
        csv)
            printf '"%s","%s","%s"\n' "$algo" "$hash" "$filename"
            ;;
        json)
            printf '{"algorithm":"%s","hash":"%s","file":"%s"}\n' "$algo" "$hash" "$filename"
            ;;
        plain|*)
            printf '%s  %s\n' "$hash" "$filename"
            ;;
    esac
}

# Collect files from command line or stdin
collect_files() {
    local files=()
    if [ ${#FILES[@]} -gt 0 ]; then
        files=("${FILES[@]}")
    elif [ ! -t 0 ]; then
        # Read from stdin
        while IFS= read -r line; do
            files+=("$line")
        done
    fi
    printf '%s\n' "${files[@]}"
}

# -------------------------------------------------------------------
# Parse command-line arguments
# -------------------------------------------------------------------
FILES=()
while [[ $# -gt 0 ]]; do
    case $1 in
        -a|--algo)
            ALGO="${2,,}"
            shift 2
            ;;
        -v|--verify)
            VERIFY=true
            shift
            ;;
        -r|--recursive)
            RECURSIVE=true
            shift
            ;;
        -m|--manifest)
            MANIFEST=true
            shift
            ;;
        -p|--progress)
            PROGRESS=true
            shift
            ;;
        -o|--output)
            OUTPUT_FORMAT="$2"
            shift 2
            ;;
        -c|--copy)
            COPY=true
            shift
            ;;
        -q|--quiet)
            QUIET=true
            shift
            ;;
        --gui)
            GUI=true
            shift
            ;;
        --follow-symlinks)
            FOLLOW_SYMLINKS=true
            shift
            ;;
        --no-hidden)
            INCLUDE_HIDDEN=false
            shift
            ;;
        --manifest-name)
            MANIFEST_NAME="$2"
            shift 2
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
        -*)
            echo "Unknown option: $1" >&2
            exit 1
            ;;
        *)
            FILES+=("$1")
            shift
            ;;
    esac
done

# -------------------------------------------------------------------
# Pre-flight checks
# -------------------------------------------------------------------
check_deps

# Validate algorithm and command
CMD=$(algo_to_cmd "$ALGO")
if [ "$CMD" = "unsupported" ]; then
    echo "ERROR: Unsupported algorithm '$ALGO'." >&2
    exit 1
fi
if ! command -v "$CMD" &>/dev/null; then
    echo "ERROR: Command '$CMD' not available for algorithm '$ALGO'." >&2
    exit 1
fi

# Validate output format
if [[ ! "$OUTPUT_FORMAT" =~ ^(plain|csv|json)$ ]]; then
    echo "ERROR: Invalid output format '$OUTPUT_FORMAT'. Use plain, csv, or json." >&2
    exit 1
fi

# Handle GUI mode
if [ "$GUI" = true ]; then
    if ! command -v kdialog &>/dev/null; then
        echo "ERROR: kdialog not available for GUI mode." >&2
        exit 1
    fi
    # If no files provided, launch file picker
    if [ ${#FILES[@]} -eq 0 ]; then
        # Ask for files/directories (multi-select)
        # shellcheck disable=SC2207
        IFS=$'\n' read -d '' -r -a FILES < <(kdialog --getopenfilename --multiple --separate-output "$HOME" "All Files (*)" 2>/dev/null)
        if [ ${#FILES[@]} -eq 0 ]; then
            kdialog --error "No files selected."
            exit 1
        fi
    fi
fi

# If no files and not reading from stdin, error
if [ ${#FILES[@]} -eq 0 ] && [ -t 0 ]; then
    echo "ERROR: No files specified and no input from stdin." >&2
# shellcheck disable=SC2317
    usage
# shellcheck disable=SC2317
    exit 1
fi

# -------------------------------------------------------------------
# Main processing
# -------------------------------------------------------------------
ERROR_OCCURRED=false
TOTAL_FILES=0
CURRENT_FILE=0

# Temporary file to collect error status across subshells
ERROR_FLAG=$(mktemp)
echo 0 > "$ERROR_FLAG"
trap 'rm -f "$ERROR_FLAG"' EXIT

# Function to mark error
mark_error() {
    echo 1 > "$ERROR_FLAG"
}

# Prepare manifest file if requested
MANIFEST_FILE=""
if [ "$MANIFEST" = true ] && [ "$VERIFY" = false ]; then
    if [ -n "$MANIFEST_NAME" ]; then
        MANIFEST_FILE="$MANIFEST_NAME"
    else
        # Use first file's base name, or fallback to "checksums"
        if [ ${#FILES[@]} -gt 0 ]; then
            base="${FILES[0]%.*}"
            MANIFEST_FILE="${base}.$(algo_to_ext "$ALGO").txt"
        else
            MANIFEST_FILE="checksums.$(algo_to_ext "$ALGO").txt"
        fi
    fi
    # Clear or create the manifest file
    : > "$MANIFEST_FILE"
    log "Manifest: $MANIFEST_FILE"
fi

# Function to write output (to manifest or individual files)
write_hash() {
    local hash_line="$1"
    if [ "$MANIFEST" = true ] && [ -n "$MANIFEST_FILE" ]; then
        echo "$hash_line" >> "$MANIFEST_FILE"
    else
        # Write to individual file: filename.ALGO.txt
        local file
        file=$(echo "$hash_line" | awk '{print $2}')
        echo "$hash_line" >> "${file}.$(algo_to_ext "$ALGO").txt"
    fi
}

# Count total files for progress (only in generate mode)
if [ "$PROGRESS" = true ] && [ "$VERIFY" = false ]; then
    while IFS= read -r item; do
        if [ -d "$item" ] && [ "$RECURSIVE" = true ]; then
            find_args=()
            [ "$FOLLOW_SYMLINKS" = true ] && find_args+=(-L)
            [ "$INCLUDE_HIDDEN" = false ] && find_args+=(! -name ".*")
            TOTAL_FILES=$((TOTAL_FILES + $(find "${find_args[@]}" "$item" -type f | wc -l)))
        elif [ -f "$item" ]; then
            TOTAL_FILES=$((TOTAL_FILES + 1))
        fi
    done < <(collect_files)
fi

progress_start

# Main loop over input items
while IFS= read -r item; do
    # Expand directories if recursive
    if [ -d "$item" ] && [ "$RECURSIVE" = true ]; then
        find_args=()
        [ "$FOLLOW_SYMLINKS" = true ] && find_args+=(-L)
        [ "$INCLUDE_HIDDEN" = false ] && find_args+=(! -name ".*")
        # Use process substitution to avoid subshell issues
        while IFS= read -r -d '' file; do
            if [ "$VERIFY" = true ]; then
                # For directories, we assume checksum files inside; but we'd need to find them.
                # Simplified: just process each checksum file if it matches the pattern.
                if [[ "$file" == *.md5 || "$file" == *.sha1 || "$file" == *.sha256 || "$file" == *.sha512 || "$file" == *.b2 || "$file" == *.crc ]]; then
                    if ! verify_one "$file" "$CMD"; then
                        mark_error
                    fi
                fi
            else
                progress_tick
                if generate_one "$file" "$CMD" | while IFS= read -r line; do
                    formatted=$(format_output "$ALGO" "${line%% *}" "${line#*  }")
                    write_hash "$formatted"
                done; then
                    :   # success
                else
                    mark_error
                fi
            fi
        done < <(find "${find_args[@]}" "$item" -type f -print0)
    elif [ -f "$item" ]; then
        progress_tick
        if [ "$VERIFY" = true ]; then
            if ! verify_one "$item" "$CMD"; then
                mark_error
            fi
        else
            if generate_one "$item" "$CMD" | while IFS= read -r line; do
            if [ $? -ne 0 ]; then mark_error; fi
            if [ $? -ne 0 ]; then mark_error; fi
            if [ $? -ne 0 ]; then mark_error; fi
            if [ $? -ne 0 ]; then mark_error; fi
            if [ $? -ne 0 ]; then mark_error; fi
                formatted=$(format_output "$ALGO" "${line%% *}" "${line#*  }")
                write_hash "$formatted"
            done; then
                :   # success
            else
                mark_error
            fi
        fi
    else
        echo "WARNING: '$item' is not a file or directory, skipping." >&2
    fi
done < <(collect_files)

progress_end

# Check error flag
ERROR_OCCURRED=$(<"$ERROR_FLAG")

# Copy first hash to clipboard if requested (only in generate mode and not verify)
if [ "$COPY" = true ] && [ "$VERIFY" = false ] && [ ${#FILES[@]} -gt 0 ]; then
    # Determine where the hash is stored
    hash_file=""
    if [ "$MANIFEST" = true ] && [ -n "$MANIFEST_FILE" ]; then
        hash_file="$MANIFEST_FILE"
    else
        hash_file="${FILES[0]}.$(algo_to_ext "$ALGO").txt"
    fi
    if [ -f "$hash_file" ]; then
        hash=$(head -1 "$hash_file" | cut -d' ' -f1)
        if command -v wl-copy &>/dev/null; then
            echo -n "$hash" | wl-copy
            log "Hash copied to clipboard (Wayland)."
        elif command -v xclip &>/dev/null; then
            echo -n "$hash" | xclip -selection clipboard
            log "Hash copied to clipboard (X11)."
        else
            echo "WARNING: No clipboard tool found (install wl-clipboard or xclip)." >&2
        fi
    else
        echo "WARNING: Hash file not found, cannot copy to clipboard." >&2
    fi
fi

# GUI completion notification
if [ "$GUI" = true ] && [ "$VERIFY" = false ]; then
    if [ "$ERROR_OCCURRED" = 1 ]; then
        kdialog --error "⚠ Some errors occurred while generating checksums."
    else
        kdialog --msgbox "✅ Checksums generated successfully."
    fi
fi

# Exit with appropriate code
exit "$ERROR_OCCURRED"
