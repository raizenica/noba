#!/bin/bash
# test-all.sh – Comprehensive functionality test for all scripts

set -euo pipefail
trap 'echo "Error at line $LINENO (last command: $BASH_COMMAND)" >&2' ERR

SCRIPT_DIR="$(cd "$(dirname "${BASH_SOURCE[0]}")" && pwd)"
# shellcheck source=/dev/null
source "$SCRIPT_DIR/noba-lib.sh"

# -------------------------------------------------------------------
# Configuration
# -------------------------------------------------------------------
TIMEOUT_SECONDS=5
SKIP_SLOW=false
DRY_RUN=false
VERBOSE=false

# -------------------------------------------------------------------
# Helper functions
# -------------------------------------------------------------------
show_version() {
    echo "test-all.sh version 1.0"
    exit 0
}

show_help() {
    cat <<EOF
Usage: $0 [OPTIONS]

Run functional tests on all noba scripts.

Options:
  -t, --timeout SECS   Set timeout per test (default: $TIMEOUT_SECONDS)
  -s, --skip-slow      Skip long-running or interactive scripts
  -n, --dry-run        Only list scripts to be tested
  -v, --verbose        Show more output (test commands)
  --help               Show this help message
  --version            Show version information
EOF
    exit 0
}

# Run a command with timeout, capturing output if verbose
run_test() {
    local script="$1"
    shift
    local cmd=("$@")
    local output_file
    output_file=$(mktemp)

    if [ "$DRY_RUN" = true ]; then
        log_info "[DRY RUN] Would test: $script ${cmd[*]}"
        rm -f "$output_file"
        return 0
    fi

    if command -v timeout &>/dev/null; then
        if timeout "$TIMEOUT_SECONDS" "${cmd[@]}" > "$output_file" 2>&1; then
            rm -f "$output_file"
            return 0
        else
            local exit_code=$?
            if [ "$VERBOSE" = true ]; then
                cat "$output_file"
            fi
            rm -f "$output_file"
            return $exit_code
        fi
    else
        # Fallback if timeout not available
        if "${cmd[@]}" > "$output_file" 2>&1; then
            rm -f "$output_file"
            return 0
        else
            local exit_code=$?
            if [ "$VERBOSE" = true ]; then
                cat "$output_file"
            fi
            rm -f "$output_file"
            return $exit_code
        fi
    fi
}

# -------------------------------------------------------------------
# Parse arguments
# -------------------------------------------------------------------
PARSED_ARGS=$(getopt -o t:snv -l timeout:,skip-slow,dry-run,verbose,help,version -- "$@")
if [ $? -ne 0 ]; then
    show_help
fi
eval set -- "$PARSED_ARGS"

while true; do
    case "$1" in
        -t|--timeout)    TIMEOUT_SECONDS="$2"; shift 2 ;;
        -s|--skip-slow)  SKIP_SLOW=true; shift ;;
        -n|--dry-run)    DRY_RUN=true; shift ;;
        -v|--verbose)    VERBOSE=true; shift ;;
        --help)          show_help ;;
        --version)       show_version ;;
        --)              shift; break ;;
        *)               break ;;
    esac
done

# -------------------------------------------------------------------
# Prepare test environment
# -------------------------------------------------------------------
cd "$SCRIPT_DIR" || { log_error "Cannot cd to $SCRIPT_DIR"; exit 1; }

echo "DEBUG: Files found: " *.sh >&2

# Create dummy backup for backup-verifier.sh
DUMMY_BACKUP="/tmp/test-backups/$(date +%Y%m%d-%H%M%S)"
mkdir -p "$DUMMY_BACKUP/Documents"
echo "dummy content" > "$DUMMY_BACKUP/Documents/test.txt"

# Create test image for images-to-pdf.sh
TEST_IMAGE="/tmp/test.png"
if [ ! -f "$TEST_IMAGE" ]; then
    if command -v magick &>/dev/null; then
        magick -size 100x100 xc:red "$TEST_IMAGE" 2>/dev/null || true
    elif command -v convert &>/dev/null; then
        convert -size 100x100 xc:red "$TEST_IMAGE" 2>/dev/null || true
    fi
fi

# -------------------------------------------------------------------
# Test counters
# -------------------------------------------------------------------
PASS=0
FAIL=0
SKIP=0

# -------------------------------------------------------------------
# Test each script
# -------------------------------------------------------------------
log_info "Starting tests (timeout: ${TIMEOUT_SECONDS}s, skip slow: $SKIP_SLOW)"

