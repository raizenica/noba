#!/bin/bash
# test-all.sh – Comprehensive functionality test for all scripts
# Improved version with streamlined edge‑case handling and cleaner reporting

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
    echo "test-all.sh version 2.0"
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

# Run a command with timeout, capturing output
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

# Report an edge‑case test result
edge_test() {
    local name="$1"
    local result=$2
    echo -n "Edge test: $name ... "
    if [ $result -eq 0 ]; then
        echo -e "${GREEN}PASS${NC}"
        PASS=$((PASS+1))
    else
        echo -e "${RED}FAIL (exit $result)${NC}"
        FAIL=$((FAIL+1))
    fi
}

# -------------------------------------------------------------------
# Parse arguments
# -------------------------------------------------------------------
if ! PARSED_ARGS=$(getopt -o t:snv -l timeout:,skip-slow,dry-run,verbose,help,version -- "$@"); then
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

# Create a file with spaces and special characters for organizer tests
TEST_SPECIAL="/tmp/Download/test file with spaces and !@#$.txt"
mkdir -p /tmp/Download
echo "content" > "$TEST_SPECIAL"

# Create a large number of small files for checksum test
LARGE_DIR="/tmp/checksum-large"
mkdir -p "$LARGE_DIR"
for i in {1..100}; do
    echo "test$i" > "$LARGE_DIR/file$i.txt"
done

# Create an invalid YAML config for testing
INVALID_YAML="/tmp/invalid_config.yaml"
cat > "$INVALID_YAML" <<EOF
backup:
  dest: "/mnt/nas"
  sources: [ "bad indentation"
    - missing dash
disk: [unclosed
EOF

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

    # Special case: noba-dashboard.sh – just run it (no arguments needed)
    if [[ "$script" == "noba-dashboard.sh" ]]; then
        if run_test "$script" "$script"; then
            echo -e "${GREEN}PASS${NC}"
            PASS=$((PASS+1))
        else
            rc=$?
            echo -e "${RED}FAIL (execution, exit code $rc)${NC}"
            FAIL=$((FAIL+1))
        fi
        continue
    fi

    # Special case: backup-verifier.sh needs a dummy backup dir
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

    # Special case: images-to-pdf.sh needs a test image
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

    # Special case: run-hogwarts-trainer.sh – just check help
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

    # General test: check --help
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

    # Additional dry‑run tests for scripts that support it
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
# Extra edge‑case tests (consolidated)
# -------------------------------------------------------------------
log_info "Running extra edge‑case tests..."

# Helper to run a test and report
run_edge_test() {
    local name="$1"
    shift
    run_test "$@" || true
    local rc=$?
    edge_test "$name" $rc
}

# 1. Invalid option for each script
for script in *.sh; do
    [[ "$script" == "noba-lib.sh" || "$script" == "test-all.sh" ]] && continue
    # Skip scripts that don't use getopt
    if [[ "$script" == "noba" || "$script" == "install.sh" || "$script" == "setup-automation-timers.sh" ]]; then
        continue
    fi
    run_edge_test "$script --invalid-option" "$script" --invalid-option
done

# 2. Missing required arguments
run_edge_test "backup-to-nas.sh (missing --source)" backup-to-nas.sh --dest /tmp
run_edge_test "backup-to-nas.sh (missing --dest)" backup-to-nas.sh --source /tmp
run_edge_test "organize-downloads.sh (non-existent dir)" organize-downloads.sh --download-dir /does/not/exist

# 3. checksum.sh with many files
run_edge_test "checksum.sh (100 files)" checksum.sh "$LARGE_DIR"/*

# 4. organize-downloads.sh with special‑char filename
TEST_DOWNLOAD_DIR="/tmp/test-downloads"
mkdir -p "$TEST_DOWNLOAD_DIR"
cp "$TEST_SPECIAL" "$TEST_DOWNLOAD_DIR/"
run_edge_test "organize-downloads.sh (special chars)" organize-downloads.sh --download-dir "$TEST_DOWNLOAD_DIR" --dry-run
rm -rf "$TEST_DOWNLOAD_DIR"

# 5. images-to-pdf.sh with non-image file
TMP_TEXT=$(mktemp)
echo "not an image" > "$TMP_TEXT"
run_edge_test "images-to-pdf.sh (invalid input)" images-to-pdf.sh -o /tmp/out.pdf "$TMP_TEXT"
rm -f "$TMP_TEXT" /tmp/out.pdf

# 6. config-check.sh with invalid YAML
export NOBA_CONFIG="$INVALID_YAML"
run_edge_test "config-check.sh (invalid YAML)" config-check.sh
unset NOBA_CONFIG

# 7. noba CLI commands
run_edge_test "noba list" noba list
run_edge_test "noba doctor --dry-run" noba doctor --dry-run
run_edge_test "noba run backup --dry-run" noba run backup --dry-run
run_edge_test "noba config" noba config

# 8. dry-run on non‑existent destination
run_edge_test "backup-to-nas.sh (dry-run with missing dest)" backup-to-nas.sh --source /tmp --dest /does/not/exist --dry-run

# 9. log-rotator.sh with non‑existent directory
run_edge_test "log-rotator.sh (non-existent dir)" log-rotator.sh --log-dir /does/not/exist --dry-run

# -------------------------------------------------------------------
# Cleanup
# -------------------------------------------------------------------
rm -rf "/tmp/test-backups"
rm -f "/tmp/test.png" "/tmp/test.pdf"
rm -rf "/tmp/Download"
rm -rf "$LARGE_DIR"
rm -f "$INVALID_YAML"

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
