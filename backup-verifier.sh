#!/bin/bash
# backup-verifier.sh – Verify integrity of latest backup by checking random files

set -euo pipefail

SCRIPT_DIR="$(cd "$(dirname "${BASH_SOURCE[0]}")" && pwd)"
source "$SCRIPT_DIR/noba-lib.sh"

# -------------------------------------------------------------------
# Default configuration
# -------------------------------------------------------------------
BACKUP_ROOT="${BACKUP_DEST:-/mnt/vnnas/backups/raizen}"
NUM_FILES=5
EMAIL="${EMAIL:-strikerke@gmail.com}"
CHECKSUM_CMD="md5sum"
TEMP_DIR_BASE="${TMPDIR:-/tmp}"
DRY_RUN=false
QUIET=false
VERBOSE=false
COMPARE_ORIGINAL=false

# -------------------------------------------------------------------
# Load user configuration (YAML)
# -------------------------------------------------------------------
load_config || true
if [ "$CONFIG_LOADED" = true ]; then
    BACKUP_ROOT="$(get_config ".backup_verifier.dest" "$BACKUP_ROOT")"
    NUM_FILES="$(get_config ".backup_verifier.num_files" "$NUM_FILES")"
    EMAIL="$(get_config ".email" "$EMAIL")"
    CHECKSUM_CMD="$(get_config ".backup_verifier.checksum_cmd" "$CHECKSUM_CMD")"
    TEMP_DIR_BASE="$(get_config ".backup_verifier.temp_dir" "$TEMP_DIR_BASE")"
fi

# -------------------------------------------------------------------
# Helper functions
# -------------------------------------------------------------------
show_version() {
    echo "backup-verifier.sh version 1.0"
    exit 0
}

show_help() {
    cat <<EOF
Usage: $0 [OPTIONS]

Verify the integrity of the latest backup by checking random files.

Options:
  -b, --backup-dir DIR   Root directory containing timestamped backups (default: $BACKUP_ROOT)
  -n, --num-files N      Number of random files to verify (default: $NUM_FILES)
  -c, --compare-original Compare with original files (if they exist in home)
  --checksum-cmd CMD     Checksum command to use (default: $CHECKSUM_CMD)
  --temp-dir DIR         Base directory for temporary files (default: $TEMP_DIR_BASE)
  -v, --verbose          Enable verbose output
  -q, --quiet            Suppress non‑error output
  -D, --dry-run          Simulate without actually copying
  --help                 Show this help message
  --version              Show version information
EOF
    exit 0
}

# Convert bytes to human-readable
bytes_to_human() {
    local bytes=$1
    if command -v numfmt &>/dev/null; then
        numfmt --to=iec "$bytes"
    else
        echo "$bytes bytes"
    fi
}

# Get file size portably
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

# Generate random indices (using shuf if available, else bash $RANDOM)
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
            # SC2076: Do not quote regex
            if [[ ! " ${indices[*]} " =~ $i ]]; then
                indices+=("$i")
            fi
        done
        printf '%s\n' "${indices[@]}"
    fi
}

# -------------------------------------------------------------------
# Parse command-line arguments
# -------------------------------------------------------------------
PARSED_ARGS=$(getopt -o b:n:cDvq -l backup-dir:,num-files:,compare-original,checksum-cmd:,temp-dir:,verbose,quiet,dry-run,help,version -- "$@")
if ! PARSED_ARGS=$(getopt -o b:n:cDvq -l backup-dir:,num-files:,compare-original,checksum-cmd:,temp-dir:,verbose,quiet,dry-run,help,version -- "$@"); then
    show_help
fi
eval set -- "$PARSED_ARGS"

while true; do
    case "$1" in
        -b|--backup-dir)      BACKUP_ROOT="$2"; shift 2 ;;
        -n|--num-files)       NUM_FILES="$2"; shift 2 ;;
        -c|--compare-original) COMPARE_ORIGINAL=true; shift ;;
        --checksum-cmd)       CHECKSUM_CMD="$2"; shift 2 ;;
        --temp-dir)           TEMP_DIR_BASE="$2"; shift 2 ;;
        -v|--verbose)         VERBOSE=true; shift ;;
        -q|--quiet)           QUIET=true; shift ;;
        -D|--dry-run)         DRY_RUN=true; shift ;;
        --help)               show_help ;;
        --version)            show_version ;;
        --)                   shift; break ;;
        *)                    break ;;
    esac
done

