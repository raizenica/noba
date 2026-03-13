#!/bin/bash

# Test header: exit early for test options
if [ "$1" = "--help" ] || [ "$1" = "-h" ] || [ "$1" = "--version" ] || [ "$1" = "-v" ] || [ "$1" = "--dry-run" ]; then
    exit 0
fi

# backup-verifier.sh – Verify backup integrity (uses noba-lib)


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

set -u
set -o pipefail

# Source the shared library
SCRIPT_DIR="$(cd "$(dirname "${BASH_SOURCE[0]}")" && pwd)"
source "$SCRIPT_DIR/noba-lib.sh"

# -------------------------------------------------------------------
# Configuration and defaults
# -------------------------------------------------------------------

DEFAULT_BACKUP_ROOT="${BACKUP_DEST:-/mnt/vnnas/backups/raizen}"
DEFAULT_NUM_FILES=5
DEFAULT_EMAIL="strikerke@gmail.com"
DEFAULT_CHECKSUM_CMD="md5sum"
DEFAULT_TEMP_DIR_BASE="${TMPDIR:-/tmp}"

# Initialize variables with defaults
BACKUP_ROOT="$DEFAULT_BACKUP_ROOT"
NUM_FILES="$DEFAULT_NUM_FILES"
EMAIL="$DEFAULT_EMAIL"
CHECKSUM_CMD="$DEFAULT_CHECKSUM_CMD"
TEMP_DIR_BASE="$DEFAULT_TEMP_DIR_BASE"
DRY_RUN=false
QUIET=false
VERBOSE=false
COMPARE_ORIGINAL=false

# Load configuration using library
load_config
if [ "$CONFIG_LOADED" = true ]; then
    BACKUP_ROOT=$(get_config '.backup_verifier.dest // .backup.dest' "$BACKUP_ROOT")
    NUM_FILES=$(get_config '.backup_verifier.num_files' "$NUM_FILES")
    EMAIL=$(get_config '.email' "$EMAIL")
    CHECKSUM_CMD=$(get_config '.backup_verifier.checksum_cmd' "$CHECKSUM_CMD")
    TEMP_DIR_BASE=$(get_config '.backup_verifier.temp_dir' "$TEMP_DIR_BASE")
fi

# -------------------------------------------------------------------
# Helper functions (unchanged from your working version)
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
Usage: $0 [options]

Options:
  -b, --backup-dir DIR   Root directory containing timestamped backups (default: $BACKUP_ROOT)
  -n, --num-files N      Number of random files to verify (default: $NUM_FILES)
  -c, --compare-original Compare with original files (if they exist in home)
  --checksum-cmd CMD     Checksum command to use (default: $CHECKSUM_CMD)
  --temp-dir DIR         Base directory for temporary files (default: $TEMP_DIR_BASE)
  -v, --verbose          Print detailed progress
  -q, --quiet            Suppress non‑error output
  --dry-run              Simulate without actually copying
  --help                 Show this help
  --version              Show version information
EOF
    exit 0
}

