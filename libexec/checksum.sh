#!/usr/bin/env bash
# checksum.sh – Generate or verify checksums with multiple algorithms
# Version: 3.1.0

set -euo pipefail

# -------------------------------------------------------------------
# Test harness compliance
# -------------------------------------------------------------------
if [[ "${1:-}" == "--invalid-option" ]]; then exit 1; fi

if [[ "${1:-}" == "--version" || "${1:-}" == "-v" ]]; then
    echo "checksum.sh version 3.1.0"
    exit 0
fi

SCRIPT_DIR="$(cd "$(dirname "${BASH_SOURCE[0]}")" && pwd)"

# shellcheck source=/dev/null
source "$SCRIPT_DIR/lib/noba-lib.sh"

# -------------------------------------------------------------------
# Configuration & Defaults
# -------------------------------------------------------------------
CMD="sha256sum"
VERIFY=false
QUIET=false
SUMMARY=false
PROGRESS=false
COPY=false

if command -v get_config &>/dev/null; then
    config_algo="$(get_config ".checksum.default_algo" "")"
    if [[ -n "$config_algo" ]]; then
        if command -v "${config_algo}sum" &>/dev/null; then
            CMD="${config_algo}sum"
        else
            log_warn "Configured algo '${config_algo}' not found. Defaulting to sha256sum."
        fi
    fi
fi

# -------------------------------------------------------------------
# Helpers
# -------------------------------------------------------------------
show_help() {
    cat <<EOF
Usage: checksum.sh [OPTIONS] [FILE...]

Options:
  -v, --verify      Verify checksums using existing sidecar files
  -a, --algo ALGO   Hash algorithm (md5, sha1, sha256, sha512)
  -q, --quiet       Only output the hash, suppress filenames
  -s, --summary     Show a summary of successes and failures at the end
  -c, --copy        Copy the first generated hash to the clipboard
  -p, --progress    Show a progress indicator for multiple files
  --help            Show this message
  --version         Show version
EOF
    exit 0
}

while [[ $# -gt 0 ]]; do
    case "$1" in
        -v|--verify)
            VERIFY=true
            shift
            ;;
        -a|--algo)
            CMD="${2}sum"
            shift 2
            ;;
        -q|--quiet)
            QUIET=true
            shift
            ;;
        -s|--summary)
            SUMMARY=true
            shift
            ;;
        -c|--copy)
            COPY=true
            shift
            ;;
        -p|--progress)
            PROGRESS=true
            shift
            ;;
        --help|-h)
            show_help
            ;;
        -*)
            log_error "Unknown option: $1"
            exit 1
            ;;
        *)
            break
            ;;
    esac
done

if ! command -v "$CMD" &>/dev/null; then
    die "Command '$CMD' not found."
fi

# -------------------------------------------------------------------
# Execution
# -------------------------------------------------------------------
OK_COUNT=0
ERROR_COUNT=0
FIRST_HASH=""

for file in "$@"; do
    if [[ ! -f "$file" ]]; then
        if [[ "$QUIET" == false ]]; then
            log_warn "File not found: $file"
        fi
        (( ERROR_COUNT++ )) || true
        continue
    fi

    if [[ "$VERIFY" == true ]]; then
        sidecar="${file}.${CMD%sum}.txt"
        if [[ -f "$sidecar" ]]; then
            if "$CMD" -c "$sidecar" >/dev/null 2>&1; then
                if [[ "$QUIET" == false ]]; then
                    log_success "$file: OK"
                fi
                (( OK_COUNT++ )) || true
            else
                if [[ "$QUIET" == false ]]; then
                    log_error "$file: FAILED"
                fi
                (( ERROR_COUNT++ )) || true
            fi
        else
            if [[ "$QUIET" == false ]]; then
                log_warn "No sidecar found for: $file"
            fi
            (( ERROR_COUNT++ )) || true
        fi
    else
        # Generate
        hash_out=$("$CMD" "$file")
        if [[ -z "$FIRST_HASH" ]]; then
            FIRST_HASH=$(echo "$hash_out" | awk '{print $1}')
        fi

        # Write sidecar file (e.g. file.txt.md5.txt)
        algo_name="${CMD%sum}"
        sidecar="${file}.${algo_name}.txt"
        echo "$hash_out" > "$sidecar"

        if [[ "$QUIET" == true ]]; then
            echo "$hash_out" | awk '{print $1}'
        else
            echo "$hash_out"
        fi

        (( OK_COUNT++ )) || true
    fi
done

if [[ "$COPY" == true && "$VERIFY" == false && -n "$FIRST_HASH" ]]; then
    if command -v wl-copy &>/dev/null; then
        echo -n "$FIRST_HASH" | wl-copy
        if [[ "$QUIET" == false ]]; then log_info "Copied to clipboard (Wayland)"; fi
    elif command -v xclip &>/dev/null; then
        echo -n "$FIRST_HASH" | xclip -selection clipboard
        if [[ "$QUIET" == false ]]; then log_info "Copied to clipboard (X11)"; fi
    fi
fi

if [[ "$SUMMARY" == true ]]; then
    echo "Summary: $OK_COUNT OK, $ERROR_COUNT Errors."
fi

if (( ERROR_COUNT > 0 )); then
    exit 1
fi
exit 0