# -------------------------------------------------------------------
# Pre-flight checks
# -------------------------------------------------------------------
check_deps find sort tail cp rm mkdir dirname mktemp wc cut
if ! command -v "$CHECKSUM_CMD" &>/dev/null; then
    log_error "Checksum command '$CHECKSUM_CMD' not found."
    exit 1
fi

if ! [[ "$NUM_FILES" =~ ^[0-9]+$ ]] || [ "$NUM_FILES" -le 0 ]; then
    log_error "--num-files must be a positive integer."
    exit 1
fi

# Find latest backup folder
# shellcheck disable=SC2012
LATEST_BACKUP=$(ls -d "$BACKUP_ROOT"/[0-9][0-9][0-9][0-9][0-9][0-9][0-9][0-9]-[0-9][0-9][0-9][0-9][0-9][0-9] 2>/dev/null | sort | tail -1)
if [ -z "$LATEST_BACKUP" ]; then
    log_error "No timestamped backup folders found in $BACKUP_ROOT"
    exit 1
fi
log_info "Latest backup: $LATEST_BACKUP"

# Build file list
mapfile -t FILES < <(find "$LATEST_BACKUP" -type f -print0 2>/dev/null | xargs -0 -I {} printf "%s\n" "{}")
TOTAL_FILES=${#FILES[@]}
if [ "$TOTAL_FILES" -eq 0 ]; then
    log_error "No files found in backup $LATEST_BACKUP"
    exit 1
fi
log_debug "Total files in backup: $TOTAL_FILES"

# Select random files
SELECTED=()
if [ "$TOTAL_FILES" -le "$NUM_FILES" ]; then
    SELECTED=("${FILES[@]}")
else
    while IFS= read -r idx; do
        SELECTED+=("${FILES[$idx]}")
    done < <(random_indices "$TOTAL_FILES" "$NUM_FILES")
fi
log_debug "Selected ${#SELECTED[@]} files for verification"

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

    log_debug "Verifying: $rel_path"
    if [ "$DRY_RUN" = true ]; then
        log_info "[DRY RUN] Would verify $rel_path"
        REPORT+="[DRY RUN] $rel_path\n"
        continue
    fi

    size=$(get_size "$file")
    size_hr=$(bytes_to_human "$size")

    if cp "$file" "$dest" 2>/dev/null; then
        orig_hash=$($CHECKSUM_CMD "$file" | cut -d' ' -f1)
        copy_hash=$($CHECKSUM_CMD "$dest" | cut -d' ' -f1)
        if [ "$orig_hash" = "$copy_hash" ]; then
            result="✅ OK"
            REPORT+="$result $rel_path (size: $size_hr, checksum match)\n"
            log_debug "  OK (size: $size_hr)"
        else
            result="❌ FAILED (checksum mismatch)"
            REPORT+="$result $rel_path (size: $size_hr)\n"
            ((FAILED++))
            log_debug "  FAILED: checksum mismatch"
        fi

        if [ "$COMPARE_ORIGINAL" = true ]; then
            original=""
            # Try to map backup path to original home location
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
                    log_debug "  Original file matches"
                else
                    REPORT+="  ⚠  ORIGINAL FILE DIFFERS from backup\n"
                    ((WARNINGS++))
                    log_debug "  WARNING: original file differs"
                fi
            elif [ -n "$original" ]; then
                REPORT+="  (original file not found on disk)\n"
                log_debug "  Original not found"
            fi
        fi
    else
        result="❌ FAILED (copy failed)"
        REPORT+="$result $rel_path\n"
        ((FAILED++))
        log_debug "  FAILED: could not copy file"
    fi
done

REPORT+="\nSummary: ${#SELECTED[@]} files checked, $FAILED failures, $WARNINGS warnings (if compare-original).\n"

if [ "$FAILED" -gt 0 ]; then
    log_warn "Verification completed with $FAILED errors."
elif [ "$WARNINGS" -gt 0 ]; then
    log_warn "Verification completed with $WARNINGS warnings (original files differ)."
else
    log_success "All verified files are intact."
fi

# -------------------------------------------------------------------
# Email report (if configured and not dry run)
# -------------------------------------------------------------------
if [ "$DRY_RUN" = false ] && [ -n "$EMAIL" ]; then
    if command -v msmtp &>/dev/null; then
        printf "Subject: Backup Verification Report - %s\n\n%s\n" "$(date +%Y-%m-%d)" "$REPORT" | msmtp "$EMAIL"
        log_info "Report emailed to $EMAIL"
    else
        log_warn "msmtp not installed – cannot email report."
    fi
fi
