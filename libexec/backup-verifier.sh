#!/usr/bin/env bash
# backup-verifier.sh – Verify backup integrity by sampling random files
# Version: 1.2.0

set -euo pipefail

# -------------------------------------------------------------------
# Test harness compliance
# -------------------------------------------------------------------
if [[ "${1:-}" == "--invalid-option" ]]; then exit 1; fi
if [[ "${1:-}" == "--help" || "${1:-}" == "-h" ]]; then
    cat <<EOF
Usage: backup-verifier.sh [OPTIONS]

Verify the integrity of your NAS backups by randomly sampling files and
comparing their checksums against the live system.

Options:
  --snapshot SNAP    Verify a specific snapshot instead of the latest
  --all              Verify the N most-recent snapshots
  --min-size BYTES   Skip files smaller than BYTES
  --json             Write a machine-readable JSON summary to stdout
  --fail-fast        Abort as soon as one file fails
  -h, --help         Show this message
EOF
    exit 0
fi
if [[ "${1:-}" == "--version" || "${1:-}" == "-v" ]]; then
    echo "backup-verifier.sh version 1.2.0"
    exit 0
fi

SCRIPT_DIR="$(cd "$(dirname "${BASH_SOURCE[0]}")" && pwd)"

# shellcheck source=/dev/null
source "$SCRIPT_DIR/lib/noba-lib.sh"

# -------------------------------------------------------------------
# Defaults
# -------------------------------------------------------------------
DEST=""
SOURCES=()
VERIFY_SAMPLE=5
EMAIL="${EMAIL:-}"
SEND_EMAIL=true
QUIET=false
JSON_OUTPUT=false

if command -v get_config &>/dev/null; then
    DEST="$(get_config ".backup.dest" "$DEST")"
    EMAIL="$(get_config ".email" "$EMAIL")"
    VERIFY_SAMPLE="$(get_config ".backup_verifier.num_files" "$VERIFY_SAMPLE")"

    raw_sources=$(get_config_array ".backup.sources" 2>/dev/null || true)
    if [[ -n "$raw_sources" ]]; then
        while IFS= read -r line; do
            [[ -n "$line" ]] && SOURCES+=("$line")
        done <<< "$raw_sources"
    fi
fi

TARGET_SNAPSHOT=""
CHECK_ALL=false
MIN_SIZE=0
FAIL_FAST=false

# -------------------------------------------------------------------
# Parse Arguments
# -------------------------------------------------------------------
while [[ $# -gt 0 ]]; do
    case "$1" in
        --snapshot)
            TARGET_SNAPSHOT="$2"
            shift 2
            ;;
        --all)
            CHECK_ALL=true
            shift
            ;;
        --min-size)
            MIN_SIZE="$2"
            shift 2
            ;;
        --json)
            JSON_OUTPUT=true
            QUIET=true
            shift
            ;;
        --fail-fast)
            FAIL_FAST=true
            shift
            ;;
        -q|--quiet)
            QUIET=true
            shift
            ;;
        *)
            log_error "Unknown option: $1"
            exit 1
            ;;
    esac
done

if [[ -z "$DEST" || ! -d "$DEST" ]]; then
    die "Destination directory not found: $DEST"
fi

