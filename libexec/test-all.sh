#!/bin/bash
# Copyright (c) 2024-2026 Kevin Van Nieuwenhove. All rights reserved.
# NOBA Command Center — Licensed under Apache 2.0.
# test-all.sh – Comprehensive functionality test for all scripts
# Version: 2.2.0

set -euo pipefail
trap 'echo "Error at line $LINENO (last command: $BASH_COMMAND)" >&2' ERR

SCRIPT_DIR="$(cd "$(dirname "${BASH_SOURCE[0]}")" && pwd)"
# shellcheck source=/dev/null
source "$SCRIPT_DIR/lib/noba-lib.sh"

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
    echo "test-all.sh version 2.2.0"
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

# Asserts the exit code matches expectations (for negative testing)
edge_test() {
    local name="$1"
    local actual_rc=$2
    local expected_rc=$3
    echo -n "Edge test: $name ... "

    if [[ $actual_rc -eq $expected_rc ]]; then
        echo -e "${GREEN}PASS${NC}"
        PASS=$((PASS+1))
    else
        echo -e "${RED}FAIL (Got exit code $actual_rc, expected $expected_rc)${NC}"
        FAIL=$((FAIL+1))
    fi
}

run_edge_test() {
    local expected_rc="$1"
    local name="$2"
    shift 2
    # Disable set -e for the test execution so it doesn't crash the harness
    set +e
    run_test "$name" "$@"
    local rc=$?
    set -e
    edge_test "$name" "$rc" "$expected_rc"
}

# -------------------------------------------------------------------
# Parse arguments
# -------------------------------------------------------------------
if ! PARSED_ARGS=$(getopt -o t:snv -l timeout:,skip-slow,dry-run,verbose,help,version -- "$@"); then
    log_error "Failed to parse arguments. Use --help for usage."
    exit 1
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
        *) log_error "Invalid argument: $1"; exit 1 ;;
    esac
done

# -------------------------------------------------------------------
# Prepare test environment
# -------------------------------------------------------------------
cd "$SCRIPT_DIR" || { log_error "Cannot cd to $SCRIPT_DIR"; exit 1; }

DUMMY_BACKUP="${TMPDIR:-/tmp}/test-backups/$(date +%Y%m%d-%H%M%S)"
mkdir -p "$DUMMY_BACKUP/Documents"
echo "dummy content" > "$DUMMY_BACKUP/Documents/test.txt"

TEST_IMAGE="${TMPDIR:-/tmp}/test.png"
if [ ! -f "$TEST_IMAGE" ]; then
    if command -v magick &>/dev/null; then
        magick -size 100x100 xc:red "$TEST_IMAGE" 2>/dev/null || true
    elif command -v convert &>/dev/null; then
        convert -size 100x100 xc:red "$TEST_IMAGE" 2>/dev/null || true
    fi
fi

TEST_SPECIAL="${TMPDIR:-/tmp}/Download/test file with spaces and !@#$.txt"
mkdir -p "${TMPDIR:-/tmp}/Download"
echo "content" > "$TEST_SPECIAL"

LARGE_DIR="${TMPDIR:-/tmp}/checksum-large"
mkdir -p "$LARGE_DIR"
for i in {1..10}; do
    echo "test$i" > "$LARGE_DIR/file$i.txt"
done

