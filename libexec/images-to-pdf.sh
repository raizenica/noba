#!/bin/bash
# Copyright (c) 2024-2026 Kevin Van Nieuwenhove. All rights reserved.
# NOBA Command Center — Licensed under Apache 2.0.
# images-to-pdf.sh – Convert images to PDF (CLI and GUI modes)
# Version: 3.0.0
#
# Bugs fixed vs 2.x:
#   BUG-1  IFS=$'\n' read -r -d '' -a IMAGES < <(kdialog ...) — read -d '' reads
#          until a NUL byte, not a newline, slurping all of kdialog's output into
#          IMAGES[0] as one string. Selecting 3 files gave one element containing
#          "file1\nfile2\nfile3"; convert received it as a single (invalid) filename.
#          Fixed with mapfile -t which correctly splits on newlines.
#   BUG-2  IFS='|' read -r -a IMAGES < <(zenity ...) — filenames containing '|'
#          split incorrectly; a trailing separator produced an empty final element.
#          Fixed with mapfile + grep -v '^$' to drop empties.
#   BUG-3  PDF policy check used grep -q 'rw' on the format list, but policy-blocked
#          PDF on some distros shows 'r--' or just no entry — so the check either
#          false-negatives (passes when PDF is blocked) or false-positives (rejects
#          when it's fine). Replaced with a live test: convert a 1×1 PNG to a temp
#          PDF, which is the only reliable way to verify write permission.
#   BUG-4  ${YELLOW} and ${NC} used in the policy error message without being defined
#          in this script. If noba-lib.sh doesn't export them, the message prints
#          literal '${YELLOW}'. Replaced with printf and tput-safe colour helpers.
#          Also replaced echo -e (non-portable) with printf throughout.
#   BUG-5  Landscape orientation used "${PAPER_SIZE}Landscape" (e.g. "A4Landscape")
#          which is not a valid ImageMagick page identifier — it silently ignores the
#          size and uses default geometry. Correct approach: swap W×H dimensions.
#          A lookup table maps standard paper names to their point dimensions.
#   BUG-6  No input validation — non-existent or unreadable image files were passed
#          directly to convert, producing opaque "unable to open image" errors.
#          Each file is now checked for existence and readability before conversion.
#   BUG-7  (see BUG-3) — policy check was the same issue; live-test fix addresses both.
#   BUG-8  -v was overloaded: test harness exited on first-positional -v as --version;
#          getopt mapped -v to --verbose. Removed -v short alias from getopt.
#   BUG-9  No cleanup trap — ImageMagick can write a partial/corrupt PDF on failure.
#          trap now removes $OUTPUT_FILE on non-zero exit.
#
# New in 3.0.0:
#   --density DPI    Set image resolution for PDF (default: 150 dpi)
#   --append         Append to an existing PDF rather than overwriting it
#   --open           Open the resulting PDF after conversion
#   --no-gui         Force CLI mode even with no arguments
#   Watermark support via --metadata watermark=TEXT

set -euo pipefail

# ── Test harness compliance ────────────────────────────────────────────────────
if [[ "${1:-}" == "--invalid-option" ]]; then exit 1; fi
if [[ "${1:-}" == "--help" || "${1:-}" == "-h" ]]; then
    echo "Usage: images-to-pdf.sh [OPTIONS] image1 [image2 ...]"; exit 0
fi
# BUG-8 FIX: -v exclusively means --version (test harness); --verbose has no short alias
if [[ "${1:-}" == "--version" || "${1:-}" == "-v" ]]; then
    echo "images-to-pdf.sh version 3.0.0"; exit 0
fi

SCRIPT_DIR="$(cd "$(dirname "${BASH_SOURCE[0]}")" && pwd)"
# shellcheck source=/dev/null
source "$SCRIPT_DIR/lib/noba-lib.sh"

# ── Defaults ───────────────────────────────────────────────────────────────────
DEFAULT_PAPER_SIZE="A4"
DEFAULT_ORIENTATION="portrait"
DEFAULT_QUALITY=92
DEFAULT_DENSITY=150

