#!/bin/bash
# images-to-pdf.sh – Convert images to PDF (CLI and GUI modes)

set -u
set -o pipefail

SCRIPT_DIR="$(cd "$(dirname "${BASH_SOURCE[0]}")" && pwd)"
source "$SCRIPT_DIR/noba-lib.sh"

# -------------------------------------------------------------------
# Configuration and defaults
# -------------------------------------------------------------------

DEFAULT_PAPER_SIZE="A4"
DEFAULT_ORIENTATION="portrait"
DEFAULT_QUALITY=92

# Initialize
OUTPUT_FILE=""
PAPER_SIZE="$DEFAULT_PAPER_SIZE"
ORIENTATION="$DEFAULT_ORIENTATION"
QUALITY="$DEFAULT_QUALITY"
METADATA=""
PROGRESS=false
VERBOSE=false
USE_GUI=false

# Load config
load_config
if [ "$CONFIG_LOADED" = true ]; then
    PAPER_SIZE=$(get_config '.images2pdf.default_paper_size' "$PAPER_SIZE")
    ORIENTATION=$(get_config '.images2pdf.default_orientation' "$ORIENTATION")
    QUALITY=$(get_config '.images2pdf.default_quality' "$QUALITY")
fi

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
Usage: $0 [options] image1 [image2 ...]

Convert one or more images to a single PDF.

Options:
  -o, --output FILE     Output PDF filename (required in CLI mode if more than one image)
  -s, --paper-size SIZE Paper size: A4, Letter, Legal, etc. (default: $DEFAULT_PAPER_SIZE)
  -r, --orientation DIR Orientation: portrait or landscape (default: $DEFAULT_ORIENTATION)
  -q, --quality PERCENT JPEG compression quality (1-100, default: $DEFAULT_QUALITY)
  -m, --metadata STR    Add PDF metadata (e.g., "title=My PDF,author=Me")
  -p, --progress        Show progress for many images (uses ImageMagick's -progress)
  -v, --verbose         Print ImageMagick commands and details
  --help                Show this help
  --version             Show version information

If no arguments are given and kdialog is installed, launches a GUI file picker.
EOF
    exit 0
}

check_deps() {
    if ! command -v convert &>/dev/null; then
        log_error "ImageMagick 'convert' not found. Please install ImageMagick."
        exit 1
    fi
}

# -------------------------------------------------------------------
# Parse command-line arguments
# -------------------------------------------------------------------

# Variables
OUTPUT_FILE=""
PAPER_SIZE="$DEFAULT_PAPER_SIZE"
ORIENTATION="$DEFAULT_ORIENTATION"
QUALITY="$DEFAULT_QUALITY"
METADATA=""
PROGRESS=false
VERBOSE=false
USE_GUI=false

