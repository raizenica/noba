#!/bin/bash
# noba-cron-setup.sh – Interactive setup of cron jobs for automation scripts

set -euo pipefail

SCRIPT_DIR="$(cd "$(dirname "${BASH_SOURCE[0]}")" && pwd)"
# shellcheck source=/dev/null
source "$SCRIPT_DIR/noba-lib.sh"

# -------------------------------------------------------------------
# Default configuration
# -------------------------------------------------------------------
SCRIPTS_DIR="${SCRIPTS_DIR:-$HOME/.local/bin}"
CRON_LOG_DIR="$HOME/.local/share/cron-logs"
LIST_ONLY=false
REMOVE_MODE=false

# Scripts suitable for automation (can be overridden in config)
AUTOMATION_SCRIPTS=(
    "backup-to-nas.sh"
    "disk-sentinel.sh"
    "organize-downloads.sh"
)

# -------------------------------------------------------------------
# Load user configuration (if any)
# -------------------------------------------------------------------
load_config || true   # Ignore non-zero exit (yq missing or config missing)
if [ "$CONFIG_LOADED" = true ]; then
    # Optionally override the list from config – ignore failure if key missing
    scripts_from_config=$(get_config_array ".cron.scripts" || true)
    if [ -n "$scripts_from_config" ]; then
        mapfile -t AUTOMATION_SCRIPTS <<< "$scripts_from_config"
    fi
    CRON_LOG_DIR="$(get_config ".logs.dir" "$CRON_LOG_DIR")/cron"
fi

# -------------------------------------------------------------------
# Helper functions
# -------------------------------------------------------------------
show_version() {
    echo "noba-cron-setup.sh version 1.0"
    exit 0
}

show_help() {
    cat <<EOF
Usage: $0 [OPTIONS]

Interactive cron setup for Nobara automation scripts.

Options:
  --list       List currently installed cron jobs from these scripts
  --remove     Remove a specific cron job (interactive)
  --help       Show this help message
  --version    Show version information
EOF
    exit 0
}

# List current cron jobs matching our scripts
list_cron_jobs() {
    log_info "Current cron jobs for user $USER:"
    local jobs
    jobs=$(crontab -l 2>/dev/null | grep -E "($(IFS=\|; echo "${AUTOMATION_SCRIPTS[*]}"))" || true)
    if [ -n "$jobs" ]; then
        echo "$jobs"
    else
        echo "  No automation scripts found in crontab."
    fi
}

# -------------------------------------------------------------------
# Parse arguments
# -------------------------------------------------------------------
PARSED_ARGS=$(getopt -o '' -l list,remove,help,version -- "$@")
if [ $? -ne 0 ]; then
    show_help
fi
eval set -- "$PARSED_ARGS"

while true; do
    case "$1" in
        --list)    LIST_ONLY=true; shift ;;
        --remove)  REMOVE_MODE=true; shift ;;
        --help)    show_help ;;
        --version) show_version ;;
        --)        shift; break ;;
        *)         break ;;
    esac
done

# -------------------------------------------------------------------
# Pre-flight
# -------------------------------------------------------------------
mkdir -p "$CRON_LOG_DIR"

# -------------------------------------------------------------------
# List mode
# -------------------------------------------------------------------
if [ "$LIST_ONLY" = true ]; then
    list_cron_jobs
    exit 0
fi

# -------------------------------------------------------------------
# Remove mode
# -------------------------------------------------------------------
if [ "$REMOVE_MODE" = true ]; then
    log_info "Select a cron job to remove:"
    # Get current automation jobs with line numbers
    jobs=()
    while IFS= read -r line; do
        jobs+=("$line")
    done < <(crontab -l 2>/dev/null | grep -n -E "($(IFS=\|; echo "${AUTOMATION_SCRIPTS[*]}"))" || true)

    if [ ${#jobs[@]} -eq 0 ]; then
        log_info "No automation cron jobs found."
        exit 0
    fi

    for i in "${!jobs[@]}"; do
        echo "$((i+1)). ${jobs[$i]#*:}"
    done

    read -r -p "Enter number to remove (or 0 to cancel): " choice
    if [[ "$choice" =~ ^[0-9]+$ ]] && [ "$choice" -gt 0 ] && [ "$choice" -le ${#jobs[@]} ]; then
        line_num=$(echo "${jobs[$((choice-1))]}" | cut -d: -f1)
        crontab -l | sed "${line_num}d" | crontab -
        log_success "Removed job."
    else
        log_info "Cancelled."
    fi
    exit 0
fi

# -------------------------------------------------------------------
# Interactive setup
# -------------------------------------------------------------------
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
    log_info "Exiting."
    exit 0
fi

script_name="${AUTOMATION_SCRIPTS[$((choice-1))]}"
script_path="$SCRIPTS_DIR/$script_name"
if [ ! -f "$script_path" ]; then
    log_error "$script_name not found in $SCRIPTS_DIR"
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

# Simple validation
if ! [[ "$schedule" =~ ^([0-9*/-]+[[:space:]]){4}[0-9*/-]+$ ]]; then
    log_warn "Invalid cron format. Using default."
    schedule="0 2 * * *"
fi

# Ask for quiet mode
read -r -p "Add --quiet flag? (y/n, default: y): " quiet
quiet_flag=""
if [[ ! "$quiet" =~ ^[Nn]$ ]]; then
    quiet_flag="--quiet"
fi

# Log file
log_file="$CRON_LOG_DIR/${script_name%.sh}.log"

# Build cron line
cron_line="$schedule $script_path $quiet_flag >> $log_file 2>&1"

# Check if job already exists
if crontab -l 2>/dev/null | grep -Fq "$script_path"; then
    log_warn "A job for $script_name already exists:"
    crontab -l | grep "$script_path"
    read -r -p "Overwrite? (y/n): " overwrite
    if [[ "$overwrite" =~ ^[Yy]$ ]]; then
        crontab -l | grep -vF "$script_path" | crontab -
        (crontab -l 2>/dev/null; echo "$cron_line") | crontab -
        log_success "Job updated."
    else
        log_info "No changes."
    fi
else
    (crontab -l 2>/dev/null; echo "$cron_line") | crontab -
    log_success "Job added: $cron_line"
fi

log_info "Logs will be written to $log_file"
