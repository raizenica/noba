#!/bin/bash
# images-to-pdf.sh – Convert images to PDF (CLI and GUI modes)

set -euo pipefail

SCRIPT_DIR="$(cd "$(dirname "${BASH_SOURCE[0]}")" && pwd)"
# shellcheck source=/dev/null
source "$SCRIPT_DIR/noba-lib.sh"

# -------------------------------------------------------------------
# Default configuration
# -------------------------------------------------------------------
DEFAULT_PAPER_SIZE="A4"
DEFAULT_ORIENTATION="portrait"
DEFAULT_QUALITY=92

OUTPUT_FILE=""
PAPER_SIZE="$DEFAULT_PAPER_SIZE"
ORIENTATION="$DEFAULT_ORIENTATION"
QUALITY="$DEFAULT_QUALITY"
METADATA=""
PROGRESS=false
VERBOSE=false
USE_GUI=false

# -------------------------------------------------------------------
# Load user configuration (YAML)
# -------------------------------------------------------------------
load_config
if [ "$CONFIG_LOADED" = true ]; then
    PAPER_SIZE="$(get_config ".images2pdf.default_paper_size" "$PAPER_SIZE")"
    ORIENTATION="$(get_config ".images2pdf.default_orientation" "$ORIENTATION")"
    QUALITY="$(get_config ".images2pdf.default_quality" "$QUALITY")"
fi

# -------------------------------------------------------------------
# Helper functions
# -------------------------------------------------------------------
show_version() {
    echo "images-to-pdf.sh version 1.0"
    exit 0
}

show_help() {
    cat <<EOF
Usage: $0 [options] image1 [image2 ...]

Convert one or more images to a single PDF.

Options:
  -o, --output FILE     Output PDF filename (required in CLI mode if more than one image)
  -s, --paper-size SIZE Paper size: A4, Letter, Legal, etc. (default: $DEFAULT_PAPER_SIZE)
  -r, --orientation DIR Orientation: portrait or landscape (default: $DEFAULT_ORIENTATION)
  -q, --quality PERCENT JPEG compression quality (1-100, default: $DEFAULT_QUALITY)
  -m, --metadata STR    Add PDF metadata (e.g., "title=My PDF,author=Me")
  -p, --progress        Show progress for many images (requires ImageMagick 7)
  -v, --verbose         Enable verbose output
  --help                Show this help message
  --version             Show version information

If no arguments are given and kdialog is installed, launches a GUI file picker.
EOF
    exit 0
}

