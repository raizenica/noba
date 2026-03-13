#!/bin/bash
SCRIPT_DIR="$(cd "$(dirname "${BASH_SOURCE[0]}")" && pwd)"
source "$SCRIPT_DIR/noba-lib.sh"
# noba-cron-setup.sh – Interactive setup of cron jobs for automation scripts

set -u
set -o pipefail

# Configuration
SCRIPTS_DIR="${SCRIPTS_DIR:-$HOME/.local/bin}"
CRON_LOG_DIR="$HOME/.local/share/cron-logs"
mkdir -p "$CRON_LOG_DIR"

# Colors for interactive output
RED='\033[0;31m'
GREEN='\033[0;32m'
YELLOW='\033[1;33m'
NC='\033[0m'

usage() {
    cat <<EOF
Usage: $0 [options]

Interactive cron setup for Nobara automation scripts.

Options:
  --list       List currently installed cron jobs from these scripts
  --remove     Remove a specific cron job (interactive)
  --help       Show this help
EOF
    exit 0
}

# Parse options
LIST_ONLY=false
REMOVE_MODE=false
while [[ $# -gt 0 ]]; do
    case $1 in
        --list)
            LIST_ONLY=true
            shift
            ;;
        --remove)
            REMOVE_MODE=true
            shift
            ;;
        --help)
            usage
            ;;
        *)
            echo "Unknown option: $1" >&2
            exit 1
            ;;
    esac
done

# List scripts suitable for automation
AUTOMATION_SCRIPTS=(
    "backup-to-nas.sh"
    "disk-sentinel.sh"
    "organize-downloads.sh"
)

# Function to list current cron jobs
list_cron_jobs() {
    echo -e "${YELLOW}Current cron jobs for user $USER:${NC}"
    crontab -l 2>/dev/null | grep -E "($(IFS=\|; echo "${AUTOMATION_SCRIPTS[*]}"))" || echo "  No automation scripts found in crontab."
}

# If --list, just show and exit
if [ "$LIST_ONLY" = true ]; then
    list_cron_jobs
    exit 0
fi

# If --remove, run removal interactively
if [ "$REMOVE_MODE" = true ]; then
    echo -e "${YELLOW}Select a cron job to remove:${NC}"
    # Get current automation jobs
    mapfile -t jobs < <(crontab -l 2>/dev/null | grep -n -E "($(IFS=\|; echo "${AUTOMATION_SCRIPTS[*]}"))")
    if [ ${#jobs[@]} -eq 0 ]; then
        echo "No automation cron jobs found."
        exit 0
    fi
    for i in "${!jobs[@]}"; do
        echo "$((i+1)). ${jobs[$i]#*:}"
    done
    read -r -p "Enter number to remove (or 0 to cancel): " choice
    if [[ "$choice" =~ ^[0-9]+$ ]] && [ "$choice" -gt 0 ] && [ "$choice" -le ${#jobs[@]} ]; then
        line_num=$(echo "${jobs[$((choice-1))]}" | cut -d: -f1)
        crontab -l | sed "${line_num}d" | crontab -
        echo -e "${GREEN}Removed job.${NC}"
    else
        echo "Cancelled."
    fi
    exit 0
fi

# Interactive setup
echo -e "${GREEN}=== Nobara Cron Setup ===${NC}"
echo "This will help you schedule automation scripts."
echo "Available scripts:"
for i in "${!AUTOMATION_SCRIPTS[@]}"; do
    script="${AUTOMATION_SCRIPTS[$i]}"
    path="$SCRIPTS_DIR/$script"
    if [ -f "$path" ]; then
        echo "  $((i+1)). $script (found)"
    else
        echo "  $((i+1)). $script ${RED}(not found)${NC}"
    fi
done

read -r -p "Enter script number to schedule (or 0 to exit): " choice
if ! [[ "$choice" =~ ^[0-9]+$ ]] || [ "$choice" -eq 0 ] || [ "$choice" -gt ${#AUTOMATION_SCRIPTS[@]} ]; then
    echo "Exiting."
    exit 0
fi

script_name="${AUTOMATION_SCRIPTS[$((choice-1))]}"
script_path="$SCRIPTS_DIR/$script_name"
if [ ! -f "$script_path" ]; then
    echo -e "${RED}Error: $script_name not found in $SCRIPTS_DIR${NC}"
    exit 1
fi

# Ask for schedule
echo "Specify schedule (cron format). Examples:"
echo "  Daily at 2 AM   : 0 2 * * *"
echo "  Every 6 hours   : 0 */6 * * *"
echo "  Hourly          : 0 * * * *"
echo "  Every Monday at 3 AM: 0 3 * * 1"
read -r -p "Enter cron schedule (default: 0 2 * * *): " schedule
schedule=${schedule:-"0 2 * * *"}

# Validate basic cron format (simplified)
if ! [[ "$schedule" =~ ^([0-9*/-]+[[:space:]]){4}[0-9*/-]+$ ]]; then
    echo -e "${RED}Invalid cron format. Using default.${NC}"
    schedule="0 2 * * *"
fi

# Ask for quiet mode
read -r -p "Add --quiet flag? (y/n, default: y): " quiet
quiet_flag=""
if [[ ! "$quiet" =~ ^[Nn]$ ]]; then
    quiet_flag="--quiet"
fi

# Log file for this job
log_file="$CRON_LOG_DIR/${script_name%.sh}.log"

# Build cron line
cron_line="$schedule $script_path $quiet_flag >> $log_file 2>&1"

# Check if job already exists
if crontab -l 2>/dev/null | grep -Fq "$script_path"; then
    echo -e "${YELLOW}A job for $script_name already exists:${NC}"
    crontab -l | grep "$script_path"
    read -r -p "Overwrite? (y/n): " overwrite
    if [[ "$overwrite" =~ ^[Yy]$ ]]; then
        crontab -l | grep -vF "$script_path" | crontab -
        (crontab -l 2>/dev/null; echo "$cron_line") | crontab -
        echo -e "${GREEN}Job updated.${NC}"
    else
        echo "No changes."
    fi
else
    (crontab -l 2>/dev/null; echo "$cron_line") | crontab -
    echo -e "${GREEN}Job added:${NC} $cron_line"
fi

echo "Logs will be written to $log_file"