for script in *.sh; do
    echo "DEBUG: Now processing: $script" >&2
    # Skip library and self
    [[ "$script" == "noba-lib.sh" || "$script" == "test-all.sh" ]] && continue

    # Optionally skip slow scripts
    if [ "$SKIP_SLOW" = true ]; then
        case "$script" in
            temperature-alert.sh|service-watch.sh|noba-web.sh)
                log_debug "Skipping slow script: $script"
                SKIP=$((SKIP+1))
                continue
                ;;
        esac
    fi

    echo -n "Testing $script ... "

    # -------------------------------------------------------------------
    # Special case: long-running daemon-like scripts – only test --help and --version
    # -------------------------------------------------------------------
    case "$script" in
        temperature-alert.sh|service-watch.sh|battery-watch.sh|noba-web.sh)
            if run_test "$script" "$script" --help; then
                if grep -q "show_version" "$script" && ! run_test "$script" "$script" --version; then
                    echo -e "${RED}FAIL (--version)${NC}"
                    FAIL=$((FAIL+1))
                else
                    echo -e "${GREEN}PASS${NC}"
                    PASS=$((PASS+1))
                fi
            else
                echo -e "${RED}FAIL (--help)${NC}"
                FAIL=$((FAIL+1))
            fi
            continue
            ;;
    esac

    # -------------------------------------------------------------------
    # Special case: backup-verifier.sh needs a dummy backup dir
    # -------------------------------------------------------------------
    if [[ "$script" == "backup-verifier.sh" ]]; then
        if run_test "$script" "$script" --backup-dir "/tmp/test-backups" --num-files 1 --dry-run; then
            echo -e "${GREEN}PASS${NC}"
            PASS=$((PASS+1))
        else
            echo -e "${RED}FAIL (dry-run on dummy backup)${NC}"
            FAIL=$((FAIL+1))
        fi
        continue
    fi

    # -------------------------------------------------------------------
    # Special case: images-to-pdf.sh needs a test image
    # -------------------------------------------------------------------
    if [[ "$script" == "images-to-pdf.sh" ]]; then
        if [ ! -f "$TEST_IMAGE" ]; then
            echo -e "${YELLOW}SKIP (no test image)${NC}"
            SKIP=$((SKIP+1))
            continue
        fi
        if run_test "$script" "$script" -o /tmp/test.pdf "$TEST_IMAGE"; then
            echo -e "${GREEN}PASS${NC}"
            PASS=$((PASS+1))
        else
            echo -e "${RED}FAIL (conversion)${NC}"
            FAIL=$((FAIL+1))
        fi
        continue
    fi

    # -------------------------------------------------------------------
    # Special case: run-hogwarts-trainer.sh – just check help
    # -------------------------------------------------------------------
    if [[ "$script" == "run-hogwarts-trainer.sh" ]]; then
        if run_test "$script" "$script" --help; then
            echo -e "${GREEN}PASS${NC}"
            PASS=$((PASS+1))
        else
            echo -e "${RED}FAIL (--help)${NC}"
            FAIL=$((FAIL+1))
        fi
        continue
    fi

    # -------------------------------------------------------------------
    # General test: check --help
    # -------------------------------------------------------------------
    if ! run_test "$script" "$script" --help; then
        echo -e "${RED}FAIL (--help)${NC}"
        FAIL=$((FAIL+1))
        continue
    fi

    # Check --version if present
    if grep -q "show_version" "$script"; then
        if ! run_test "$script" "$script" --version; then
            echo -e "${RED}FAIL (--version)${NC}"
            FAIL=$((FAIL+1))
            continue
        fi
    fi

    # -------------------------------------------------------------------
    # Additional dry‑run tests for scripts that support it
    # -------------------------------------------------------------------
    case "$script" in
        backup-to-nas.sh|disk-sentinel.sh|organize-downloads.sh|undo-organizer.sh|log-rotator.sh)
            if ! run_test "$script" "$script" --dry-run; then
                echo -e "${RED}FAIL (--dry-run)${NC}"
                FAIL=$((FAIL+1))
                continue
            fi
            ;;
        checksum.sh)
            tmp=$(mktemp)
            echo "test" > "$tmp"
            if ! run_test "$script" "$script" "$tmp"; then
                echo -e "${RED}FAIL (checksum generation)${NC}"
                FAIL=$((FAIL+1))
                rm -f "$tmp"
                continue
            fi
            rm -f "$tmp"
            ;;
        # Scripts that only need help test (already passed)
        cloud-backup.sh|config-check.sh|motd-generator.sh|noba-completion.sh|noba-cron-setup.sh|noba-daily-digest.sh|noba-dashboard.sh|noba-setup.sh|noba-tui.sh|noba-update.sh|system-report.sh)
            ;;
        *)
            # Already passed help
            ;;
    esac

    echo -e "${GREEN}PASS${NC}"
    PASS=$((PASS+1))
done

# -------------------------------------------------------------------
# Cleanup
# -------------------------------------------------------------------
rm -rf "/tmp/test-backups"
rm -f "/tmp/test.png" "/tmp/test.pdf"

# -------------------------------------------------------------------
# Summary
# -------------------------------------------------------------------
echo ""
log_info "Results: $PASS passed, $FAIL failed, $SKIP skipped"

if [ "$FAIL" -gt 0 ]; then
    exit 1
else
    exit 0
fi