# -------------------------------------------------------------------
# Parse command-line arguments
# -------------------------------------------------------------------
if [ $# -eq 0 ]; then
    if command -v kdialog &>/dev/null; then
        USE_GUI=true
    else
        log_error "No input files and kdialog not available."
        exit 1
    fi
else
    PARSED_ARGS=$(getopt -o o:s:r:q:m:pv -l output:,paper-size:,orientation:,quality:,metadata:,progress,verbose,help,version -- "$@")
    if ! some_command; then
    show_help
    fi
    eval set -- "$PARSED_ARGS"

    while true; do
        case "$1" in
            -o|--output)         OUTPUT_FILE="$2"; shift 2 ;;
            -s|--paper-size)     PAPER_SIZE="$2"; shift 2 ;;
            -r|--orientation)    ORIENTATION="$2"; shift 2 ;;
            -q|--quality)        QUALITY="$2"; shift 2 ;;
            -m|--metadata)        METADATA="$2"; shift 2 ;;
            -p|--progress)        PROGRESS=true; shift ;;
            -v|--verbose)         VERBOSE=true; shift ;;
            --help)               show_help ;;
            --version)            show_version ;;
            --)                   shift; break ;;
            *)                    break ;;
        esac
    done

    IMAGES=("$@")
    if [ ${#IMAGES[@]} -eq 0 ]; then
        log_error "No image files specified."
        show_help
    fi

    # Set default output if not given
    if [ -z "$OUTPUT_FILE" ]; then
        if [ ${#IMAGES[@]} -eq 1 ]; then
            OUTPUT_FILE="${IMAGES[0]%.*}.pdf"
        else
            OUTPUT_FILE="combined.pdf"
        fi
        log_info "No output specified, using: $OUTPUT_FILE"
    fi
fi

# -------------------------------------------------------------------
# GUI mode (kdialog)
# -------------------------------------------------------------------
if [ "$USE_GUI" = true ]; then
    # Select images
    IFS=$'\n' read -r -d '' -a IMAGES < <(kdialog --multiple --getopenfilename "$HOME" "Image Files (*.png *.jpg *.jpeg *.gif *.bmp *.tiff *.webp)" 2>/dev/null || true)
    if [ ${#IMAGES[@]} -eq 0 ]; then
        log_info "No images selected, exiting."
        exit 0
    fi

    OUTPUT_FILE=$(kdialog --getsavefilename "$HOME" "Save PDF as" "images.pdf" 2>/dev/null)
    if [ -z "$OUTPUT_FILE" ]; then
        log_info "No output file specified, exiting."
        exit 0
    fi
    if [[ "$OUTPUT_FILE" != *.pdf ]]; then
        OUTPUT_FILE="${OUTPUT_FILE}.pdf"
    fi

    PAPER_SIZE=$(kdialog --combobox "Select paper size:" "A4" "Letter" "Legal" --default "$DEFAULT_PAPER_SIZE" 2>/dev/null)
    [ -z "$PAPER_SIZE" ] && exit 0

    ORIENTATION=$(kdialog --combobox "Select orientation:" "portrait" "landscape" --default "$DEFAULT_ORIENTATION" 2>/dev/null)
    [ -z "$ORIENTATION" ] && exit 0

    QUALITY=$(kdialog --inputbox "JPEG quality (1-100):" "$DEFAULT_QUALITY" 2>/dev/null)
fi

# -------------------------------------------------------------------
# Pre-flight checks
# -------------------------------------------------------------------
check_deps convert

# Validate quality
if [ -n "$QUALITY" ] && { [ "$QUALITY" -lt 1 ] || [ "$QUALITY" -gt 100 ]; } 2>/dev/null; then
    log_error "Quality must be between 1 and 100."
    exit 1
fi

output_dir=$(dirname "$OUTPUT_FILE")
if [ ! -d "$output_dir" ]; then
    log_error "Output directory '$output_dir' does not exist."
    exit 1
fi
if [ ! -w "$output_dir" ]; then
    log_error "Output directory '$output_dir' is not writable."
    exit 1
fi

if [ -e "$OUTPUT_FILE" ]; then
    if [ "$USE_GUI" = true ]; then
        if ! kdialog --warningyesno "File '$OUTPUT_FILE' exists. Overwrite?"; then
            log_info "Exiting."
            exit 0
        fi
    else
        log_warn "Output file '$OUTPUT_FILE' already exists. Will overwrite."
    fi
fi

# Optional check for PDF write support
if ! convert -list format 2>/dev/null | grep -q "PDF.*rw"; then
    log_warn "ImageMagick PDF output may be restricted by policy. Check /etc/ImageMagick-*/policy.xml"
fi

# -------------------------------------------------------------------
# Build convert options
# -------------------------------------------------------------------
CONVERT_OPTS=()

# Page size and orientation
if [ "$ORIENTATION" = "landscape" ]; then
    case "$PAPER_SIZE" in
        A4|Letter|Legal) PAGE="${PAPER_SIZE}Landscape" ;;
        *) PAGE="$PAPER_SIZE" ;;
    esac
else
    PAGE="$PAPER_SIZE"
fi
CONVERT_OPTS+=("-page" "$PAGE")

# Quality
if [ -n "$QUALITY" ]; then
    CONVERT_OPTS+=("-quality" "$QUALITY")
fi

# Metadata
if [ -n "$METADATA" ]; then
    IFS=',' read -ra KV <<< "$METADATA"
    for pair in "${KV[@]}"; do
        key="${pair%%=*}"
        value="${pair#*=}"
        CONVERT_OPTS+=("-define" "pdf:${key}=${value}")
    done
fi

# Progress (ImageMagick 7+)
if [ "$PROGRESS" = true ]; then
    if convert -version | grep -q "Version: ImageMagick 7"; then
        CONVERT_OPTS+=("-progress")
    else
        log_warn "Progress option requires ImageMagick 7. Ignored."
    fi
fi

# Verbose
if [ "$VERBOSE" = true ]; then
    CONVERT_OPTS+=("-verbose")
    log_debug "convert ${IMAGES[*]} ${CONVERT_OPTS[*]} $OUTPUT_FILE"
fi

# -------------------------------------------------------------------
# Run conversion
# -------------------------------------------------------------------
log_info "Converting ${#IMAGES[@]} images to PDF: $OUTPUT_FILE"

if ! convert "${IMAGES[@]}" "${CONVERT_OPTS[@]}" "$OUTPUT_FILE"; then
    exit_code=$?
    if [ "$USE_GUI" = true ]; then
        kdialog --error "❌ Conversion failed (exit code $exit_code). Check the files and try again."
    else
        log_error "Conversion failed (exit code $exit_code)."
    fi
    exit $exit_code
fi

if [ "$USE_GUI" = true ]; then
    kdialog --msgbox "✅ PDF saved to:\n$OUTPUT_FILE"
else
    log_success "PDF saved to: $OUTPUT_FILE"
fi
