#!/bin/bash
# system-report.sh – Generate HTML report of system health

REPORT_FILE="/tmp/system-report-$(date +%Y%m%d).html"
EMAIL="${EMAIL:-strikerke@gmail.com}"

cat > "$REPORT_FILE" <<EOF
<html><head><title>System Report $(date)</title>
<style>body{font-family:Arial}</style></head>
<body>
<h1>System Report for $(hostname) – $(date)</h1>
<h2>Disk Usage</h2>
<pre>$(df -h | grep '^/dev/')</pre>
<h2>Last Backup</h2>
<pre>$(tail -5 "$HOME/.local/share/backup-to-nas.log" 2>/dev/null || echo "No backup log")</pre>
<h2>Recent Disk Warnings</h2>
<pre>$(grep -E "WARNING|exceeded" "$HOME/.local/share/disk-sentinel.log" 2>/dev/null | tail -5)</pre>
<h2>Updates</h2>
<pre>DNF: $(dnf check-update -q 2>/dev/null | wc -l) updates
Flatpak: $(flatpak remote-ls --updates 2>/dev/null | wc -l) updates</pre>
<h2>System Load</h2>
<pre>$(uptime)</pre>
</body></html>
EOF

echo "Report saved to $REPORT_FILE"
if command -v msmtp &>/dev/null && [ -n "$EMAIL" ]; then
    mail -s "System Report $(date)" -a "$REPORT_FILE" "$EMAIL" < /dev/null
fi
