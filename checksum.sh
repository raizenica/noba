#!/bin/bash
# Generate or verify checksums – with multiple algorithms, directory manifests, and progress

set -u
set -o pipefail

# Defaults
ALGO="sha256"
VERIFY=false
RECURSIVE=false
OUTPUT="plain"  # plain, csv, json (not fully implemented yet)
COPY=false
MANIFEST=false  # generate a single manifest file for all processed files
PROGRESS=false  # show progress (requires `pv` or simple counter)
QUIET=false

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
        crc32|CRC32)    echo "cksum" ;;   # crc32 is not standard; cksum gives CRC-32 but different output format
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
    # Check if file is a valid checksum file
    if [[ "$file" == *.md5 || "$file" == *.sha1 || "$file" == *.sha256 || "$file" == *.sha512 || "$file" == *.b2 || "$file" == *.crc ]]; then
        "$cmd" -c "$file"
    else
        echo "Skipping '$file' (not a recognized checksum file)." >&2
        return 1
    fi
}

# Generate a manifest (all checksums in one file)
generate_manifest() {
    local manifest="$1"
    shift
    local files=("$@")
    local cmd="$2"  # need to restructure; better to pass cmd separately
    # This is a placeholder; actual implementation will use find or loops
    echo "Manifest generation not fully implemented yet." >&2
    return 1
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
    # If still no files, error
    if [ ${#FILES[@]} -eq 0 ]; then
        kdialog --error "No files selected."
        exit 1
    fi
fi

# Check for required tools for certain features
if $PROGRESS && ! command -v pv &>/dev/null; then
    echo "Warning: pv not installed; progress will be estimated with simple counter." >&2
    PROGRESS=false  # fallback to simple counter
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
    # For manifest, we need an output file name. Use first file's name with appropriate extension.
    base="${FILES[0]%.*}"
    MANIFEST_FILE="${base}.${ALGO}.txt"
    echo "Generating manifest: $MANIFEST_FILE"
    # Overwrite or append? We'll overwrite.
    : > "$MANIFEST_FILE"
fi

# Function to output (either to manifest or individual files)
output_hash() {
    local hash_line="$1"
    if $MANIFEST && [ -n "$MANIFEST_FILE" ]; then
        echo "$hash_line" >> "$MANIFEST_FILE"
    else
        # In non-manifest mode, hash_line includes filename, but we need to redirect to individual file.
        # The line is like "hash  filename". We'll extract filename and write to that file with .algo.txt.
        local hash_file
        hash_file=$(echo "$hash_line" | awk '{print $2}')
        echo "$hash_line" >> "${hash_file}.${ALGO}.txt"
    fi
}

# Process each file or directory
for item in "${FILES[@]}"; do
    if [ -f "$item" ]; then
        if $VERIFY; then
            if ! verify_one "$item" "$CMD"; then
                ERROR_OCCURRED=true
            fi
        else
            # Generate
            if $PROGRESS; then
                # Use pv to show progress for the file (if it's large)
                if command -v pv &>/dev/null; then
                    pv "$item" | "$CMD" | while read -r line; do
                        output_hash "$line"
                    done
                else
                    # fallback: simple counter (not very useful)
                    echo "Processing $item..." >&2
                    generate_one "$item" "$CMD" | while read -r line; do
                        output_hash "$line"
                    done
                fi
            else
                generate_one "$item" "$CMD" | while read -r line; do
                    output_hash "$line"
                done
            fi
            if [ $? -ne 0 ]; then
                ERROR_OCCURRED=true
            fi
        fi
    elif [ -d "$item" ] && $RECURSIVE; then
        if $VERIFY; then
            echo "Verification for directories not yet implemented." >&2
            ERROR_OCCURRED=true
            continue
        fi
        # Generate checksums for all files in directory recursively
        if $MANIFEST; then
            # If manifest, we'll collect all output in one file
            echo "Processing directory $item recursively..." >&2
            find "$item" -type f -print0 | while IFS= read -r -d '' file; do
                generate_one "$file" "$CMD" | while read -r line; do
                    output_hash "$line"
                done
                if [ $? -ne 0 ]; then
                    ERROR_OCCURRED=true
                fi
            done
        else
            # Generate individual .algo.txt files for each file in the directory
            echo "Processing directory $item recursively (individual files)..." >&2
            find "$item" -type f -print0 | while IFS= read -r -d '' file; do
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

# If manifest mode, print the manifest filename
if $MANIFEST && [ -n "$MANIFEST_FILE" ]; then
    echo "Manifest saved to: $MANIFEST_FILE"
fi

# Copy to clipboard if requested and exactly one hash generated (non-verify)
if $COPY && ! $VERIFY && [ ${#FILES[@]} -eq 1 ]; then
    # Get the last generated hash (simplistic: read from the output file)
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
