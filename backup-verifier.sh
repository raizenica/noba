#!/bin/bash
# Backup Verifier – test integrity of random files from backups

set -u
set -o pipefail

# -------------------------------------------------------------------
# Configuration and defaults
# -------------------------------------------------------------------

# Source central config if available
# shellcheck source=/dev/null
if [ -f "$HOME/.config/automation.conf" ]; then
    source "$HOME/.config/automation.conf"
fi

# Defaults (can be overridden by config or command line)
BACKUP_ROOT="${BACKUP_DEST:-/mnt/vnnas/backups/raizen}"
NUM_FILES=5
EMAIL="${EMAIL:-strikerke@gmail.com}"
DRY_RUN=false
QUIET=false
VERBOSE=false
COMPARE_ORIGINAL=false
CHECKSUM_CMD="md5sum"
TEMP_DIR_BASE="${TMPDIR:-/tmp}"

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

# Check that all required commands are available
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
        echo "Please install them and try again." >&2
        exit 1
    fi

    # Verify that the chosen checksum command exists
    if ! command -v "$CHECKSUM_CMD" &>/dev/null; then
        echo "ERROR: Checksum command '$CHECKSUM_CMD' not found." >&2
        exit 1
    fi
}

# Logging function (respects quiet)
log() {
    if [ "$QUIET" = false ]; then
        echo "$@"
    fi
}

# Verbose logging
vlog() {
    if [ "$VERBOSE" = true ] && [ "$QUIET" = false ]; then
        echo "[VERBOSE]" "$@"
    fi
}

# Convert bytes to human-readable (fallback if numfmt missing)
bytes_to_human() {
    local bytes=$1
    if command -v numfmt &>/dev/null; then
        numfmt --to=iec "$bytes"
    else
        echo "$bytes bytes"
    fi
}

# Get file size in bytes (portable)
get_size() {
    local file="$1"
    # Try GNU stat
    if stat -c %s "$file" 2>/dev/null; then
        return
    # Try BSD stat
    elif stat -f %z "$file" 2>/dev/null; then
        return
    # Fallback to wc -c
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
        # Fallback: use bash's RANDOM (not perfectly uniform but good enough)
        local -a indices=()
        local i
        while [ ${#indices[@]} -lt "$count" ]; do
            i=$((RANDOM % total))
            # Check for duplicates (simple linear search, ok for small counts)
            if [[ ! " ${indices[*]} " == *" $i * ]]; then
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

# Ensure NUM_FILES is a positive integer
if ! [[ "$NUM_FILES" =~ ^[0-9]+$ ]] || [ "$NUM_FILES" -le 0 ]; then
    echo "ERROR: --num-files must be a positive integer." >&2
    exit 1
fi

# Find the most recent backup folder (by timestamp)
LATEST_BACKUP=$(find "$BACKUP_ROOT" -maxdepth 1 -type d -name "????????-??????" -print0 | sort -z | tail -zn1 | tr -d '\0')
if [ -z "$LATEST_BACKUP" ]; then
    echo "ERROR: No timestamped backup folders found in $BACKUP_ROOT" >&2
    exit 1
fi
log "Latest backup: $LATEST_BACKUP"

# Collect all files in that backup (handle spaces safely)
mapfile -t FILES < <(find "$LATEST_BACKUP" -type f -print0 2>/dev/null | xargs -0 -I {} printf "%s\n" "{}")
TOTAL_FILES=${#FILES[@]}
if [ "$TOTAL_FILES" -eq 0 ]; then
    echo "ERROR: No files found in backup $LATEST_BACKUP" >&2
    exit 1
fi
vlog "Total files in backup: $TOTAL_FILES"

# Randomly select N files
SELECTED=()
if [ "$TOTAL_FILES" -le "$NUM_FILES" ]; then
    SELECTED=("${FILES[@]}")
else
    # Get random indices
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
    # Compute relative path to restore same structure
    rel_path="${file#$LATEST_BACKUP/}"
    dest="$TEMP_DIR/$rel_path"
    mkdir -p "$(dirname "$dest")"

    vlog "Verifying: $rel_path"
    if [ "$DRY_RUN" = true ]; then
        log "[DRY RUN] Would verify $rel_path"
        REPORT+="[DRY RUN] $rel_path\n"
        continue
    fi

    # Get file size (portable)
    size=$(get_size "$file")
    size_hr=$(bytes_to_human "$size")

    # Copy file to temp
    if cp "$file" "$dest" 2>/dev/null; then
        # Compute checksums
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

        # If compare-original is enabled, try to find the original file
        if [ "$COMPARE_ORIGINAL" = true ]; then
            # Guess original path: map based on known patterns
            original=""
            case "$rel_path" in
                config/.config/*)
                    original="$HOME/${rel_path#config/.config/}"
                    ;;
                Documents/* | Pictures/* | Downloads/* | Videos/* | Music/*)
                    original="$HOME/$rel_path"
                    ;;
                # Add more mappings as needed, or use a configurable prefix map
                *)
                    # Try a generic fallback: assume the backup root contains a home-like structure
                    if [[ "$rel_path" =~ ^[^/]+/(.*) ]]; then
                        # e.g., "hostname/home/user/file" -> strip first component
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

# Summary
REPORT+="\nSummary: ${#SELECTED[@]} files checked, $FAILED failures, $WARNINGS warnings (if compare-original).\n"

# Output summary to console
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
        # Use printf for better portability than echo -e
        printf "Subject: Backup Verification Report - %s\n\n%s\n" "$(date +%Y-%m-%d)" "$REPORT" | msmtp "$EMAIL"
        log "Report emailed to $EMAIL"
    else
        echo "WARNING: msmtp not installed; cannot email report." >&2
    fi
fi

# Exit with number of failures (max 127 to stay within valid exit codes)
if [ "$FAILED" -gt 127 ]; then
    exit 127
else
    exit "$FAILED"
fi
