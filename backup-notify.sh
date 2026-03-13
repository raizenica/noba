
# Help handling

# Help handling

# Help handling

# Help handling

# Help handling

# Help handling

# Help handling

# Help handling

# Help handling

# Help handling

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
    echo "For detailed help, see the script documentation."
    exit 0
fi
if [ "$1" = "--version" ] || [ "$1" = "-v" ]; then
    echo "$(basename "$0") version 1.0"
    exit 0
fi

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
    echo "For detailed help, see the script documentation."
    exit 0
fi
if [ "$1" = "--version" ] || [ "$1" = "-v" ]; then
    echo "$(basename "$0") version 1.0"
    exit 0
fi

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
    echo "For detailed help, see the script documentation."
    exit 0
fi
if [ "$1" = "--version" ] || [ "$1" = "-v" ]; then
    echo "$(basename "$0") version 1.0"
    exit 0
fi

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
    echo "For detailed help, see the script documentation."
    exit 0
fi
if [ "$1" = "--version" ] || [ "$1" = "-v" ]; then
    echo "$(basename "$0") version 1.0"
    exit 0
fi

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
    echo "For detailed help, see the script documentation."
    exit 0
fi
if [ "$1" = "--version" ] || [ "$1" = "-v" ]; then
    echo "$(basename "$0") version 1.0"
    exit 0
fi

if [ "$1" = "--help" ] || [ "$1" = "-h" ]; then
    echo "Usage: $(basename "$0") [OPTIONS]"
    echo "For detailed help, see the script documentation."
    exit 0
fi
if [ "$1" = "--version" ] || [ "$1" = "-v" ]; then
    echo "$(basename "$0") version 1.0"
    exit 0
fi

#!/bin/bash
# backup-notify.sh – Send desktop notification about last backup status

# Load configuration
load_config
if [ "$CONFIG_LOADED" = true ]; then
    # Override defaults with config values (script-specific)
    # Example:
    # VAR=$(get_config ".${script%.sh}.var" "$VAR")
fi

# Load configuration
load_config
if [ "$CONFIG_LOADED" = true ]; then
    # Override defaults with config values (script-specific)
    # Example:
    # VAR=$(get_config ".${script%.sh}.var" "$VAR")
fi

set -u
set -o pipefail

# Script directory and library
SCRIPT_DIR="$(cd "$(dirname "${BASH_SOURCE[0]}")" && pwd)"
source "$SCRIPT_DIR/noba-lib.sh"

# Version
show_version() {
    echo "backup-notify.sh version 1.0"
    exit 0
}

# Help
show_help() {
    cat <<EOF
Usage: $0 [OPTIONS]

Send a desktop notification about the last backup status.

Options:
  --help        Show this help message
  --version     Show version information
EOF
    exit 0
}

# Parse arguments
while [[ $# -gt 0 ]]; do
    case $1 in
        --help) show_help ;;
        --version) show_version ;;
        *) echo "Unknown option: $1" >&2; show_help ;;
    esac
done

LOG_FILE="$HOME/.local/share/backup-to-nas.log"

if [ ! -f "$LOG_FILE" ]; then
    log_error "No backup log found."
    exit 1
fi

last_line=$(tail -1 "$LOG_FILE" 2>/dev/null)

if echo "$last_line" | grep -qi "error"; then
    urgency="critical"
    summary="⚠ Backup Failed"
elif echo "$last_line" | grep -qi "complete"; then
    urgency="normal"
    summary="✅ Backup Completed"
else
    urgency="low"
    summary="ℹ Backup Status Unknown"
fi

if command -v notify-send &>/dev/null; then
    notify-send -u "$urgency" "$summary" "$last_line"
elif command -v kdialog &>/dev/null; then
    kdialog --passivepopup "$last_line" 5 --title "$summary"
else
    echo "$summary: $last_line"
fi
