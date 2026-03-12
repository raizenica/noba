#!/bin/bash
# noba-web.sh – Start a local web server with status page

PORT="${1:-8080}"
HTML="/tmp/noba-web.html"

while true; do
    cat > "$HTML" <<EOF
<html><head><title>Nobara Dashboard</title>
<meta http-equiv="refresh" content="60">
<style>body{font-family:Arial;margin:40px;}</style>
</head>
<body>
<h1>Nobara System Status</h1>
<pre>$(hostname) – $(date)</pre>
<h2>Disk Usage</h2>
<pre>$(df -h | grep '^/dev/')</pre>
<h2>Last Backup</h2>
<pre>$(tail -5 "$HOME/.local/share/backup-to-nas.log" 2>/dev/null || echo "No log")</pre>
<h2>Pending Updates</h2>
<pre>DNF: $(dnf check-update -q 2>/dev/null | wc -l)
Flatpak: $(flatpak remote-ls --updates 2>/dev/null | wc -l)</pre>
<h2>Download Organizer</h2>
<pre>Moved: $(grep -c "Moved:" "$HOME/.local/share/download-organizer.log" 2>/dev/null || echo 0) files</pre>
</body></html>
EOF
    echo "Serving at http://localhost:$PORT"
    python3 -m http.server --directory "$(dirname "$HTML")" "$PORT" 2>/dev/null
    sleep 60
done