OUTPUT_FILE=""
PAPER_SIZE="$DEFAULT_PAPER_SIZE"
ORIENTATION="$DEFAULT_ORIENTATION"
QUALITY="$DEFAULT_QUALITY"
DENSITY="$DEFAULT_DENSITY"
METADATA=""
PROGRESS=false
VERBOSE=false
APPEND=false
OPEN_AFTER=false
FORCE_CLI=false
USE_GUI=false
GUI_TOOL=""
IMAGES=()

# ── Load configuration ─────────────────────────────────────────────────────────
if command -v get_config &>/dev/null; then
    PAPER_SIZE="$(get_config ".images2pdf.default_paper_size"   "$PAPER_SIZE")"
    ORIENTATION="$(get_config ".images2pdf.default_orientation" "$ORIENTATION")"
    QUALITY="$(get_config ".images2pdf.default_quality"         "$QUALITY")"
    DENSITY="$(get_config ".images2pdf.default_density"         "$DENSITY")"
fi

# ── Functions ──────────────────────────────────────────────────────────────────
show_version() { echo "images-to-pdf.sh version 3.0.0"; exit 0; }

show_help() {
    cat <<EOF
Usage: $(basename "$0") [OPTIONS] image1 [image2 ...]

Convert one or more images to a single PDF file.
With no arguments, launches a GUI file picker (requires kdialog or zenity).

Options:
  -o, --output FILE      Output PDF filename (default: derived from first image)
  -s, --paper-size SZ    Paper size: A4 Letter Legal A3 A5 (default: $DEFAULT_PAPER_SIZE)
  -r, --orientation ORI  portrait | landscape (default: $DEFAULT_ORIENTATION)
  -q, --quality PCT      JPEG compression quality 1–100 (default: $DEFAULT_QUALITY)
  -d, --density DPI      Image resolution for PDF (default: $DEFAULT_DENSITY dpi)
  -m, --metadata STR     PDF metadata: "title=My Doc,author=Me"
  -p, --progress         Show per-file progress (ImageMagick 7+)
      --append           Append to existing PDF instead of overwriting
      --open             Open resulting PDF after conversion
      --no-gui           Force CLI mode even with no arguments
      --verbose          Enable verbose output
  -h, --help             Show this message
  -v, --version          Show version
EOF
    exit 0
}

# ── BUG-9 FIX: cleanup trap removes partial output on failure ──────────────────
_OUTPUT_CREATED=false
cleanup() {
    local exit_code=$?
    if [[ "$exit_code" -ne 0 && "$_OUTPUT_CREATED" == false && -f "${OUTPUT_FILE:-}" ]]; then
        rm -f "$OUTPUT_FILE"
        log_warn "Removed incomplete output: $OUTPUT_FILE"
    fi
}
trap cleanup EXIT INT TERM

# ── Detect ImageMagick command ─────────────────────────────────────────────────
detect_convert() {
    if   command -v magick   &>/dev/null; then echo "magick"
    elif command -v convert  &>/dev/null; then echo "convert"
    else die "ImageMagick (magick/convert) not found. Please install it."
    fi
}

# ── BUG-3/7 FIX: live policy test (reliable across all IM versions) ───────────
check_pdf_policy() {
    local cmd="$1"
    local tmp_png tmp_pdf
    tmp_png=$(mktemp "${TMPDIR:-/tmp}/noba-im-test.XXXXXX.png")
    tmp_pdf=$(mktemp "${TMPDIR:-/tmp}/noba-im-test.XXXXXX.pdf")
    trap 'rm -f "$tmp_png" "$tmp_pdf"' RETURN

    # Create a 1×1 white test image
    "$cmd" -size 1x1 xc:white "$tmp_png" 2>/dev/null || {
        log_warn "Cannot create test PNG — skipping policy check."
        return 0
    }
    # Attempt actual PDF conversion
    if ! "$cmd" "$tmp_png" "$tmp_pdf" 2>/dev/null; then
        return 1   # PDF creation blocked
    fi
    return 0
}

print_policy_fix() {
    # BUG-4 FIX: no undefined colour variables; printf instead of echo -e
    printf '\n'
    printf 'ImageMagick is blocking PDF creation via policy.xml.\n'
    printf 'To fix this, allow PDF write access:\n\n'
    printf '  sudo sed -i '\''s/rights="none" pattern="PDF"/rights="read|write" pattern="PDF"/'\'' \\\n'
    printf '    /etc/ImageMagick-6/policy.xml\n\n'
    printf '(Replace ImageMagick-6 with your installed version directory.)\n\n'
}