# If no arguments, try GUI mode
if [ $# -eq 0 ]; then
    if command -v kdialog &>/dev/null; then
        USE_GUI=true
    else
        echo "ERROR: No input files and kdialog not available." >&2
        exit 1
    fi
else
    # Parse options with getopt
    if ! OPTIONS=$(getopt -o o:s:r:q:m:pvh -l output:,paper-size:,orientation:,quality:,metadata:,progress,verbose,help,version -- "$@"); then
        usage
    fi
    eval set -- "$OPTIONS"

    while true; do
        case "$1" in
            -o|--output)
                OUTPUT_FILE="$2"
                shift 2
                ;;
            -s|--paper-size)
                PAPER_SIZE="$2"
                shift 2
                ;;
            -r|--orientation)
                ORIENTATION="$2"
                shift 2
                ;;
            -q|--quality)
                QUALITY="$2"
                shift 2
                ;;
            -m|--metadata)
                METADATA="$2"
                shift 2
                ;;
            -p|--progress)
                PROGRESS=true
                shift
                ;;
            -v|--verbose)
                VERBOSE=true
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
            *)
                echo "Internal error!"
                exit 1
                ;;
        esac
    done

    # Remaining arguments are image files
    IMAGES=("$@")
    if [ ${#IMAGES[@]} -eq 0 ]; then
        echo "ERROR: No image files specified." >&2
        usage
    fi

    # If output not specified, generate one
    if [ -z "$OUTPUT_FILE" ]; then
        if [ ${#IMAGES[@]} -eq 1 ]; then
            # Single image: use same basename with .pdf
            OUTPUT_FILE="${IMAGES[0]%.*}.pdf"
        else
            OUTPUT_FILE="combined.pdf"
        fi
        echo "No output specified, using: $OUTPUT_FILE"
    fi
fi

# -------------------------------------------------------------------
# GUI mode (kdialog)
# -------------------------------------------------------------------
if $USE_GUI; then
    # Select images (multiple)
    # kdialog returns newline-separated list; use readarray to handle spaces
    IFS=$'\n' read -r -d '' -a IMAGES < <(kdialog --multiple --getopenfilename "$HOME" "Image Files (*.png *.jpg *.jpeg *.gif *.bmp *.tiff *.webp)" 2>/dev/null)
    if [ ${#IMAGES[@]} -eq 0 ]; then
        echo "No images selected, exiting."
        exit 1
    fi

    # Output file
    OUTPUT_FILE=$(kdialog --getsavefilename "$HOME" "Save PDF as" "images.pdf")
    if [ -z "$OUTPUT_FILE" ]; then
        echo "No output file specified, exiting."
        exit 1
    fi
    if [[ "$OUTPUT_FILE" != *.pdf ]]; then
        OUTPUT_FILE="${OUTPUT_FILE}.pdf"
    fi

    # Paper size
    PAPER_SIZE=$(kdialog --combobox "Select paper size:" "A4" "Letter" "Legal" --default "$DEFAULT_PAPER_SIZE")
    [ -z "$PAPER_SIZE" ] && exit 1

    # Orientation
    ORIENTATION=$(kdialog --combobox "Select orientation:" "portrait" "landscape" --default "$DEFAULT_ORIENTATION")
    [ -z "$ORIENTATION" ] && exit 1

    # Quality
    QUALITY=$(kdialog --inputbox "JPEG quality (1-100):" "$DEFAULT_QUALITY")
    # If user cancels, QUALITY will be empty; we'll fallback to default later
fi

# -------------------------------------------------------------------
# Pre-flight checks
# -------------------------------------------------------------------
check_deps

# Validate quality (1-100)
if [ -n "$QUALITY" ] && { [ "$QUALITY" -lt 1 ] || [ "$QUALITY" -gt 100 ]; } 2>/dev/null; then
    echo "ERROR: Quality must be between 1 and 100." >&2
    exit 1
fi

# Ensure output directory is writable
output_dir=$(dirname "$OUTPUT_FILE")
if [ ! -d "$output_dir" ]; then
    echo "ERROR: Output directory '$output_dir' does not exist." >&2
    exit 1
fi
if [ ! -w "$output_dir" ]; then
    echo "ERROR: Output directory '$output_dir' is not writable." >&2
    exit 1
fi

# Check if output file already exists (prompt in GUI, warn in CLI)
if [ -e "$OUTPUT_FILE" ]; then
    if $USE_GUI; then
        if ! kdialog --warningyesno "File '$OUTPUT_FILE' exists. Overwrite?"; then
            echo "Exiting."
            exit 1
        fi
    else
        echo "Warning: Output file '$OUTPUT_FILE' already exists. Will overwrite."
    fi
fi

# Check ImageMagick policy for PDF writing (optional)
if ! convert -list format 2>/dev/null | grep -q "PDF.*rw"; then
    echo "Warning: ImageMagick PDF output may be restricted by policy. Check /etc/ImageMagick-*/policy.xml" >&2
fi

# -------------------------------------------------------------------
# Build convert options
# -------------------------------------------------------------------
CONVERT_OPTS=()

# Set page size and orientation
# For landscape, use paper size with "Landscape" suffix (e.g., "A4Landscape")
if [ "$ORIENTATION" = "landscape" ]; then
    case "$PAPER_SIZE" in
        A4)         PAGE="${PAPER_SIZE}Landscape" ;;
        Letter)     PAGE="${PAPER_SIZE}Landscape" ;;
        Legal)      PAGE="${PAPER_SIZE}Landscape" ;;
        *)          PAGE="$PAPER_SIZE" ;; # fallback
    esac
else
    PAGE="$PAPER_SIZE"
fi
CONVERT_OPTS+=("-page" "$PAGE")

# Quality
if [ -n "$QUALITY" ]; then
    CONVERT_OPTS+=("-quality" "$QUALITY")
fi

# Metadata (if any) – use -define pdf:... for standard PDF metadata
if [ -n "$METADATA" ]; then
    # Split METADATA into an array
    IFS=',' read -ra KV <<< "$METADATA"
    # Use indexed loop to make array explicit
    for (( idx=0; idx<${#KV[@]}; idx++ )); do
        pair="${KV[$idx]}"
        key="${pair%%=*}"
        value="${pair#*=}"
        CONVERT_OPTS+=("-define" "pdf:${key}=${value}")
    done
fi

# Progress (ImageMagick 7+)
if [ "$PROGRESS" = true ]; then
    # Check if convert supports -progress (ImageMagick 7)
    if convert -version | grep -q "Version: ImageMagick 7"; then
        CONVERT_OPTS+=("-progress")
    else
        echo "Progress option requires ImageMagick 7. Ignored." >&2
    fi
fi

# Verbose (show commands)
if [ "$VERBOSE" = true ]; then
    CONVERT_OPTS+=("-verbose")
fi

# -------------------------------------------------------------------
# Run conversion
# -------------------------------------------------------------------
echo "Converting ${#IMAGES[@]} images to PDF: $OUTPUT_FILE"

if [ "$VERBOSE" = true ]; then
    echo "Running: convert" "${IMAGES[@]}" "${CONVERT_OPTS[@]}" "$OUTPUT_FILE"
fi

# Use "${IMAGES[@]}" to preserve spaces in filenames
if ! convert "${IMAGES[@]}" "${CONVERT_OPTS[@]}" "$OUTPUT_FILE"; then
    exit_code=$?
    if $USE_GUI; then
        kdialog --error "❌ Conversion failed (exit code $exit_code). Check the files and try again."
    else
        echo "❌ Conversion failed (exit code $exit_code)." >&2
    fi
    exit $exit_code
fi

# Success
if $USE_GUI; then
    kdialog --msgbox "✅ PDF saved to:\n$OUTPUT_FILE"
else
    echo "✅ PDF saved to: $OUTPUT_FILE"
fi

exit 0
