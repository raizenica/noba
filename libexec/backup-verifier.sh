#!/usr/bin/env bash
# backup-verifier.sh – Standalone integrity verifier for noba backup snapshots
# Version: 1.0.0
#
# Verifies that files in a backup snapshot still match their originals on disk,
# and optionally checks snapshot-to-snapshot consistency using hardlink counts.
#
# Usage:
#   noba verify --dest /mnt/nas/backups [--snapshot 20240601-120000] [--sample N] [--full]
#
# Exit codes:
#   0  All checks passed
#   1  One or more verification failures
#   2  Fatal error (missing dest, no snapshots found, etc.)

set -euo pipefail

SCRIPT_DIR="$(cd "$(dirname "${BASH_SOURCE[0]}")" && pwd)"
# shellcheck source=./lib/noba-lib.sh
source "$SCRIPT_DIR/lib/noba-lib.sh"

# ── Defaults ──────────────────────────────────────────────────────────────────
DEST=""
SNAPSHOT=""        # empty = use latest
SAMPLE=20          # files to spot-check (ignored when --full is set)
FULL_VERIFY=false  # check every file
QUIET=false
CHECK_HARDLINKS=false   # verify hardlink counts between consecutive snapshots
LOG_FILE="${LOG_FILE:-$HOME/.local/share/backup-verifier.log}"

# ── Help ──────────────────────────────────────────────────────────────────────
show_help() {
    cat <<EOF
Usage: $(basename "$0") [OPTIONS]

Verify integrity of a noba backup snapshot against the live source files.

Options:
  -d, --dest DIR          Root directory where snapshots live (required)
  -S, --snapshot NAME     Snapshot to verify (default: latest, e.g. 20240601-120000)
  -s, --sample N          Files to spot-check when not using --full (default: $SAMPLE)
  -f, --full              Verify every file instead of a random sample
  -H, --hardlinks         Also check hardlink counts between the two most-recent snapshots
  -q, --quiet             Suppress informational output; only print failures
      --help              Show this message and exit

Exit codes:
  0  All checks passed
  1  One or more verification failures detected
  2  Fatal / setup error (missing dest, sha256sum unavailable, etc.)

Examples:
  noba verify --dest /mnt/nas/backups
  noba verify --dest /mnt/nas/backups --snapshot 20240601-120000 --full
  noba verify --dest /mnt/nas/backups --sample 50 --hardlinks
EOF
    exit 0
}

# ── Argument parsing ──────────────────────────────────────────────────────────
if ! PARSED_ARGS=$(getopt -o d:S:s:fHqh \
    -l dest:,snapshot:,sample:,full,hardlinks,quiet,help \
    -- "$@" 2>/dev/null); then
    log_error "Invalid argument. Run with --help for usage."
    exit 2
fi
eval set -- "$PARSED_ARGS"

while true; do
    case "$1" in
        -d|--dest)      DEST="$2";            shift 2 ;;
        -S|--snapshot)  SNAPSHOT="$2";        shift 2 ;;
        -s|--sample)    SAMPLE="$2";          shift 2 ;;
        -f|--full)      FULL_VERIFY=true;     shift   ;;
        -H|--hardlinks) CHECK_HARDLINKS=true; shift   ;;
        -q|--quiet)     QUIET=true;           shift   ;;
        -h|--help)      show_help ;;
        --)             shift; break ;;
        *)              log_error "Unknown argument: $1"; exit 2 ;;
    esac
done

# ── Validation ────────────────────────────────────────────────────────────────
[[ -z "$DEST" ]] && die "--dest is required. Run with --help for usage."
[[ ! -d "$DEST" ]] && die "Destination $DEST does not exist — is the NAS mounted?"
[[ "$SAMPLE" =~ ^[0-9]+$ ]] || die "--sample must be a positive integer, got: $SAMPLE"
command -v sha256sum &>/dev/null || die "sha256sum is required but not installed."

