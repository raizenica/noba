#!/bin/bash
# noba-cron-setup.sh – Interactive setup of cron jobs for automation scripts
# Improved version with dry-run, better validation, and robust error handling

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
DRY_RUN=false
DEFAULT_SCHEDULE="0 2 * * *"

# Scripts suitable for automation (can be overridden in config)
AUTOMATION_SCRIPTS=(
    "backup-to-nas.sh"
    "disk-sentinel.sh"
    "organize-downloads.sh"
)

# -------------------------------------------------------------------
# Load user configuration (if any)
# -------------------------------------------------------------------
load_config || true
if [ "$CONFIG_LOADED" = true ]; then
    scripts_from_config=$(get_config_array ".cron.scripts" || true)
    if [ -n "$scripts_from_config" ]; then
        mapfile -t AUTOMATION_SCRIPTS <<< "$scripts_from_config"
    fi
    CRON_LOG_DIR="$(get_config ".logs.dir" "$CRON_LOG_DIR")/cron"
    DEFAULT_SCHEDULE="$(get_config ".cron.default_schedule" "$DEFAULT_SCHEDULE")"
fi

# -------------------------------------------------------------------
# Helper functions
# -------------------------------------------------------------------
show_version() {
    echo "noba-cron-setup.sh version 2.0"
    exit 0
}

show_help() {
    cat <<EOF
Usage: $0 [OPTIONS]

Interactive cron setup for Nobara automation scripts.

Options:
  --list       List currently installed cron jobs from these scripts
  --remove     Remove a specific cron job (interactive)
  --dry-run    Show what would be done without modifying crontab
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

# Check if crontab command is available
check_crontab() {
    if ! command -v crontab &>/dev/null; then
        log_error "crontab command not found. Please install cron (e.g., 'sudo dnf install cronie')."
        exit 1
    fi
}

# -------------------------------------------------------------------
# Parse arguments
# -------------------------------------------------------------------
if ! PARSED_ARGS=$(getopt -o '' -l list,remove,dry-run,help,version -- "$@"); then
    show_help
fi
eval set -- "$PARSED_ARGS"

while true; do
    case "$1" in
        --list)     LIST_ONLY=true; shift ;;
        --remove)   REMOVE_MODE=true; shift ;;
        --dry-run)  DRY_RUN=true; shift ;;
        --help)     show_help ;;
        --version)  show_version ;;
        --)         shift; break ;;
        *)          break ;;
    esac
done

# -------------------------------------------------------------------
# Pre-flight
# -------------------------------------------------------------------
check_crontab
mkdir -p "$CRON_LOG_DIR" || {
    log_error "Cannot create log directory $CRON_LOG_DIR"
    exit 1
}

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
    # Get current crontab content (handle empty crontab)
    current_crontab=$(crontab -l 2>/dev/null || true)
    if [ -z "$current_crontab" ]; then
        log_info "No crontab exists for user $USER."
        exit 0
    fi

    # Find lines with automation scripts
    jobs=()
    while IFS= read -r line; do
        jobs+=("$line")
    done < <(echo "$current_crontab" | grep -n -E "($(IFS=\|; echo "${AUTOMATION_SCRIPTS[*]}"))" || true)

    if [ ${#jobs[@]} -eq 0 ]; then
        log_info "No automation cron jobs found."
        exit 0
    fi

    echo -e "${GREEN}Select a cron job to remove:${NC}"
    for i in "${!jobs[@]}"; do
        echo "$((i+1)). ${jobs[$i]#*:}"
    done

    read -r -p "Enter number to remove (or 0 to cancel): " choice
    if [[ "$choice" =~ ^[0-9]+$ ]] && [ "$choice" -gt 0 ] && [ "$choice" -le ${#jobs[@]} ]; then
        line_num=$(echo "${jobs[$((choice-1))]}" | cut -d: -f1)
        if [ "$DRY_RUN" = true ]; then
            log_info "[DRY RUN] Would remove line $line_num:"
            echo "${jobs[$((choice-1))]#*:}"
        else
            echo "$current_crontab" | sed "${line_num}d" | crontab -
            log_success "Removed job."
        fi
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
read -r -p "Enter cron schedule (default: $DEFAULT_SCHEDULE): " schedule
schedule=${schedule:-$DEFAULT_SCHEDULE}

# Simple validation (cron pattern: 5 fields separated by spaces)
if ! [[ "$schedule" =~ ^([0-9*/-]+[[:space:]]){4}[0-9*/-]+$ ]]; then
    log_warn "Invalid cron format. Using default: $DEFAULT_SCHEDULE"
    schedule="$DEFAULT_SCHEDULE"
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
current_crontab=$(crontab -l 2>/dev/null || true)
if echo "$current_crontab" | grep -Fq "$script_path"; then
    log_warn "A job for $script_name already exists:"
    echo "$current_crontab" | grep "$script_path"
    read -r -p "Overwrite? (y/n): " overwrite
    if [[ "$overwrite" =~ ^[Yy]$ ]]; then
        # Remove existing line(s) with this script
        new_crontab=$(echo "$current_crontab" | grep -vF "$script_path")
        if [ "$DRY_RUN" = true ]; then
            log_info "[DRY RUN] Would replace with:"
            echo "$cron_line"
        else
            (echo "$new_crontab"; echo "$cron_line") | crontab -
            log_success "Job updated."
        fi
    else
        log_info "No changes."
    fi
else
    if [ "$DRY_RUN" = true ]; then
        log_info "[DRY RUN] Would add: $cron_line"
    else
        (echo "$current_crontab"; echo "$cron_line") | crontab -
        log_success "Job added: $cron_line"
    fi
fi

log_info "Logs will be written to $log_file"
