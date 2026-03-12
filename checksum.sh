#!/bin/bash
# Generate or verify checksums – with multiple algorithms, directory manifests, and progress

set -u
set -o pipefail

# Source central config if available (optional, can be used for future settings)
if [ -f "$HOME/.config/automation.conf" ]; then
    source "$HOME/.config/automation.conf"
fi

# Defaults
ALGO="sha256"
VERIFY=false
RECURSIVE=false
OUTPUT="plain"  # plain, csv, json (not fully implemented yet)
COPY=false
MANIFEST=false  # generate a single manifest file for all processed files
PROGRESS=false  # show progress (requires `pv` or simple counter)
QUIET=false

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

# Function to show usage
usage() {
    cat <<EOF
Usage: $0 [options] [files...]

Options:
  -a, --algo ALGO     Hash algorithm: md5, sha1, sha256, sha512, blake2b, crc32 (default: sha256)
  -v, --verify        Verify checksums from .sha256 files (or match algo)
  -r, --recursive     Process directories recursively
  -m, --manifest      Generate a single manifest file (all checksums in one file)
  -p, --progress      Show progress (requires pv for large operations)
  -o, --output FORMAT Output format: plain, csv, json (default: plain)
  -c, --copy          Copy hash to clipboard (X11/Wayland)
  -q, --quiet         Suppress non‑error output
  --help              Show this help
  --version           Show version information

If no files are given and no options, runs in GUI mode.
EOF
    exit 0
}

# Map algorithm to command
algo_to_cmd() {
    case "$1" in
        md5|MD5)        echo "md5sum" ;;
        sha1|SHA1)      echo "sha1sum" ;;
        sha256|SHA256)  echo "sha256sum" ;;
        sha512|SHA512)  echo "sha512sum" ;;
        blake2b|BLAKE2) echo "b2sum" ;;
        crc32|CRC32)    echo "cksum" ;;
        *)              echo "unsupported" ;;
    esac
}

# Generate checksum for a single file
generate_one() {
    local file="$1"
    local cmd="$2"
    if [ ! -f "$file" ]; then
        echo "Warning: '$file' not a regular file, skipping." >&2
        return 1
    fi
    "$cmd" "$file"
}

# Verify a single checksum file
verify_one() {
    local file="$1"
    local cmd="$2"
    if [ ! -f "$file" ]; then
        echo "Warning: '$file' not found, skipping." >&2
        return 1
    fi
    if [[ "$file" == *.md5 || "$file" == *.sha1 || "$file" == *.sha256 || "$file" == *.sha512 || "$file" == *.b2 || "$file" == *.crc ]]; then
        "$cmd" -c "$file"
    else
        echo "Skipping '$file' (not a recognized checksum file)." >&2
        return 1
    fi
}

# Progress display function
show_progress() {
    local current="$1"
    local total="$2"
    local msg="$3"
    if $PROGRESS && [ "$QUIET" = false ]; then
        if command -v pv &>/dev/null && [ "$total" -gt 0 ]; then
            printf "\r%s: %d/%d (%d%%)" "$msg" "$current" "$total" $((current * 100 / total)) >&2
        else
            printf "\r%s: %d/%d" "$msg" "$current" "$total" >&2
        fi
    fi
}