# ── Logging setup ─────────────────────────────────────────────────────────────
mkdir -p "$(dirname "$LOG_FILE")"
touch "$LOG_FILE"
exec > >(tee -a "$LOG_FILE") 2>&1

# ── Resolve snapshot ──────────────────────────────────────────────────────────
if [[ -n "$SNAPSHOT" ]]; then
    SNAP_PATH="$DEST/$SNAPSHOT"
    [[ -d "$SNAP_PATH" ]] || die "Snapshot '$SNAPSHOT' not found in $DEST."
else
    # Find the most-recent snapshot (YYYYMMDD-HHMMSS naming)
    SNAP_PATH=""
    while IFS= read -r -d '' d; do
        SNAP_PATH="$d"
    done < <(find "$DEST" -maxdepth 1 -type d -name "????????-??????" -print0 2>/dev/null | sort -z)
    [[ -n "$SNAP_PATH" ]] || die "No snapshots found in $DEST (expected YYYYMMDD-HHMMSS directories)."
fi

SNAP_NAME=$(basename "$SNAP_PATH")

# ── Summary header ────────────────────────────────────────────────────────────
log_info "============================================================"
log_info "  Backup Verifier v1.0.0"
log_info "  Snapshot:  $SNAP_NAME"
log_info "  Mode:      $([ "$FULL_VERIFY" = true ] && echo 'full' || echo "sample ($SAMPLE files)")"
log_info "  Started:   $(date)"
log_info "============================================================"

FAIL_COUNT=0
CHECK_COUNT=0
MISSING_COUNT=0

# ── Per-source-directory verification ────────────────────────────────────────
# Each top-level directory inside the snapshot corresponds to one backed-up source.
# We attempt to reconstruct the original path from the stored name, reversing the
# dot-stripping that backup-to-nas.sh applies (.config → config, .ssh → ssh).
while IFS= read -r -d '' src_dir; do
    top_name=$(basename "$src_dir")

    # Candidate original paths: check HOME first, then root-level dirs, with and without leading dot
    original_dir=""
    for candidate in "$HOME/$top_name" "$HOME/.$top_name" "/$top_name" "/.$top_name"; do
        if [[ -d "$candidate" ]]; then
            original_dir="$candidate"
            break
        fi
    done

    if [[ -z "$original_dir" ]]; then
        [[ "$QUIET" != true ]] && \
            log_warn "Cannot locate original source for '$top_name' — skipping (source may have moved or been removed)."
        continue
    fi

    [[ "$QUIET" != true ]] && log_info "Checking: $src_dir  →  $original_dir"

    local_fail=0
    local_check=0
    local_missing=0

    # Build file list: full = all files; sample = random N via shuf
    if [[ "$FULL_VERIFY" == true ]]; then
        mapfile -d '' file_list < <(find "$src_dir" -type f -print0 2>/dev/null)
    else
        if command -v shuf &>/dev/null; then
            mapfile -d '' file_list < <(find "$src_dir" -type f -print0 2>/dev/null | shuf -z -n "$SAMPLE")
        else
            log_warn "shuf not available — using first $SAMPLE files (install coreutils for random sampling)."
            mapfile -d '' file_list < <(find "$src_dir" -type f -print0 2>/dev/null | head -zn "$SAMPLE")
        fi
    fi

    for backed_up in "${file_list[@]}"; do
        [[ -z "$backed_up" ]] && continue

        rel="${backed_up#"$src_dir/"}"
        original_file="$original_dir/$rel"

        if [[ ! -f "$original_file" ]]; then
            [[ "$QUIET" != true ]] && log_warn "MISSING in source: $original_file"
            (( local_missing++ )) || true
            (( local_check++ ))   || true
            continue
        fi

        orig_sum=$(sha256sum "$original_file" 2>/dev/null | cut -d' ' -f1)
        bkp_sum=$( sha256sum "$backed_up"     2>/dev/null | cut -d' ' -f1)

        if [[ "$orig_sum" != "$bkp_sum" ]]; then
            log_warn "MISMATCH: $backed_up"
            log_warn "  source:  $orig_sum  $original_file"
            log_warn "  backup:  $bkp_sum  $backed_up"
            (( local_fail++ )) || true
        else
            [[ "$QUIET" != true ]] && log_verbose "OK: $rel"
        fi
        (( local_check++ )) || true
    done

    (( FAIL_COUNT    += local_fail    )) || true
    (( CHECK_COUNT   += local_check   )) || true
    (( MISSING_COUNT += local_missing )) || true

    if (( local_fail > 0 || local_missing > 0 )); then
        log_error "  ✗ $top_name: $local_fail mismatch(es), $local_missing missing from source"
    else
        [[ "$QUIET" != true ]] && log_info "  ✓ $top_name: $local_check file(s) OK"
    fi

