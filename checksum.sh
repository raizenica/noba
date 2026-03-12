#!/bin/bash
# Generate or verify checksums – CLI and GUI modes

# Defaults
ALGO="sha256"
VERIFY=false
RECURSIVE=false
OUTPUT="plain"  # plain, csv, json
COPY=false

# Function to show usage
usage() {
    cat <<EOF
Usage: $0 [options] [files...]

Options:
  -a, --algo ALGO     Hash algorithm: md5, sha1, sha256 (default: sha256)
  -v, --verify        Verify checksums from .sha256 files (or specify algo)
  -r, --recursive     Process directories recursively
  -o, --output FORMAT Output format: plain, csv, json (default: plain)
  -c, --copy          Copy hash to clipboard (X11/Wayland)
  --help              Show this help

If no files are given and no options, runs in GUI mode.
EOF
    exit 0
}

# Parse arguments
USE_GUI=true
FILES=()
while [[ $# -gt 0 ]]; do
    case $1 in
        -a|--algo)
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
        -o|--output)
            OUTPUT="$2"
            shift 2
            ;;
        -c|--copy)
            COPY=true
            shift
            ;;
        --help)
            usage
            ;;
        -*)
            echo "Unknown option: $1"
            usage
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

# Map algorithm to command
case $ALGO in
    md5|MD5)    cmd="md5sum" ;;
    sha1|SHA1)  cmd="sha1sum" ;;
    sha256|SHA256) cmd="sha256sum" ;;
    *) echo "Unsupported algorithm: $ALGO"; exit 1 ;;
esac

# GUI mode
if $USE_GUI; then
    type=$(kdialog --combobox "Select checksum type:" "MD5" "SHA1" "SHA256" --default "SHA256")
    [ -z "$type" ] && exit 1
    case $type in
        MD5)    cmd="md5sum" ;;
        SHA1)   cmd="sha1sum" ;;
        SHA256) cmd="sha256sum" ;;
    esac
    # Get selected files from Dolphin (passed as arguments)
    FILES=("$@")
fi

# Function to process a single file (generate or verify)
process_file() {
    local file="$1"
    if $VERIFY; then
        # Verify checksum
        if [[ "$file" == *.md5 || "$file" == *.sha1 || "$file" == *.sha256 ]]; then
            echo "Verifying $file..."
            $cmd -c "$file"
        else
            echo "Skipping $file (not a checksum file)"
        fi
    else
        # Generate checksum
        if [ -f "$file" ]; then
            $cmd "$file" >> "${file}.${ALGO}.txt"
            echo "Generated ${ALGO} for $file"
        elif [ -d "$file" ] && $RECURSIVE; then
            find "$file" -type f -print0 | while IFS= read -r -d '' f; do
                $cmd "$f" >> "${file}.${ALGO}.txt"
            done
        fi
    fi
}

# Main processing
for file in "${FILES[@]}"; do
    process_file "$file"
done

# If copy to clipboard requested and only one file processed
if $COPY && [ ${#FILES[@]} -eq 1 ] && ! $VERIFY; then
    hash=$(tail -1 "${FILES[0]}.${ALGO}.txt" | cut -d' ' -f1)
    if command -v wl-copy &>/dev/null; then
        echo -n "$hash" | wl-copy
    elif command -v xclip &>/dev/null; then
        echo -n "$hash" | xclip -selection clipboard
    else
        echo "Clipboard tool not found"
    fi
fi

# GUI completion notification
if $USE_GUI && ! $VERIFY; then
    kdialog --msgbox "✅ ${ALGO} checksums saved to .txt files"
fi