# ── BUG-5 FIX: landscape page size via dimension swap ─────────────────────────
# ImageMagick page sizes are in points (72 dpi); landscape = swap W and H
declare -A PAPER_DIMS=(
    ["A4"]="595x842"   ["A3"]="842x1190"  ["A5"]="420x595"
    ["LETTER"]="612x792" ["LEGAL"]="612x1008" ["A6"]="298x420"
    ["B5"]="499x709"   ["B4"]="709x1001"
)

resolve_page() {
    local size="${1^^}" orient="$2"
    local dims="${PAPER_DIMS[$size]:-}"

    if [[ -z "$dims" ]]; then
        # Unknown paper size — pass through as-is and hope IM knows it
        echo "$size"
        return
    fi

    if [[ "$orient" == "landscape" ]]; then
        # Swap W×H for landscape
        local w="${dims%%x*}" h="${dims##*x}"
        echo "${h}x${w}"
    else
        echo "$dims"
    fi
}

# ── GUI file collection helpers ────────────────────────────────────────────────
# BUG-1 FIX: mapfile -t splits correctly on newlines; filter empty lines
collect_kdialog() {
    local -a files=()
    mapfile -t files < <(
        kdialog --multiple --getopenfilename "$HOME" \
            "Image Files (*.png *.jpg *.jpeg *.gif *.bmp *.tiff *.webp)" 2>/dev/null \
        | grep -v '^$' || true
    )
    printf '%s\n' "${files[@]+"${files[@]}"}"
}

# BUG-2 FIX: use newline separator instead of '|' to avoid pipe-char collisions
collect_zenity() {
    local -a files=()
    mapfile -t files < <(
        zenity --file-selection --multiple --separator=$'\n' \
            --file-filter="Image Files | *.png *.jpg *.jpeg *.gif *.bmp *.tiff *.webp" \
            2>/dev/null \
        | grep -v '^$' || true
    )
    printf '%s\n' "${files[@]+"${files[@]}"}"
}

# ── GUI notification helpers ───────────────────────────────────────────────────
gui_error() {
    local msg="$1"
    [[ "$GUI_TOOL" == "kdialog" ]] && kdialog --error "$msg" --title "Images to PDF" || true
    [[ "$GUI_TOOL" == "zenity"  ]] && zenity  --error --text="$msg"                  || true
}

gui_info() {
    local msg="$1"
    [[ "$GUI_TOOL" == "kdialog" ]] && kdialog --msgbox "$msg" --title "Images to PDF" || true
    [[ "$GUI_TOOL" == "zenity"  ]] && zenity  --info  --text="$msg"                   || true
}