# Parse arguments
USE_GUI=true
FILES=()
while [[ $# -gt 0 ]]; do
    case $1 in
        -a|--algo)
            if [[ -z $2 ]]; then
                echo "Error: --algo requires an argument" >&2
                exit 1
            fi
            ALGO="$2"
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
            if [[ -z $2 ]]; then
                echo "Error: --output requires an argument" >&2
                exit 1
            fi
            # shellcheck disable=SC2034
            OUTPUT="$2"
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

# If files provided, disable GUI
if [ ${#FILES[@]} -gt 0 ]; then
    USE_GUI=false
fi

# Determine command
CMD=$(algo_to_cmd "$ALGO")
if [ "$CMD" = "unsupported" ]; then
    echo "Error: Unsupported algorithm '$ALGO'. Use md5, sha1, sha256, sha512, blake2b, or crc32." >&2
    exit 1
fi

# GUI mode
if $USE_GUI; then
    if ! command -v kdialog &>/dev/null; then
        echo "Error: kdialog not available for GUI mode." >&2
        exit 1
    fi
    type=$(kdialog --combobox "Select checksum type:" "MD5" "SHA1" "SHA256" "SHA512" "BLAKE2" "CRC32" --default "SHA256")
    [ -z "$type" ] && exit 1
    case $type in
        MD5)    CMD="md5sum" ;;
        SHA1)   CMD="sha1sum" ;;
        SHA256) CMD="sha256sum" ;;
        SHA512) CMD="sha512sum" ;;
        BLAKE2) CMD="b2sum" ;;
        CRC32)  CMD="cksum" ;;
    esac
    # Get selected files from Dolphin (passed as arguments)
    FILES=("$@")
    if [ ${#FILES[@]} -eq 0 ]; then
        kdialog --error "No files selected."
        exit 1
    fi
fi

# If verifying, ensure we have files
if $VERIFY && [ ${#FILES[@]} -eq 0 ]; then
    echo "Error: No files specified for verification." >&2
    exit 1
fi

# Process files
ERROR_OCCURRED=false
MANIFEST_FILE=""
if $MANIFEST && [ ${#FILES[@]} -gt 1 ]; then
    base="${FILES[0]%.*}"
    MANIFEST_FILE="${base}.${ALGO}.txt"
    echo "Generating manifest: $MANIFEST_FILE"
    : > "$MANIFEST_FILE"
fi

# Function to output (either to manifest or individual files)
output_hash() {
    local hash_line="$1"
    if $MANIFEST && [ -n "$MANIFEST_FILE" ]; then
        echo "$hash_line" >> "$MANIFEST_FILE"
    else
        local hash_file
        hash_file=$(echo "$hash_line" | awk '{print $2}')
        echo "$hash_line" >> "${hash_file}.${ALGO}.txt"
    fi
}

# Count total files for progress (if recursive and directories)
TOTAL_FILES=0
if $PROGRESS && ! $VERIFY; then
    for item in "${FILES[@]}"; do
        if [ -d "$item" ] && $RECURSIVE; then
            TOTAL_FILES=$((TOTAL_FILES + $(find "$item" -type f | wc -l)))
        elif [ -f "$item" ]; then
            TOTAL_FILES=$((TOTAL_FILES + 1))
        fi
    done
fi

CURRENT_FILE=0
for item in "${FILES[@]}"; do
    if [ -f "$item" ]; then
        if $VERIFY; then
            if ! verify_one "$item" "$CMD"; then
                ERROR_OCCURRED=true
            fi
        else
            # Generate
            if $PROGRESS; then
                CURRENT_FILE=$((CURRENT_FILE + 1))
                show_progress "$CURRENT_FILE" "$TOTAL_FILES" "Processing files"
            fi
            if ! generate_one "$item" "$CMD" | while read -r line; do
                output_hash "$line"
            done; then
                ERROR_OCCURRED=true
            fi
        fi
    elif [ -d "$item" ] && $RECURSIVE; then
        if $VERIFY; then
            echo "Verification for directories not yet implemented." >&2
            ERROR_OCCURRED=true
            continue
        fi
        # Find all files recursively
        if $MANIFEST; then
            # Collect in manifest
            find "$item" -type f -print0 | while IFS= read -r -d '' file; do
                if $PROGRESS; then
                    CURRENT_FILE=$((CURRENT_FILE + 1))
                    show_progress "$CURRENT_FILE" "$TOTAL_FILES" "Processing files"
                fi
                generate_one "$file" "$CMD" | while read -r line; do
                    output_hash "$line"
                done
                if [ $? -ne 0 ]; then
                    ERROR_OCCURRED=true
                fi
            done
        else
            # Individual files
            find "$item" -type f -print0 | while IFS= read -r -d '' file; do
                if $PROGRESS; then
                    CURRENT_FILE=$((CURRENT_FILE + 1))
                    show_progress "$CURRENT_FILE" "$TOTAL_FILES" "Processing files"
                fi
                generate_one "$file" "$CMD" | while read -r line; do
                    output_hash "$line"
                done
                if [ $? -ne 0 ]; then
                    ERROR_OCCURRED=true
                fi
            done
        fi
    else
        echo "Warning: '$item' is not a file or directory (or recursive not enabled), skipping." >&2
    fi
done

# Newline after progress output
if $PROGRESS && ! $VERIFY && [ "$QUIET" = false ]; then
    echo >&2
fi

# If manifest mode, print the manifest filename
if $MANIFEST && [ -n "$MANIFEST_FILE" ]; then
    echo "Manifest saved to: $MANIFEST_FILE"
fi

# Copy to clipboard if requested and exactly one hash generated (non-verify)
if $COPY && ! $VERIFY && [ ${#FILES[@]} -eq 1 ]; then
    if $MANIFEST && [ -n "$MANIFEST_FILE" ]; then
        hash=$(tail -1 "$MANIFEST_FILE" | cut -d' ' -f1)
    else
        hash=$(tail -1 "${FILES[0]}.${ALGO}.txt" | cut -d' ' -f1)
    fi
    if command -v wl-copy &>/dev/null; then
        echo -n "$hash" | wl-copy
    elif command -v xclip &>/dev/null; then
        echo -n "$hash" | xclip -selection clipboard
    else
        echo "Clipboard tool not found." >&2
    fi
fi

# GUI completion notification
if $USE_GUI && ! $VERIFY; then
    if $ERROR_OCCURRED; then
        kdialog --error "⚠️ Some errors occurred while generating checksums."
    else
        kdialog --msgbox "✅ Checksums generated successfully."
    fi
fi

# Exit with appropriate code
if $ERROR_OCCURRED; then
    exit 1
else
    exit 0
fi
