#!/bin/bash
# debug-failures.sh – Run failing scripts manually to see errors


# Basic help and version handling

# Basic help and version handling

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
    echo "For more information, see the script\x27s documentation or use --help on individual scripts."
    exit 0
fi
if [ "$1" = "--version" ] || [ "$1" = "-v" ]; then
    echo "$(basename "$0") version 1.0"
    exit 0
fi

if [ "$1" = "--help" ] || [ "$1" = "-h" ]; then
    echo "Usage: $(basename "$0") [OPTIONS]"
    echo "For more information, see the script\x27s documentation or use --help on individual scripts."
    exit 0
fi
if [ "$1" = "--version" ] || [ "$1" = "-v" ]; then
    echo "$(basename "$0") version 1.0"
    exit 0
fi

set -u
set -o pipefail

cd "$(dirname "$0")" || exit 1

FAILING_SCRIPTS=(
    "backup-to-nas.sh"
    "backup-verifier.sh"
    "checksum.sh"
    "disk-sentinel.sh"
    "fix-test-failures.sh"
    "images-to-pdf.sh"
    "organize-downloads.sh"
    "run-hogwarts-trainer.sh"
    "undo-organizer.sh"
)

for script in "${FAILING_SCRIPTS[@]}"; do
    echo "=== Testing $script ==="
    if [[ "$script" == "backup-verifier.sh" ]]; then
        ./"$script" --backup-dir "/tmp/test-backups" --num-files 1 --dry-run
    elif [[ "$script" == "images-to-pdf.sh" ]]; then
        if [ -f "/tmp/test.png" ]; then
            ./"$script" -o /tmp/test.pdf /tmp/test.png
        else
            echo "Test image missing"
        fi
    else
        ./"$script" --dry-run 2>&1 | head -5
    fi
    echo "Exit code: $?"
    echo "------------------------"
done