done < <(find "$SNAP_PATH" -maxdepth 1 -mindepth 1 -type d -print0 2>/dev/null)

# ── Optional hardlink consistency check ──────────────────────────────────────
# Between the two most-recent snapshots, unchanged files should be hardlinked
# (same inode, nlink ≥ 2). A nlink of 1 on a file that also exists in the
# previous snapshot suggests --link-dest failed silently for that file.
if [[ "$CHECK_HARDLINKS" == true ]]; then
    log_info "------------------------------------------------------------"
    log_info "Hardlink consistency check..."

    PREV_SNAP=""
    # Sort all snapshots descending; the one immediately after ours is the previous
    FOUND_CURRENT=false
    while IFS= read -r -d '' d; do
        if [[ "$d" == "$SNAP_PATH" ]]; then
            FOUND_CURRENT=true
        elif [[ "$FOUND_CURRENT" == false ]]; then
            PREV_SNAP="$d"
        fi
    done < <(find "$DEST" -maxdepth 1 -type d -name "????????-??????" -print0 2>/dev/null | sort -rz)

    if [[ -z "$PREV_SNAP" ]]; then
        log_warn "No previous snapshot found — skipping hardlink check."
    else
        PREV_NAME=$(basename "$PREV_SNAP")
        log_info "Comparing $SNAP_NAME against $PREV_NAME"

        HL_CHECKED=0
        HL_UNLINKED=0

        while IFS= read -r -d '' f; do
            nlink=$(stat --format="%h" "$f" 2>/dev/null || echo 1)
            if (( nlink < 2 )); then
                rel="${f#"$SNAP_PATH/"}"
                prev_copy="$PREV_SNAP/$rel"
                # Only flag as suspicious if the file also exists in the previous snapshot
                if [[ -f "$prev_copy" ]]; then
                    log_warn "NOT HARDLINKED (nlink=1, exists in prev): $rel"
                    (( HL_UNLINKED++ )) || true
                fi
            fi
            (( HL_CHECKED++ )) || true
        done < <(find "$SNAP_PATH" -type f -print0 2>/dev/null)

        if (( HL_UNLINKED > 0 )); then
            log_warn "Hardlink check: $HL_UNLINKED/$HL_CHECKED file(s) not hardlinked to previous snapshot."
            log_warn "This may indicate --link-dest failed. Consider re-running a full backup."
            (( FAIL_COUNT += HL_UNLINKED )) || true
        else
            log_info "Hardlink check passed: all $HL_CHECKED file(s) properly linked where expected."
        fi
    fi
fi

# ── Final summary ─────────────────────────────────────────────────────────────
log_info "============================================================"
log_info "  Snapshot:   $SNAP_NAME"
log_info "  Checked:    $CHECK_COUNT file(s)"
log_info "  Missing:    $MISSING_COUNT"
log_info "  Mismatches: $FAIL_COUNT"
log_info "  Finished:   $(date)"
log_info "============================================================"

if (( FAIL_COUNT > 0 || MISSING_COUNT > 0 )); then
    log_error "Verification FAILED — $FAIL_COUNT mismatch(es), $MISSING_COUNT missing."
    exit 1
else
    log_success "Verification passed — $CHECK_COUNT file(s) OK."
    exit 0
fi
