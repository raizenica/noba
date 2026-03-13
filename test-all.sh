#!/bin/bash
# Create test image for images-to-pdf.sh
if [ ! -f "/tmp/test.png" ]; then
    if command -v magick &>/dev/null; then
        magick -size 100x100 xc:red /tmp/test.png 2>/dev/null
    elif command -v convert &>/dev/null; then
        convert -size 100x100 xc:red /tmp/test.png 2>/dev/null
    fi
fi
# test-all.sh – Comprehensive functionality test for all scripts with timeouts

set -u
set -o pipefail

cd "$(dirname "$0")" || exit 1

GREEN='\033[0;32m'
RED='\033[0;31m'
YELLOW='\033[1;33m'
NC='\033[0m'

PASS=0
FAIL=0
SKIP=0

# Helper: run a command with a timeout and suppress output
run_timeout() {
    timeout 5 "$@" >/dev/null 2>&1
}

# Create a dummy backup for backup-verifier.sh
DUMMY_BACKUP="/tmp/test-backups/$(date +%Y%m%d-%H%M%S)"
mkdir -p "$DUMMY_BACKUP/Documents"
echo "dummy content" > "$DUMMY_BACKUP/Documents/test.txt"

# Create a test image for images-to-pdf.sh if not present
if [ ! -f "/tmp/test.png" ] && command -v convert &>/dev/null; then
    convert -size 100x100 xc:red /tmp/test.png
fi

for script in *.sh; do
    # Skip library and test scripts
    [[ "$script" == "noba-lib.sh" || "$script" == "test-all.sh" ]] && continue

    echo -n "Testing $script ... "

    # Special handling for daemon scripts that should only be tested for help/version
    case "$script" in
        temperature-alert.sh|service-watch.sh|battery-watch.sh|noba-web.sh)
            # These scripts are long-running; only test --help and --version
            if run_timeout "$script" --help; then
                if grep -q "show_version" "$script" && ! run_timeout "$script" --version; then
                    echo -e "${RED}FAIL (--version)${NC}"
                    ((FAIL++))
                else
                    echo -e "${GREEN}PASS${NC}"
                    ((PASS++))
                fi
            else
                echo -e "${RED}FAIL (--help)${NC}"
                ((FAIL++))
            fi
            continue
            ;;
    esac

    # Special handling for backup-verifier.sh
    if [[ "$script" == "backup-verifier.sh" ]]; then
        if run_timeout "$script" --backup-dir "/tmp/test-backups" --num-files 1 --dry-run; then
            echo -e "${GREEN}PASS${NC}"
            ((PASS++))
        else
            echo -e "${RED}FAIL (dry-run on dummy backup)${NC}"
            ((FAIL++))
        fi
        continue
    fi

    # Special handling for images-to-pdf.sh
    if [[ "$script" == "images-to-pdf.sh" ]]; then
        if [ ! -f "/tmp/test.png" ]; then
            echo -e "${YELLOW}SKIP (no test image)${NC}"
            ((SKIP++))
            continue
        fi
        if run_timeout "$script" -o /tmp/test.pdf /tmp/test.png; then
            echo -e "${GREEN}PASS${NC}"
            ((PASS++))
        else
            echo -e "${RED}FAIL (conversion)${NC}"
            ((FAIL++))
        fi
        continue
    fi

    # Special handling for run-hogwarts-trainer.sh (needs trainer file)
    if [[ "$script" == "run-hogwarts-trainer.sh" ]]; then
        # Just check help
        if run_timeout "$script" --help; then
            echo -e "${GREEN}PASS${NC}"
            ((PASS++))
        else
            echo -e "${RED}FAIL (--help)${NC}"
            ((FAIL++))
        fi
        continue
    fi

    # For other scripts, check --help
    if ! run_timeout "$script" --help; then
        echo -e "${RED}FAIL (--help)${NC}"
        ((FAIL++))
        continue
    fi

    # Check --version if present
    if grep -q "show_version" "$script"; then
        if ! run_timeout "$script" --version; then
            echo -e "${RED}FAIL (--version)${NC}"
            ((FAIL++))
            continue
        fi
    fi

    # Dry-run for scripts that support it (excluding those already handled)
    case "$script" in
        backup-to-nas.sh|disk-sentinel.sh|organize-downloads.sh|undo-organizer.sh)
            if ! run_timeout "$script" --dry-run; then
                echo -e "${RED}FAIL (--dry-run)${NC}"
                ((FAIL++))
                continue
            fi
            ;;
        checksum.sh)
            tmp=$(mktemp)
            echo "test" > "$tmp"
            if ! run_timeout checksum.sh "$tmp"; then
                echo -e "${RED}FAIL (checksum generation)${NC}"
                ((FAIL++))
                rm -f "$tmp"
                continue
            fi
            rm -f "$tmp"
            ;;
        cloud-backup.sh)
            # Just help tested, --dry-run would need rclone configured
            ;;
        config-check.sh)
            # Just help tested
            ;;
        motd-generator.sh)
            # Just help tested
            ;;
        noba-completion.sh)
            # Just help tested
            ;;
        noba-cron-setup.sh)
            # Just help tested
            ;;
        noba-daily-digest.sh)
            # Just help tested
            ;;
        noba-dashboard.sh)
            # Just help tested
            ;;
        noba-setup.sh)
            # Just help tested
            ;;
        noba-tui.sh)
            # Just help tested
            ;;
        noba-update.sh)
            # Just help tested
            ;;
        system-report.sh)
            # Just help tested
            ;;
        *)
            # Already passed help
            ;;
    esac

    echo -e "${GREEN}PASS${NC}"
    ((PASS++))
done

# Cleanup
rm -rf "/tmp/test-backups"
rm -f "/tmp/test.png" "/tmp/test.pdf"

echo ""
echo "Results: $PASS passed, $FAIL failed, $SKIP skipped"
exit $FAIL