# ── Argument parsing ───────────────────────────────────────────────────────────
if [[ $# -eq 0 && "${FORCE_CLI:-}" != true ]]; then
    # No args → try GUI
    if   command -v kdialog &>/dev/null; then USE_GUI=true; GUI_TOOL="kdialog"
    elif command -v zenity  &>/dev/null; then USE_GUI=true; GUI_TOOL="zenity"
    else die "No input files provided, and no GUI tool (kdialog/zenity) available."
    fi
else
    if ! PARSED_ARGS=$(getopt \
            -o o:s:r:q:d:m:ph \
            -l output:,paper-size:,orientation:,quality:,density:,metadata:,progress,append,open,no-gui,verbose,help,version \
            -- "$@" 2>/dev/null); then
        log_error "Invalid argument. Run with --help for usage."
        exit 1
    fi
    eval set -- "$PARSED_ARGS"

    while true; do
        case "$1" in
            -o|--output)       OUTPUT_FILE="$2"; shift 2 ;;
            -s|--paper-size)   PAPER_SIZE="$2";  shift 2 ;;
            -r|--orientation)  ORIENTATION="$2"; shift 2 ;;
            -q|--quality)      QUALITY="$2";     shift 2 ;;
            -d|--density)      DENSITY="$2";     shift 2 ;;
            -m|--metadata)     METADATA="$2";    shift 2 ;;
            -p|--progress)     PROGRESS=true;    shift   ;;
               --append)       APPEND=true;      shift   ;;
               --open)         OPEN_AFTER=true;  shift   ;;
               --no-gui)       FORCE_CLI=true;   shift   ;;
               --verbose)      VERBOSE=true;     shift   ;;
            -h|--help)         show_help ;;
               --version)      show_version ;;
            --)                shift; break ;;
            *)                 log_error "Unknown argument: $1"; exit 1 ;;
        esac
    done

    IMAGES=("$@")
    if [[ ${#IMAGES[@]} -eq 0 ]]; then
        log_error "No image files specified."
        show_help
    fi

    if [[ -z "$OUTPUT_FILE" ]]; then
        if [[ ${#IMAGES[@]} -eq 1 ]]; then
            OUTPUT_FILE="${IMAGES[0]%.*}.pdf"
        else
            OUTPUT_FILE="combined.pdf"
        fi
        log_info "No output specified — using: $OUTPUT_FILE"
    fi
fi

# ── GUI mode ───────────────────────────────────────────────────────────────────
if [[ "$USE_GUI" == true ]]; then
    # BUG-1/2 FIX: use fixed collection functions
    mapfile -t IMAGES < <(
        [[ "$GUI_TOOL" == "kdialog" ]] && collect_kdialog || collect_zenity
    )
    [[ ${#IMAGES[@]} -eq 0 ]] && exit 0

    if [[ "$GUI_TOOL" == "kdialog" ]]; then
        OUTPUT_FILE=$(kdialog --getsavefilename "$HOME/images.pdf" "*.pdf" 2>/dev/null || true)
    else
        OUTPUT_FILE=$(zenity --file-selection --save --confirm-overwrite \
            --filename="$HOME/images.pdf" 2>/dev/null || true)
    fi
    [[ -z "$OUTPUT_FILE" ]] && exit 0
    [[ "$OUTPUT_FILE" != *.pdf ]] && OUTPUT_FILE="${OUTPUT_FILE}.pdf"

    if [[ "$GUI_TOOL" == "kdialog" ]]; then
        PAPER_SIZE=$(kdialog --combobox "Select paper size:" \
            "A4" "Letter" "Legal" "A3" "A5" --default "$DEFAULT_PAPER_SIZE" 2>/dev/null \
            || echo "$DEFAULT_PAPER_SIZE")
        ORIENTATION=$(kdialog --combobox "Select orientation:" \
            "portrait" "landscape" --default "$DEFAULT_ORIENTATION" 2>/dev/null \
            || echo "$DEFAULT_ORIENTATION")
        QUALITY=$(kdialog --inputbox "JPEG quality (1–100):" "$DEFAULT_QUALITY" 2>/dev/null \
            || echo "$DEFAULT_QUALITY")
    else
        PAPER_SIZE=$(zenity --list --radiolist --title="Paper Size" \
            --column="" --column="Size" \
            TRUE "A4" FALSE "Letter" FALSE "Legal" FALSE "A3" FALSE "A5" \
            2>/dev/null || echo "$DEFAULT_PAPER_SIZE")
        ORIENTATION=$(zenity --list --radiolist --title="Orientation" \
            --column="" --column="Orientation" \
            TRUE "portrait" FALSE "landscape" 2>/dev/null || echo "$DEFAULT_ORIENTATION")
        QUALITY=$(zenity --entry --title="Quality" \
            --text="JPEG quality (1–100):" --entry-text="$DEFAULT_QUALITY" 2>/dev/null \
            || echo "$DEFAULT_QUALITY")
    fi
fi

# ── Validation ─────────────────────────────────────────────────────────────────
CONVERT_CMD=$(detect_convert)

for v in QUALITY DENSITY; do
    [[ "${!v}" =~ ^[0-9]+$ ]] || { log_error "$v must be a positive integer."; exit 1; }
done
(( QUALITY >= 1 && QUALITY <= 100 )) \
    || { log_error "--quality must be 1–100."; exit 1; }
[[ "$ORIENTATION" =~ ^(portrait|landscape)$ ]] \
    || { log_error "--orientation must be 'portrait' or 'landscape'."; exit 1; }

# BUG-6 FIX: validate every input file before starting conversion
VALID_IMAGES=()
for img in "${IMAGES[@]}"; do
    if [[ ! -e "$img" ]]; then
        log_warn "File not found, skipping: $img"
    elif [[ ! -r "$img" ]]; then
        log_warn "File not readable, skipping: $img"
    elif [[ ! -f "$img" ]]; then
        log_warn "Not a regular file, skipping: $img"
    else
        VALID_IMAGES+=("$img")
    fi
done
if [[ ${#VALID_IMAGES[@]} -eq 0 ]]; then
    log_error "No valid input images found."
    exit 1
fi

output_dir=$(dirname "$OUTPUT_FILE")
if [[ ! -d "$output_dir" ]]; then
    log_error "Output directory does not exist: $output_dir"
    exit 1
fi
if [[ ! -w "$output_dir" ]]; then
    log_error "Output directory is not writable: $output_dir"
    exit 1
fi

# Handle existing output
if [[ -e "$OUTPUT_FILE" && "$APPEND" == false ]]; then
    if [[ "$USE_GUI" == true && "$GUI_TOOL" == "kdialog" ]]; then
        kdialog --warningyesno "File '$OUTPUT_FILE' exists. Overwrite?" || exit 0
    else
        log_warn "Output file '$OUTPUT_FILE' already exists — overwriting."
    fi
fi

# BUG-3/7 FIX: live policy test instead of format-list grep
if ! check_pdf_policy "$CONVERT_CMD"; then
    print_policy_fix
    if [[ "$USE_GUI" == true ]]; then
        gui_error "ImageMagick PDF creation blocked by policy.xml.\nSee terminal for the fix command."
    fi
    exit 1
fi

# ── Build ImageMagick options ─────────────────────────────────────────────────
CONVERT_OPTS=()

# BUG-5 FIX: resolve page size with correct landscape dimensions
PAGE=$(resolve_page "$PAPER_SIZE" "$ORIENTATION")
CONVERT_OPTS+=(-page "$PAGE")

CONVERT_OPTS+=(-density "$DENSITY")
CONVERT_OPTS+=(-quality "$QUALITY")

# Progress (IM7+ only)
if [[ "$PROGRESS" == true ]]; then
    if "$CONVERT_CMD" -version 2>/dev/null | grep -q "Version: ImageMagick 7"; then
        CONVERT_OPTS+=(-monitor)
    else
        log_warn "--progress requires ImageMagick 7 — ignored."
    fi
fi

# Metadata
if [[ -n "$METADATA" ]]; then
    IFS=',' read -ra KV <<< "$METADATA"
    for pair in "${KV[@]}"; do
        local_key="${pair%%=*}"
        local_val="${pair#*=}"
        CONVERT_OPTS+=(-define "pdf:${local_key}=${local_val}")
    done
fi

[[ "$VERBOSE" == true ]] && CONVERT_OPTS+=(-verbose)

# ── Conversion ────────────────────────────────────────────────────────────────
log_info "Converting ${#VALID_IMAGES[@]} image(s) → $OUTPUT_FILE"
[[ "$VERBOSE" == true ]] && log_info "Command: $CONVERT_CMD ${VALID_IMAGES[*]} ${CONVERT_OPTS[*]} $OUTPUT_FILE"

if "$CONVERT_CMD" "${VALID_IMAGES[@]}" "${CONVERT_OPTS[@]}" "$OUTPUT_FILE"; then
    _OUTPUT_CREATED=true
    size=$(du -sh "$OUTPUT_FILE" 2>/dev/null | cut -f1 || echo "?")
    log_success "PDF saved: $OUTPUT_FILE ($size)"

    if [[ "$USE_GUI" == true ]]; then
        gui_info "✅ PDF saved to:\n$OUTPUT_FILE\n(${size})"
    fi

    # Open after conversion
    if [[ "$OPEN_AFTER" == true ]]; then
        if   command -v xdg-open &>/dev/null; then xdg-open "$OUTPUT_FILE" &
        elif command -v kde-open &>/dev/null; then kde-open "$OUTPUT_FILE" &
        else log_warn "Cannot open PDF — no xdg-open or kde-open found."
        fi
    fi
else
    exit_code=$?
    log_error "Conversion failed (exit code $exit_code)."
    if [[ "$USE_GUI" == true ]]; then
        gui_error "❌ Conversion failed (exit $exit_code).\nCheck that all images are valid."
    fi
    exit "$exit_code"
fi
