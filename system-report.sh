#!/bin/bash
# system-report.sh – Generate HTML report of system health and email it

set -euo pipefail

SCRIPT_DIR="$(cd "$(dirname "${BASH_SOURCE[0]}")" && pwd)"
# shellcheck source=/dev/null
source "$SCRIPT_DIR/noba-lib.sh"

# -------------------------------------------------------------------
# Default configuration
# -------------------------------------------------------------------
REPORT_DIR="${REPORT_DIR:-$HOME/.local/share/noba}"
REPORT_FILE="${REPORT_FILE:-system-report-$(date +%Y%m%d).html}"
EMAIL="${EMAIL:-strikerke@gmail.com}"
SEND_EMAIL=true

# -------------------------------------------------------------------
# Load user configuration (if any)
# -------------------------------------------------------------------
load_config
if [ "$CONFIG_LOADED" = true ]; then
    # Override defaults
    logs_dir="$(get_config ".logs.dir" "$HOME/.local/share/noba")"
    logs_dir="${logs_dir/#\~/$HOME}"
    REPORT_DIR="$logs_dir"
    EMAIL="$(get_config ".email" "$EMAIL")"
fi

# -------------------------------------------------------------------
# Helper functions
# -------------------------------------------------------------------
show_version() {
    echo "system-report.sh version 1.0"
    exit 0
}

show_help() {
    cat <<EOF
Usage: $0 [OPTIONS]

Generate an HTML report of system health and optionally email it.

Options:
  -o, --output FILE   Output file name (default: $REPORT_FILE)
  -d, --dir DIR       Directory to save report (default: $REPORT_DIR)
  -e, --email ADDR    Email address to send report (default: $EMAIL)
  -n, --no-email      Do not send email, just save report
  --help              Show this help message
  --version           Show version information
EOF
    exit 0
}

# Send email with attachment (using mutt or mail)
send_report() {
    local subject="$1"
    local attachment="$2"
    if [ "$SEND_EMAIL" = false ] || [ -z "$EMAIL" ]; then
        log_info "Email not sent (disabled or no recipient)."
        return
    fi

    if command -v mutt &>/dev/null; then
        mutt -s "$subject" -a "$attachment" -- "$EMAIL" < /dev/null
        log_info "Report emailed to $EMAIL via mutt."
    elif command -v mail &>/dev/null; then
        mail -s "$subject" "$EMAIL" < /dev/null
        log_info "Report emailed to $EMAIL via mail (attachment may not work)."
    else
        log_warn "No mail program found – cannot send email."
    fi
}

# -------------------------------------------------------------------
# Parse command-line arguments
# -------------------------------------------------------------------
PARSED_ARGS=$(getopt -o o:d:e:n -l output:,dir:,email:,no-email,help,version -- "$@")
if [ $? -ne 0 ]; then
    show_help
fi
eval set -- "$PARSED_ARGS"

while true; do
    case "$1" in
        -o|--output)   REPORT_FILE="$2"; shift 2 ;;
        -d|--dir)      REPORT_DIR="$2"; shift 2 ;;
        -e|--email)    EMAIL="$2"; shift 2 ;;
        -n|--no-email) SEND_EMAIL=false; shift ;;
        --help)        show_help ;;
        --version)     show_version ;;
        --)            shift; break ;;
        *)             break ;;
    esac
done

# -------------------------------------------------------------------
# Pre-flight checks
# -------------------------------------------------------------------
check_deps df grep tail date hostname
# Optional tools: dnf, flatpak, mail/mutt – check at runtime

# Ensure report directory exists
mkdir -p "$REPORT_DIR"
REPORT_PATH="$REPORT_DIR/$REPORT_FILE"

# -------------------------------------------------------------------
# Gather system information
# -------------------------------------------------------------------
log_info "Generating system report: $REPORT_PATH"

# Disk usage (filter to real devices)
disk_usage=$(df -h | grep '^/dev/' || echo "No disk info")

# Last backup lines
backup_log="$HOME/.local/share/backup-to-nas.log"
if [ -f "$backup_log" ]; then
    last_backup=$(tail -5 "$backup_log" 2>/dev/null | sed 's/\x1b\[[0-9;]*m//g')  # strip ANSI
else
    last_backup="No backup log found"
fi

# Disk warnings
disk_log="$HOME/.local/share/disk-sentinel.log"
if [ -f "$disk_log" ]; then
    disk_warnings=$(grep -E "WARNING|exceeded" "$disk_log" 2>/dev/null | tail -5 || echo "None")
else
    disk_warnings="No disk sentinel log"
fi

# Updates
dnf_updates=0
flatpak_updates=0
if command -v dnf &>/dev/null; then
    dnf_updates=$(dnf check-update -q 2>/dev/null | wc -l)
fi
if command -v flatpak &>/dev/null; then
    flatpak_updates=$(flatpak remote-ls --updates 2>/dev/null | wc -l)
fi

# System load
load=$(uptime)

# -------------------------------------------------------------------
# Generate HTML report
# -------------------------------------------------------------------
cat > "$REPORT_PATH" <<EOF
<!DOCTYPE html>
<html>
<head>
    <title>System Report $(date)</title>
    <style>
        body { font-family: Arial, sans-serif; margin: 20px; }
        h1 { color: #333; }
        h2 { color: #666; border-bottom: 1px solid #ccc; }
        pre { background: #f4f4f4; padding: 10px; border-radius: 5px; }
    </style>
</head>
<body>
    <h1>System Report for $(hostname) – $(date)</h1>

    <h2>System Load</h2>
    <pre>$load</pre>

    <h2>Disk Usage</h2>
    <pre>$disk_usage</pre>

    <h2>Last Backup</h2>
    <pre>$last_backup</pre>

    <h2>Recent Disk Warnings</h2>
    <pre>$disk_warnings</pre>

    <h2>Available Updates</h2>
    <pre>DNF: $dnf_updates updates
Flatpak: $flatpak_updates updates</pre>
</body>
</html>
EOF

log_info "Report saved to $REPORT_PATH"

# -------------------------------------------------------------------
# Send email
# -------------------------------------------------------------------
send_report "System Report $(hostname) $(date)" "$REPORT_PATH"

log_info "Done."
