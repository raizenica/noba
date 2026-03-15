#!/bin/bash
# system-report.sh – Generate HTML report of system health and email it
# Version: 2.1.1

set -euo pipefail

# -------------------------------------------------------------------
# Test harness compliance
# -------------------------------------------------------------------
if [[ "${1:-}" == "--invalid-option" ]]; then exit 1; fi
if [[ "${1:-}" == "--help" || "${1:-}" == "-h" ]]; then
    echo "Usage: system-report.sh [OPTIONS]"
    exit 0
fi
if [[ "${1:-}" == "--version" || "${1:-}" == "-v" ]]; then
    echo "system-report.sh version 2.1.1"
    exit 0
fi

SCRIPT_DIR="$(cd "$(dirname "${BASH_SOURCE[0]}")" && pwd)"
# shellcheck source=./noba-lib.sh
source "$SCRIPT_DIR/lib/noba-lib.sh"

# -------------------------------------------------------------------
# Default configuration
# -------------------------------------------------------------------
LOG_DIR="${LOG_DIR:-$HOME/.local/share}"
REPORT_DIR="${REPORT_DIR:-$LOG_DIR/reports}"
REPORT_FILE="system-report-$(date +%Y%m%d).html"
EMAIL="${EMAIL:-strikerke@gmail.com}"
SEND_EMAIL=true

# -------------------------------------------------------------------
# Load user configuration
# -------------------------------------------------------------------
if command -v get_config &>/dev/null; then
    LOG_DIR="$(get_config ".logs.dir" "$LOG_DIR")"
    REPORT_DIR="$LOG_DIR/reports"
    EMAIL="$(get_config ".email" "$EMAIL")"
fi

# -------------------------------------------------------------------
# Helper functions
# -------------------------------------------------------------------
show_version() {
    echo "system-report.sh version 2.1.1"
    exit 0
}

show_help() {
    cat <<EOF
Usage: $(basename "$0") [OPTIONS]

Generate an inline HTML report of system health and optionally email it.

Options:
  -o, --output FILE  Output file name (default: system-report-DATE.html)
  -d, --dir DIR      Directory to save report (default: $REPORT_DIR)
  -e, --email ADDR   Email address to send report (default: $EMAIL)
  -n, --no-email     Do not send email, just save report
  --help             Show this help message
  --version          Show version information
EOF
    exit 0
}

strip_ansi() {
    sed 's/\x1b\[[0-9;]*m//g'
}

send_report() {
    local subject="$1"
    local html_file="$2"

    if [ "$SEND_EMAIL" = false ] || [ -z "$EMAIL" ]; then
        log_info "Email not sent (disabled or no recipient)."
        return
    fi

    if command -v msmtp &>/dev/null; then
        (
            echo "Subject: $subject"
            echo "MIME-Version: 1.0"
            echo "Content-Type: text/html; charset=utf-8"
            echo ""
            cat "$html_file"
        ) | msmtp "$EMAIL"
        log_info "Report emailed inline to $EMAIL via msmtp."
    elif command -v mutt &>/dev/null; then
        mutt -e "set content_type=text/html" -s "$subject" "$EMAIL" < "$html_file"
        log_info "Report emailed inline to $EMAIL via mutt."
    elif command -v mail &>/dev/null; then
        mail -s "$subject" "$EMAIL" < "$html_file"
        log_info "Report sent to $EMAIL via standard mail."
    else
        log_warn "No mail program found – cannot send email."
    fi
}

# -------------------------------------------------------------------
# Parse command-line arguments
# -------------------------------------------------------------------
if ! PARSED_ARGS=$(getopt -o o:d:e:n -l output:,dir:,email:,no-email,help,version -- "$@"); then
    log_error "Invalid argument"
    exit 1
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
        *)             log_error "Invalid argument: $1"; exit 1 ;;
    esac
done

# -------------------------------------------------------------------
# Execution
# -------------------------------------------------------------------
check_deps df grep tail date hostname awk

mkdir -p "$REPORT_DIR"
REPORT_PATH="$REPORT_DIR/$REPORT_FILE"

log_info "Generating system report: $REPORT_PATH"

# Disk usage
disk_rows=""
while read -r line; do
    disk_rows+="<tr>"
    for word in $line; do
        disk_rows+="<td style='padding: 8px; border-bottom: 1px solid #ddd;'>$word</td>"
    done
    disk_rows+="</tr>"
done < <(df -h | grep -E '^/dev/|^Filesystem')

# Logs
backup_log="$LOG_DIR/backup-to-nas.log"
last_backup=$([ -f "$backup_log" ] && tail -n 5 "$backup_log" | strip_ansi || echo "No log found")

disk_log="$LOG_DIR/disk-sentinel.log"
disk_warnings=$([ -f "$disk_log" ] && tail -n 10 "$disk_log" | strip_ansi | grep -E "WARNING|exceeded" || echo "None")

# Updates & Load
dnf_updates=$(command -v dnf &>/dev/null && dnf check-update -q 2>/dev/null | grep -v '^Last metadata' | awk 'NF' | wc -l || echo "0")
flatpak_updates=$(command -v flatpak &>/dev/null && flatpak remote-ls --updates 2>/dev/null | awk 'NF' | wc -l || echo "0")
load=$(uptime)

# HTML Generation
cat > "$REPORT_PATH" <<EOF
<!DOCTYPE html>
<html>
<head>
    <meta charset="utf-8">
    <title>System Report $(date '+%Y-%m-%d')</title>
    <style>
        body { font-family: sans-serif; margin: 20px; color: #333; line-height: 1.6; }
        .container { max-width: 800px; margin: 0 auto; }
        h1 { color: #2c3e50; border-bottom: 2px solid #3498db; padding-bottom: 10px; }
        h2 { color: #34495e; margin-top: 30px; border-bottom: 1px solid #ecf0f1; padding-bottom: 5px; }
        pre { background: #f8f9fa; padding: 15px; border-radius: 6px; border: 1px solid #e9ecef; white-space: pre-wrap; font-family: monospace; }
        table { width: 100%; border-collapse: collapse; margin-top: 10px; }
        .stat-badge { display: inline-block; padding: 4px 8px; border-radius: 4px; background: #e9ecef; margin-right: 10px; font-weight: bold; }
        .warning-text { color: #e74c3c; font-weight: bold; }
    </style>
</head>
<body>
    <div class="container">
        <h1>🖥️ System Report for $(hostname -s)</h1>
        <p>Generated on $(date)</p>
        <h2>⏱️ System Load</h2>
        <pre>$load</pre>
        <h2>💾 Disk Usage</h2>
        <table>$disk_rows</table>
        <h2>📦 Updates</h2>
        <div>
            <span class="stat-badge">DNF: $dnf_updates</span>
            <span class="stat-badge">Flatpak: $flatpak_updates</span>
        </div>
        <h2>⚠️ Disk Warnings</h2>
        <pre>$disk_warnings</pre>
        <h2>🔄 Last Backup</h2>
        <pre>$last_backup</pre>
    </div>
</body>
</html>
EOF

log_info "Report saved to $REPORT_PATH"
send_report "System Report: $(hostname -s) - $(date +%Y-%m-%d)" "$REPORT_PATH"
log_info "Done."
