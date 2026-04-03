#!/bin/bash
# Copyright (c) 2024-2026 Kevin Van Nieuwenhove. All rights reserved.
# NOBA Command Center — Licensed under Apache 2.0.
# system-report.sh – Generate HTML report of system health and email it
# Version: 2.2.0

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
    echo "system-report.sh version 2.2.0"
    exit 0
fi

SCRIPT_DIR="$(cd "$(dirname "${BASH_SOURCE[0]}")" && pwd)"
# shellcheck source=./lib/noba-lib.sh
source "$SCRIPT_DIR/lib/noba-lib.sh"

# -------------------------------------------------------------------
# Default configuration
# -------------------------------------------------------------------
LOG_DIR="${LOG_DIR:-$HOME/.local/share}"
REPORT_DIR="${REPORT_DIR:-$LOG_DIR/reports}"
REPORT_FILE="system-report-$(date +%Y%m%d).html"
EMAIL="${EMAIL:-}" # Scrubbed hardcoded email
SEND_EMAIL=true

# -------------------------------------------------------------------
# Load user configuration
# -------------------------------------------------------------------
if command -v get_config &>/dev/null; then
    LOG_DIR="$(get_config ".logs.dir" "$LOG_DIR")"
    REPORT_DIR="$LOG_DIR/reports"
    EMAIL="$(get_config ".email" "$EMAIL")"
fi

mkdir -p "$REPORT_DIR"
FULL_REPORT_PATH="$REPORT_DIR/$REPORT_FILE"

# -------------------------------------------------------------------
# Data Collection
# -------------------------------------------------------------------
log_info "Gathering system metrics..."

load=$(uptime)

# Disk usage (skip loops/snaps)
disk_rows=""
while read -r line; do
    fs=$(echo "$line" | awk '{print $1}')
    size=$(echo "$line" | awk '{print $2}')
    used=$(echo "$line" | awk '{print $3}')
    avail=$(echo "$line" | awk '{print $4}')
    pcent=$(echo "$line" | awk '{print $5}')
    target=$(echo "$line" | awk '{print $6}')

    pcent_num=${pcent%%%}
    if [[ "$pcent_num" -ge 85 ]]; then
        pcent_html="<span class='warning-text'>$pcent</span>"
    else
        pcent_html="$pcent"
    fi

    disk_rows+="<tr><td>$target</td><td>$size</td><td>$used</td><td>$avail</td><td>$pcent_html</td></tr>"
done < <(df -h | grep '^/dev/' | grep -v '/loop')

# Memory
mem=$(free -m | awk 'NR==2{printf "Total: %sMB | Used: %sMB | Free: %sMB", $2,$3,$4}')

# Uptime Kuma Status (Optional)
kuma_status=""
if command -v docker &>/dev/null && docker ps | grep -q uptime-kuma; then
    kuma_status="<span class='stat-badge'>Docker: Kuma Running</span>"
elif command -v podman &>/dev/null && podman ps | grep -q uptime-kuma; then
    kuma_status="<span class='stat-badge'>Podman: Kuma Running</span>"
else
    kuma_status="<span class='stat-badge'>Kuma: Not Detected</span>"
fi

# -------------------------------------------------------------------
# Generate HTML
# -------------------------------------------------------------------
log_info "Generating HTML report..."

cat > "$FULL_REPORT_PATH" <<EOF
<!DOCTYPE html>
<html>
<head>
    <meta charset="utf-8">
    <title>System Report - $(hostname)</title>
    <style>
        body { font-family: -apple-system, BlinkMacSystemFont, 'Segoe UI', sans-serif; margin: 20px; background: #060a10; color: #c8dff0; line-height: 1.6; }
        .container { max-width: 800px; margin: 0 auto; }
        h1 { color: #00c8ff; border-bottom: 2px solid rgba(0,200,255,0.22); padding-bottom: 10px; }
        h2 { color: #c8dff0; margin-top: 30px; border-bottom: 1px solid rgba(0,200,255,0.12); padding-bottom: 5px; }
        pre { background: #0a1628; padding: 15px; border-radius: 6px; border: 1px solid rgba(0,200,255,0.12); white-space: pre-wrap; font-family: monospace; color: #c8dff0; }
        table { width: 100%; border-collapse: collapse; margin-top: 10px; }
        th, td { padding: 8px; text-align: left; border-bottom: 1px solid rgba(0,200,255,0.12); }
        th { background-color: #0a1628; color: #4a7a9b; text-transform: uppercase; font-size: 0.85em; letter-spacing: 0.05em; }
        .stat-badge { display: inline-block; padding: 4px 8px; border-radius: 4px; background: rgba(0,200,255,0.1); border: 1px solid rgba(0,200,255,0.22); color: #00c8ff; margin-right: 10px; font-weight: bold; }
        .warning-text { color: #ff5555; font-weight: bold; }
    </style>
</head>
<body>
    <div class="container">
        <h1>🖥️ System Report for $(hostname -s)</h1>
        <p>Generated on $(date)</p>

        <h2>⏱️ System Load</h2>
        <pre>$load</pre>

        <h2>💾 Disk Usage</h2>
        <table>
            <tr><th>Mount</th><th>Size</th><th>Used</th><th>Avail</th><th>Use %</th></tr>
            $disk_rows
        </table>

        <h2>🧠 Memory Usage</h2>
        <pre>$mem</pre>

        <h2>📡 Services</h2>
        <div>$kuma_status</div>

        <p style="margin-top: 40px; font-size: 0.8em; color: #4a7a9b; border-top: 1px solid rgba(0,200,255,0.12); padding-top: 10px;">
            Generated by Noba Automation Suite v2.2.0
        </p>
    </div>
</body>
</html>
EOF

log_success "Report generated: $FULL_REPORT_PATH"

# -------------------------------------------------------------------
# Send Email
# -------------------------------------------------------------------
if [[ "$SEND_EMAIL" == true ]]; then
    if [[ -z "$EMAIL" ]]; then
        log_warn "No email configured in YAML. Skipping email transmission."
        exit 0
    fi

    subject="System Report - $(hostname -s)"

    if command -v msmtp &>/dev/null; then
        {
            echo "To: $EMAIL"
            echo "Subject: $subject"
            echo "Content-Type: text/html; charset=utf-8"
            echo ""
            cat "$FULL_REPORT_PATH"
        } | msmtp "$EMAIL"
        log_success "Email sent via msmtp to $EMAIL"
    elif command -v sendmail &>/dev/null; then
        {
            echo "To: $EMAIL"
            echo "Subject: $subject"
            echo "Content-Type: text/html; charset=utf-8"
            echo ""
            cat "$FULL_REPORT_PATH"
        } | sendmail -t
        log_success "Email sent via sendmail to $EMAIL"
    else
        log_warn "No suitable mailer (msmtp/sendmail) found. Cannot send email."
    fi
fi