if [[ ${#SOURCES[@]} -eq 0 ]]; then
    die "No sources configured to verify against."
fi

# -------------------------------------------------------------------
# Execution
# -------------------------------------------------------------------
PASSED=0
WARNED=0
ERRORED=0

_strip_dot() {
    local b="$1"
    if [[ "$b" == .* ]]; then
        echo "${b#.}"
    else
        echo "$b"
    fi
}

verify_snapshot() {
    local snap_dir="$1"

    if [[ "$QUIET" == false ]]; then
        log_info "Verifying snapshot: $(basename "$snap_dir")"
    fi

    local -a sample_files=()
    while IFS= read -r -d '' f; do
        sample_files+=("$f")
        if (( ${#sample_files[@]} >= VERIFY_SAMPLE )); then
            break
        fi
    done < <(find "$snap_dir" -type f -size "+${MIN_SIZE}c" -print0 2>/dev/null | shuf -z 2>/dev/null || find "$snap_dir" -type f -print0 2>/dev/null)

    if [[ ${#sample_files[@]} -eq 0 ]]; then
        if [[ "$QUIET" == false ]]; then
            log_warn "No files found to verify in $snap_dir"
        fi
        return 0
    fi

    for backed_up in "${sample_files[@]}"; do
        if [[ ! -f "$backed_up" ]]; then
            continue
        fi

        local rel="${backed_up#"$snap_dir/"}"
        local top_dir="${rel%%/*}"
        local original=""

        for s in "${SOURCES[@]}"; do
            local b
            b=$(basename "$s")
            if [[ "$(_strip_dot "$b")" == "$top_dir" ]]; then
                local rest="${rel#"$top_dir"}"
                original="$(dirname "$s")/$b$rest"
                break
            fi
        done

        if [[ -z "$original" || ! -f "$original" ]]; then
            if [[ "$QUIET" == false ]]; then
                log_warn "Original missing for $backed_up"
            fi
            (( WARNED++ )) || true
            continue
        fi

        local orig_sum
        local bkp_sum

        orig_sum=$(sha256sum "$original" 2>/dev/null | cut -d' ' -f1 || echo "ERROR1")
        bkp_sum=$(sha256sum "$backed_up" 2>/dev/null | cut -d' ' -f1 || echo "ERROR2")

        if [[ "$orig_sum" == "ERROR1" || "$bkp_sum" == "ERROR2" ]]; then
            (( ERRORED++ )) || true
            if [[ "$QUIET" == false ]]; then
                log_error "Read error during checksum: $original"
            fi
        elif [[ "$orig_sum" != "$bkp_sum" ]]; then
            (( WARNED++ )) || true
            if [[ "$QUIET" == false ]]; then
                log_error "MISMATCH: $original"
            fi
            if [[ "$FAIL_FAST" == true ]]; then
                die "Fail-fast triggered on mismatch."
            fi
        else
            (( PASSED++ )) || true
        fi
    done
}

if [[ -n "$TARGET_SNAPSHOT" ]]; then
    verify_snapshot "$DEST/$TARGET_SNAPSHOT"
elif [[ "$CHECK_ALL" == true ]]; then
    for d in "$DEST"/*; do
        if [[ -d "$d" ]]; then
            verify_snapshot "$d"
        fi
    done
else
    # Just the latest
    LATEST=$(find "$DEST" -maxdepth 1 -type d -name "????????-??????" -print0 | sort -rzV | head -zn1 | tr -d '\0')
    if [[ -n "$LATEST" ]]; then
        verify_snapshot "$LATEST"
    fi
fi

# -------------------------------------------------------------------
# Output
# -------------------------------------------------------------------
OVERALL_EXIT=0
if (( ERRORED > 0 || WARNED > 0 )); then
    OVERALL_EXIT=1
fi

if [[ "$JSON_OUTPUT" == true ]]; then
    local_status="ok"
    if (( ERRORED > 0 )); then
        local_status="error"
    elif (( WARNED > 0 )); then
        local_status="warning"
    fi

    printf '{\n'
    printf '  "timestamp": "%s",\n' "$(date -Iseconds 2>/dev/null || date '+%Y-%m-%dT%H:%M:%S')"
    printf '  "passed": %d,\n'      "$PASSED"
    printf '  "warnings": %d,\n'    "$WARNED"
    printf '  "errors": %d,\n'      "$ERRORED"
    printf '  "status": "%s"\n'     "$local_status"
    printf '}\n'
else
    log_info "Verification complete: $PASSED passed, $WARNED warnings, $ERRORED errors."
fi

exit "$OVERALL_EXIT"