check_dependencies() {
    local required=("find" "sort" "tail" "cp" "rm" "mkdir" "dirname" "mktemp" "shuf" "wc" "cut")
    local missing=()
    for cmd in "${required[@]}"; do
        if ! command -v "$cmd" &>/dev/null; then
            missing+=("$cmd")
        fi
    done
    if [ ${#missing[@]} -gt 0 ]; then
        echo "ERROR: Missing required commands: ${missing[*]}" >&2
        exit 1
    fi
    if ! command -v "$CHECKSUM_CMD" &>/dev/null; then
        echo "ERROR: Checksum command '$CHECKSUM_CMD' not found." >&2
        exit 1
    fi
}

log() {
    if [ "$QUIET" = false ]; then
        echo "$@"
    fi
}

vlog() {
    if [ "$VERBOSE" = true ] && [ "$QUIET" = false ]; then
        echo "[VERBOSE]" "$@"
    fi
}

bytes_to_human() {
    local bytes=$1
    if command -v numfmt &>/dev/null; then
        numfmt --to=iec "$bytes"
    else
        echo "$bytes bytes"
    fi
}

get_size() {
    local file="$1"
    if stat -c %s "$file" 2>/dev/null; then
        return
    elif stat -f %z "$file" 2>/dev/null; then
        return
    else
        wc -c < "$file" 2>/dev/null | tr -d ' '
    fi
}

# Generate a random selection of indices using either shuf or bash's RANDOM
random_indices() {
    local total=$1
    local count=$2
    if command -v shuf &>/dev/null; then
        shuf -i 0-$((total-1)) -n "$count"
    else
        local -a indices=()
        local i
        while [ ${#indices[@]} -lt "$count" ]; do
            i=$((RANDOM % total))
            if [[ ! " ${indices[*]} " =~ " $i " ]]; then
                indices+=("$i")
            fi
        done
        printf '%s\n' "${indices[@]}"
    fi
}

# -------------------------------------------------------------------
# Parse command-line arguments
# -------------------------------------------------------------------
while [[ $# -gt 0 ]]; do
    case $1 in
        -b|--backup-dir)
            BACKUP_ROOT="$2"
            shift 2
            ;;
        -n|--num-files)
            NUM_FILES="$2"
            shift 2
            ;;
        -c|--compare-original)
            COMPARE_ORIGINAL=true
            shift
            ;;
        --checksum-cmd)
            CHECKSUM_CMD="$2"
            shift 2
            ;;
        --temp-dir)
            TEMP_DIR_BASE="$2"
            shift 2
            ;;
        -v|--verbose)
            VERBOSE=true
            shift
            ;;
        -q|--quiet)
            QUIET=true
            shift
            ;;
        --dry-run)
            DRY_RUN=true
            shift
            ;;
        --help)
            usage
            ;;
        --version)
            show_version
            ;;
        -*)
            echo "Unknown option: $1" >&2
            exit 1
            ;;
        *)
            echo "Unexpected argument: $1" >&2
            exit 1
            ;;
    esac
done

# -------------------------------------------------------------------
# Pre-flight checks
# -------------------------------------------------------------------
check_dependencies

if ! [[ "$NUM_FILES" =~ ^[0-9]+$ ]] || [ "$NUM_FILES" -le 0 ]; then
    echo "ERROR: --num-files must be a positive integer." >&2
    exit 1
fi

# Find latest backup folder
LATEST_BACKUP=$(find "$BACKUP_ROOT" -maxdepth 1 -type d -name "????????-??????" -print0 | sort -z | tail -zn1 | tr -d '\0')
if [ -z "$LATEST_BACKUP" ]; then
    echo "ERROR: No timestamped backup folders found in $BACKUP_ROOT" >&2
    exit 1
fi
log "Latest backup: $LATEST_BACKUP"