INVALID_YAML="${TMPDIR:-/tmp}/invalid_config.yaml"
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
    [[ "$script" == "noba-lib.sh" || "$script" == "test-all.sh" || "$script" == "install.sh" || "$script" == "noba-completion.sh" ]] && continue

    if [ "$SKIP_SLOW" = true ]; then
        case "$script" in
            temperature-alert.sh|service-watch.sh|noba-web.sh|noba-tui.sh)
                log_debug "Skipping slow script: $script"
                SKIP=$((SKIP+1))
                continue
                ;;
        esac
    fi

    echo -n "Testing $script ... "

    # Check --help (every script should support this)
    if ! run_test "$script" "./$script" --help; then
        echo -e "${RED}FAIL (--help)${NC}"
        FAIL=$((FAIL+1))
        continue
    fi

    # Check --version if it's implemented
    if grep -q "show_version" "$script"; then
        if ! run_test "$script" "./$script" --version; then
            echo -e "${RED}FAIL (--version)${NC}"
            FAIL=$((FAIL+1))
            continue
        fi
    fi

    # Additional dry-run tests for supported scripts
    # Set up minimal environment so dry-run works in CI
    case "$script" in
        backup-to-nas.sh|disk-sentinel.sh|log-rotator.sh)
            if ! run_test "$script" "./$script" --dry-run; then
                echo -e "${RED}FAIL (--dry-run)${NC}"
                FAIL=$((FAIL+1))
                continue
            fi
            ;;
        organize-downloads.sh)
            mkdir -p "${TMPDIR:-/tmp}/noba-test-dl"
            if ! DOWNLOAD_DIR="${TMPDIR:-/tmp}/noba-test-dl" run_test "$script" "./$script" --dry-run; then
                echo -e "${RED}FAIL (--dry-run)${NC}"
                FAIL=$((FAIL+1))
                rm -rf "${TMPDIR:-/tmp}/noba-test-dl"
                continue
            fi
            rm -rf "${TMPDIR:-/tmp}/noba-test-dl"
            ;;
        undo-organizer.sh)
            mkdir -p "${TMPDIR:-/tmp}/noba-test-dl"
            if ! DOWNLOAD_DIR="${TMPDIR:-/tmp}/noba-test-dl" run_test "$script" "./$script" --dry-run; then
                echo -e "${RED}FAIL (--dry-run)${NC}"
                FAIL=$((FAIL+1))
                rm -rf "${TMPDIR:-/tmp}/noba-test-dl"
                continue
            fi
            rm -rf "${TMPDIR:-/tmp}/noba-test-dl"
            ;;
        cloud-backup.sh)
            # Requires rclone — skip if not available
            if command -v rclone &>/dev/null; then
                if ! run_test "$script" "./$script" --dry-run; then
                    echo -e "${RED}FAIL (--dry-run)${NC}"
                    FAIL=$((FAIL+1))
                    continue
                fi
            else
                echo -n -e "${YELLOW}(skipped: no rclone) ${NC}"
            fi
            ;;
        backup-verifier.sh)
            # Needs a configured backup destination to run — just test --help
            ;;
        images-to-pdf.sh)
            if [ -f "$TEST_IMAGE" ]; then
                if ! run_test "$script" "./$script" -o "${TMPDIR:-/tmp}/test.pdf" "$TEST_IMAGE"; then
                    echo -e "${RED}FAIL (conversion)${NC}"
                    FAIL=$((FAIL+1))
                    continue
                fi
            else
                echo -n -e "${YELLOW}(skipped pdf conversion) ${NC}"
            fi
            ;;
        checksum.sh)
            tmp=$(mktemp)
            echo "test" > "$tmp"
            if ! run_test "$script" "./$script" "$tmp"; then
                echo -e "${RED}FAIL (checksum generation)${NC}"
                FAIL=$((FAIL+1))
                rm -f "$tmp"
                continue
            fi
            rm -f "$tmp"
            ;;
    esac

    echo -e "${GREEN}PASS${NC}"
    PASS=$((PASS+1))
done

# -------------------------------------------------------------------
# Extra edge-case tests (Negative Testing)
# -------------------------------------------------------------------
log_info "Running edge-case tests (Negative Testing)..."

# 1. Invalid option for each script (Expect Failure: 1)
for script in *.sh; do
    [[ "$script" == "noba-lib.sh" || "$script" == "test-all.sh" || "$script" == "install.sh" ]] && continue
    # Skip wrapper and setup scripts without strict getopt
    if [[ "$script" == "setup-automation-timers.sh" || "$script" == "noba-completion.sh" ]]; then
        continue
    fi
    run_edge_test 1 "$script (--invalid-option)" "./$script" --invalid-option
done

# 2. Missing required arguments (Expect Failure: 1)
run_edge_test 1 "backup-to-nas.sh (missing --source)" ./backup-to-nas.sh --dest "${TMPDIR:-/tmp}"
# Note: --source without --dest may hang reading config — skip timeout-prone test
DOWNLOAD_DIR=/does/not/exist run_edge_test 0 "organize-downloads.sh (non-existent dir)" ./organize-downloads.sh

# 3. checksum.sh with many files (Expect Success: 0)
run_edge_test 0 "checksum.sh (10 files)" ./checksum.sh "$LARGE_DIR"/*

# 4. organize-downloads.sh with special characters (Expect Success: 0)
TEST_DOWNLOAD_DIR="${TMPDIR:-/tmp}/test-downloads"
mkdir -p "$TEST_DOWNLOAD_DIR"
echo "special content" > "$TEST_DOWNLOAD_DIR/test file with spaces.txt"
DOWNLOAD_DIR="$TEST_DOWNLOAD_DIR" run_edge_test 0 "organize-downloads.sh (special chars)" ./organize-downloads.sh --dry-run
rm -rf "$TEST_DOWNLOAD_DIR"

# 5. config-check.sh with invalid YAML (config-check only verifies tool deps, not YAML)
export NOBA_CONFIG="$INVALID_YAML"
run_edge_test 0 "config-check.sh (invalid YAML)" ./config-check.sh -q
unset NOBA_CONFIG

# 6. noba CLI commands (Expect Success/Failure where appropriate)
if [ -x "./noba" ]; then
    run_edge_test 0 "noba list" ./noba list
    run_edge_test 0 "noba doctor --dry-run" ./noba doctor --dry-run
    run_edge_test 0 "noba backup --dry-run" ./noba backup --dry-run
    run_edge_test 1 "noba unknown_cmd" ./noba made_up_command
fi

# 7. dry-run on non-existent destination (Expect Success: 0, it skips checks)
run_edge_test 0 "backup-to-nas.sh (dry-run with missing dest)" ./backup-to-nas.sh --source "${TMPDIR:-/tmp}" --dest /does/not/exist --dry-run

# -------------------------------------------------------------------
# Cleanup
# -------------------------------------------------------------------
rm -rf "${TMPDIR:-/tmp}/test-backups"
rm -f "${TMPDIR:-/tmp}/test.png" "${TMPDIR:-/tmp}/test.pdf"
rm -rf "${TMPDIR:-/tmp}/Download"
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