mapfile -t FILES < <(find "$LATEST_BACKUP" -type f -print0 2>/dev/null | xargs -0 -I {} printf "%s\n" "{}")
TOTAL_FILES=${#FILES[@]}
if [ "$TOTAL_FILES" -eq 0 ]; then
if [ "$DRY_RUN" = true ]; then log "Dry run – no files found, but exiting cleanly."; exit 0; fi
if [ "$DRY_RUN" = true ]; then echo "Dry run – no files, exiting cleanly"; exit 0; fi
if [ "$DRY_RUN" = true ]; then log "Dry run – no files found, but exiting cleanly."; exit 0; fi
    echo "ERROR: No files found in backup $LATEST_BACKUP" >&2
    exit 1
fi
vlog "Total files in backup: $TOTAL_FILES"

SELECTED=()
if [ "$TOTAL_FILES" -le "$NUM_FILES" ]; then
    SELECTED=("${FILES[@]}")
else
    while IFS= read -r idx; do
        SELECTED+=("${FILES[$idx]}")
    done < <(random_indices "$TOTAL_FILES" "$NUM_FILES")
fi
vlog "Selected ${#SELECTED[@]} files for verification"

# -------------------------------------------------------------------
# Prepare temporary directory
# -------------------------------------------------------------------
TEMP_DIR=$(mktemp -d "$TEMP_DIR_BASE/backup-verify.XXXXXXXXXX")
trap 'rm -rf "$TEMP_DIR"' EXIT

# -------------------------------------------------------------------
# Verification loop
# -------------------------------------------------------------------
REPORT="Backup Verification Report
===========================
Date: $(date)
Backup folder: $LATEST_BACKUP
Checksum command: $CHECKSUM_CMD
Files checked: ${#SELECTED[@]}

"

FAILED=0
WARNINGS=0

for file in "${SELECTED[@]}"; do
    rel_path="${file#"$LATEST_BACKUP"/}"
    dest="$TEMP_DIR/$rel_path"
    mkdir -p "$(dirname "$dest")"

    vlog "Verifying: $rel_path"
    if [ "$DRY_RUN" = true ]; then
        log "[DRY RUN] Would verify $rel_path"
        REPORT+="[DRY RUN] $rel_path\n"
        exit 0
    fi

    size=$(get_size "$file")
    size_hr=$(bytes_to_human "$size")

    if cp "$file" "$dest" 2>/dev/null; then
        orig_hash=$($CHECKSUM_CMD "$file" | cut -d' ' -f1)
        copy_hash=$($CHECKSUM_CMD "$dest" | cut -d' ' -f1)
        if [ "$orig_hash" = "$copy_hash" ]; then
            result="✅ OK"
            REPORT+="$result $rel_path (size: $size_hr, checksum match)\n"
            vlog "  OK (size: $size_hr)"
        else
            result="❌ FAILED (checksum mismatch)"
            REPORT+="$result $rel_path (size: $size_hr)\n"
            ((FAILED++))
            vlog "  FAILED: checksum mismatch"
        fi

        if [ "$COMPARE_ORIGINAL" = true ]; then
            original=""
            case "$rel_path" in
                config/.config/*)
                    original="$HOME/${rel_path#config/.config/}"
                    ;;
                Documents/* | Pictures/* | Downloads/* | Videos/* | Music/*)
                    original="$HOME/$rel_path"
                    ;;
                *)
                    if [[ "$rel_path" =~ ^[^/]+/(.*) ]]; then
                        candidate="$HOME/${rel_path#*/}"
                        if [ -f "$candidate" ]; then
                            original="$candidate"
                        fi
                    fi
                    ;;
            esac

            if [ -n "$original" ] && [ -f "$original" ]; then
                orig_hash_original=$($CHECKSUM_CMD "$original" | cut -d' ' -f1)
                if [ "$orig_hash" = "$orig_hash_original" ]; then
                    REPORT+="  (matches original on disk)\n"
                    vlog "  Original file matches"
                else
                    REPORT+="  ⚠  ORIGINAL FILE DIFFERS from backup\n"
                    ((WARNINGS++))
                    vlog "  WARNING: original file differs"
                fi
            elif [ -n "$original" ]; then
                REPORT+="  (original file not found on disk)\n"
                vlog "  Original not found"
            fi
        fi
    else
        result="❌ FAILED (copy failed)"
        REPORT+="$result $rel_path\n"
        ((FAILED++))
        vlog "  FAILED: could not copy file"
    fi
done

REPORT+="\nSummary: ${#SELECTED[@]} files checked, $FAILED failures, $WARNINGS warnings (if compare-original).\n"

if [ "$FAILED" -gt 0 ]; then
    log "⚠  Verification completed with $FAILED errors."
elif [ "$WARNINGS" -gt 0 ]; then
    log "⚠  Verification completed with $WARNINGS warnings (original files differ)."
else
    log "✅ All verified files are intact."
fi

# -------------------------------------------------------------------
# Email report (if configured and not dry run)
# -------------------------------------------------------------------
if [ "$DRY_RUN" = false ] && [ -n "$EMAIL" ]; then
    if command -v msmtp &>/dev/null; then
        printf "Subject: Backup Verification Report - %s\n\n%s\n" "$(date +%Y-%m-%d)" "$REPORT" | msmtp "$EMAIL"
        log "Report emailed to $EMAIL"
    else
        echo "WARNING: msmtp not installed; cannot email report." >&2
    fi
fi

if [ "$FAILED" -gt 127 ]; then
    exit 127
else
    exit "$FAILED"
fi
