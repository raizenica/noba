#!/bin/bash
# noba-web.sh – Interactive web dashboard with robust cleanup and port reuse

set -u
set -o pipefail

PORT="${1:-8080}"
HTML_DIR="/tmp/noba-web"
SERVER_PID_FILE="/tmp/noba-web-server.pid"
UPDATER_PID_FILE="/tmp/noba-web-updater.pid"
LOG_FILE="/tmp/noba-web.log"

mkdir -p "$HTML_DIR"

# Function to kill a process by PID file
kill_pid_file() {
    local pid_file=$1
    local name=$2
    if [ -f "$pid_file" ]; then
        pid=$(cat "$pid_file")
        if kill -0 "$pid" 2>/dev/null; then
            echo "Stopping old $name (PID $pid)..."
            kill "$pid" 2>/dev/null && sleep 1
            if kill -0 "$pid" 2>/dev/null; then
                echo "Force killing $name..."
                kill -9 "$pid" 2>/dev/null
            fi
        fi
        rm -f "$pid_file"
    fi
}

# Function to find and kill any process using our port
kill_port_process() {
    local port=$1
    local pid=""
    if command -v lsof &>/dev/null; then
        pid=$(lsof -ti :"$port" 2>/dev/null | head -1)
    elif command -v ss &>/dev/null; then
        pid=$(ss -tulnp | grep ":$port" | grep -oP 'pid=\K\d+' | head -1)
    fi
    if [ -n "$pid" ]; then
        echo "Port $port is in use by PID $pid. Killing..."
        kill "$pid" 2>/dev/null && sleep 1
        if kill -0 "$pid" 2>/dev/null; then
            kill -9 "$pid" 2>/dev/null
        fi
    fi
}

# Kill previous instances
kill_pid_file "$SERVER_PID_FILE" "server"
kill_pid_file "$UPDATER_PID_FILE" "updater"
kill_port_process "$PORT"

# Give OS time to release the port
sleep 2

# Wait for port to be free
for i in {1..10}; do
    if ! ss -tuln | grep -q ":$PORT "; then
        break
    fi
    echo "Waiting for port $PORT to be released... (attempt $i)"
    sleep 1
done
if ss -tuln | grep -q ":$PORT "; then
    echo "ERROR: Port $PORT still in use. Exiting."
    exit 1
fi

# Generate the main HTML page
cat > "$HTML_DIR/index.html" <<'EOF'
<!DOCTYPE html>
<html lang="en">
<head>
    <meta charset="utf-8">
    <meta name="viewport" content="width=device-width, initial-scale=1">
    <title>Nobara Interactive Dashboard</title>
    <meta http-equiv="refresh" content="60">
    <!-- Font Awesome & Alpine.js for reactivity -->
    <link rel="stylesheet" href="https://cdnjs.cloudflare.com/ajax/libs/font-awesome/6.0.0-beta3/css/all.min.css">
    <script src="https://cdn.jsdelivr.net/npm/alpinejs@3.x.x/dist/cdn.min.js" defer></script>
    <style>
        :root {
            --bg: #1a1e24;
            --card: #252b33;
            --text: #e4e7eb;
            --text-muted: #9aa5b5;
            --accent: #3b82f6;
            --success: #10b981;
            --warning: #f59e0b;
            --danger: #ef4444;
        }
        * { margin: 0; padding: 0; box-sizing: border-box; }
        body {
            background: var(--bg);
            color: var(--text);
            font-family: 'Inter', system-ui, sans-serif;
            padding: 2rem;
            min-height: 100vh;
        }
        .container { max-width: 1400px; margin: 0 auto; }
        h1 {
            font-size: 2rem;
            font-weight: 600;
            margin-bottom: 0.5rem;
            display: flex;
            align-items: center;
            gap: 1rem;
        }
        h1 i { color: var(--accent); }
        .timestamp {
            color: var(--text-muted);
            font-size: 0.9rem;
            margin-bottom: 2rem;
        }
        .grid {
            display: grid;
            grid-template-columns: repeat(auto-fit, minmax(350px, 1fr));
            gap: 1.5rem;
        }
        .card {
            background: var(--card);
            border-radius: 1rem;
            padding: 1.5rem;
            box-shadow: 0 10px 25px rgba(0,0,0,0.3);
            transition: transform 0.2s;
        }
        .card:hover { transform: translateY(-4px); }
        .card-header {
            display: flex;
            align-items: center;
            gap: 0.75rem;
            font-size: 1.25rem;
            font-weight: 600;
            margin-bottom: 1.25rem;
            color: var(--accent);
            border-bottom: 1px solid #3a4452;
            padding-bottom: 0.75rem;
        }
        .card-header i { font-size: 1.5rem; }
        .stat-row {
            display: flex;
            justify-content: space-between;
            align-items: baseline;
            padding: 0.5rem 0;
            border-bottom: 1px solid #2e3843;
        }
        .stat-label { color: var(--text-muted); font-size: 0.95rem; }
        .stat-value { font-weight: 600; font-size: 1.1rem; }
        .disk-item {
            display: flex;
            align-items: center;
            gap: 0.5rem;
            padding: 0.5rem 0;
        }
        .disk-bar {
            flex: 1;
            height: 0.5rem;
            background: #2e3843;
            border-radius: 1rem;
            overflow: hidden;
        }
        .disk-bar-fill { height: 100%; border-radius: 1rem; }
        .disk-percent {
            font-weight: 600;
            min-width: 3rem;
            text-align: right;
        }
        .success { color: var(--success); }
        .warning { color: var(--warning); }
        .danger { color: var(--danger); }
        pre {
            background: #1a1e24;
            padding: 0.75rem;
            border-radius: 0.5rem;
            overflow-x: auto;
            font-size: 0.9rem;
            margin-top: 0.5rem;
        }
        .footer {
            margin-top: 2rem;
            text-align: center;
            color: var(--text-muted);
            font-size: 0.9rem;
        }
        .button-grid {
            display: flex;
            flex-wrap: wrap;
            gap: 0.5rem;
            margin-top: 1rem;
        }
        .btn {
            background: #2e3843;
            border: none;
            color: var(--text);
            padding: 0.5rem 1rem;
            border-radius: 0.5rem;
            cursor: pointer;
            font-size: 0.9rem;
            display: inline-flex;
            align-items: center;
            gap: 0.5rem;
            transition: background 0.2s;
        }
        .btn:hover { background: #3a4452; }
        .btn-primary { background: var(--accent); }
        .btn-primary:hover { background: #2563eb; }
        .modal {
            position: fixed;
            top: 0; left: 0; width: 100%; height: 100%;
            background: rgba(0,0,0,0.5);
            display: flex;
            align-items: center;
            justify-content: center;
            z-index: 1000;
        }
        .modal-content {
            background: var(--card);
            padding: 2rem;
            border-radius: 1rem;
            max-width: 600px;
            width: 90%;
            max-height: 80vh;
            overflow-y: auto;
        }
        .modal-header {
            display: flex;
            justify-content: space-between;
            align-items: center;
            margin-bottom: 1rem;
        }
        .modal-close {
            cursor: pointer;
            font-size: 1.5rem;
        }
        .loading {
            display: inline-block;
            width: 1rem;
            height: 1rem;
            border: 2px solid var(--text-muted);
            border-top-color: var(--accent);
            border-radius: 50%;
            animation: spin 1s linear infinite;
        }
        @keyframes spin { to { transform: rotate(360deg); } }
    </style>
</head>
<body>
<div class="container" x-data="dashboard()" x-init="init()">
    <h1><i class="fas fa-chart-line"></i> Nobara Interactive Dashboard</h1>
    <div class="timestamp"><i class="far fa-clock"></i> Last updated: <span x-text="timestamp"></span></div>

    <div class="grid">
        <!-- System Health Card -->
        <div class="card">
            <div class="card-header"><i class="fas fa-microchip"></i> System Health</div>
            <div class="stat-row"><span class="stat-label">Uptime</span><span class="stat-value" x-text="uptime"></span></div>
            <div class="stat-row"><span class="stat-label">Load Average</span><span class="stat-value" x-text="loadavg"></span></div>
            <div class="stat-row"><span class="stat-label">Memory</span><span class="stat-value" x-text="memory"></span></div>
            <div class="stat-row"><span class="stat-label">CPU Temp</span>
                <span class="stat-value" :class="tempClass" x-text="cpuTemp + '°C'"></span>
            </div>
        </div>

        <!-- Backup Status Card -->
        <div class="card">
            <div class="card-header"><i class="fas fa-database"></i> Backup</div>
            <div class="stat-row"><span class="stat-label">Last backup</span>
                <span class="stat-value" :class="backupClass" x-text="backupStatus"></span>
            </div>
            <div class="stat-row"><span class="stat-label">Time</span><span class="stat-value" x-text="backupTime"></span></div>
            <pre x-text="backupLog"></pre>
            <div class="button-grid">
                <button class="btn btn-primary" @click="runScript('backup')"><i class="fas fa-play"></i> Run Backup</button>
                <button class="btn" @click="runScript('verify')"><i class="fas fa-check"></i> Verify</button>
            </div>
        </div>

        <!-- Updates Card -->
        <div class="card">
            <div class="card-header"><i class="fas fa-sync-alt"></i> Updates</div>
            <div class="stat-row"><span class="stat-label">DNF</span><span class="stat-value" x-text="dnfUpdates"></span></div>
            <div class="stat-row"><span class="stat-label">Flatpak</span><span class="stat-value" x-text="flatpakUpdates"></span></div>
            <div class="stat-row"><span class="stat-label">Total</span><span class="stat-value" x-text="totalUpdates"></span></div>
        </div>

        <!-- Disk Usage Card -->
        <div class="card" style="grid-column: span 2;">
            <div class="card-header"><i class="fas fa-hdd"></i> Disk Usage</div>
            <template x-for="disk in disks" :key="disk.mount">
                <div class="disk-item">
                    <span style="min-width:80px;" x-text="disk.mount"></span>
                    <div class="disk-bar">
                        <div class="disk-bar-fill" :style="'width:'+disk.percent+'%; background: var(--'+disk.barClass+');'"></div>
                    </div>
                    <span class="disk-percent" x-text="disk.percent+'%'"></span>
                </div>
            </template>
        </div>

        <!-- Download Organizer Card -->
        <div class="card">
            <div class="card-header"><i class="fas fa-download"></i> Download Organizer</div>
            <div class="stat-row"><span class="stat-label">Files moved</span><span class="stat-value" x-text="movedFiles"></span></div>
            <div class="stat-row"><span class="stat-label">Last move</span><span class="stat-value" x-text="lastMove"></span></div>
            <pre x-text="organizerLog"></pre>
            <div class="button-grid">
                <button class="btn btn-primary" @click="runScript('organize')"><i class="fas fa-play"></i> Organize Now</button>
            </div>
        </div>

        <!-- Disk Sentinel Card -->
        <div class="card">
            <div class="card-header"><i class="fas fa-exclamation-triangle"></i> Disk Sentinel</div>
            <pre x-text="diskAlerts"></pre>
            <div class="button-grid">
                <button class="btn" @click="runScript('diskcheck')"><i class="fas fa-search"></i> Check Now</button>
            </div>
        </div>
    </div>

    <!-- Modal for script output -->
    <div x-show="showModal" class="modal" @click.self="showModal=false">
        <div class="modal-content">
            <div class="modal-header">
                <h2 x-text="modalTitle"></h2>
                <span class="modal-close" @click="showModal=false">&times;</span>
            </div>
            <pre x-text="modalOutput" style="white-space: pre-wrap;"></pre>
            <div class="button-grid" style="justify-content: flex-end;">
                <button class="btn" @click="showModal=false">Close</button>
            </div>
        </div>
    </div>

    <div class="footer">
        <i class="fas fa-sync-alt"></i> Auto‑refreshes every minute • <button class="btn" @click="refreshStats"><i class="fas fa-redo"></i> Refresh Now</button>
    </div>
</div>

<script>
function dashboard() {
    return {
        timestamp: '',
        uptime: '',
        loadavg: '',
        memory: '',
        cpuTemp: '',
        tempClass: '',
        backupStatus: '',
        backupClass: '',
        backupTime: '',
        backupLog: '',
        dnfUpdates: 0,
        flatpakUpdates: 0,
        disks: [],
        movedFiles: 0,
        lastMove: '',
        organizerLog: '',
        diskAlerts: '',
        showModal: false,
        modalTitle: '',
        modalOutput: '',
        runningScript: false,

        async init() {
            await this.refreshStats();
            setInterval(() => this.refreshStats(), 60000);
        },

        async refreshStats() {
            const response = await fetch('/api/stats');
            const data = await response.json();
            this.timestamp = data.timestamp;
            this.uptime = data.uptime;
            this.loadavg = data.loadavg;
            this.memory = data.memory;
            this.cpuTemp = data.cpuTemp;
            this.tempClass = data.cpuTemp > 80 ? 'danger' : data.cpuTemp > 60 ? 'warning' : '';
            this.backupStatus = data.backupStatus;
            this.backupClass = data.backupStatus.includes('OK') ? 'success' : data.backupStatus.includes('Failed') ? 'danger' : '';
            this.backupTime = data.backupTime;
            this.backupLog = data.backupLog;
            this.dnfUpdates = data.dnfUpdates;
            this.flatpakUpdates = data.flatpakUpdates;
            this.disks = data.disks;
            this.movedFiles = data.movedFiles;
            this.lastMove = data.lastMove;
            this.organizerLog = data.organizerLog;
            this.diskAlerts = data.diskAlerts;
        },

        async runScript(script) {
            if (this.runningScript) return;
            this.runningScript = true;
            this.modalTitle = `Running ${script}...`;
            this.modalOutput = 'Starting...';
            this.showModal = true;

            const response = await fetch('/api/run', {
                method: 'POST',
                headers: { 'Content-Type': 'application/json' },
                body: JSON.stringify({ script: script })
            });
            const result = await response.json();
            this.modalOutput = result.output;
            this.modalTitle = result.success ? '✅ Success' : '❌ Failed';
            this.runningScript = false;
            await this.refreshStats();
        }
    }
}
</script>
</body>
</html>
EOF

# Generate the initial stats JSON (will be overwritten by the server)
cat > "$HTML_DIR/stats.json" <<EOF
{"timestamp":"$(date)","uptime":"loading...","loadavg":"","memory":"","cpuTemp":"","backupStatus":"","backupTime":"","backupLog":"","dnfUpdates":0,"flatpakUpdates":0,"disks":[],"movedFiles":0,"lastMove":"","organizerLog":"","diskAlerts":""}
EOF

# Create the Python HTTP server with custom handler and port reuse
cd "$HTML_DIR" || exit 1
cat > server.py <<'EOF'
import http.server
import socketserver
import json
import subprocess
import os
import time
import re

PORT = int(os.environ.get('PORT', 8080))
SCRIPT_DIR = os.path.expanduser("~/.local/bin")

# Allow immediate port reuse (avoids TIME_WAIT issues)
socketserver.TCPServer.allow_reuse_address = True

class Handler(http.server.SimpleHTTPRequestHandler):
    def do_GET(self):
        if self.path == '/api/stats':
            self.send_response(200)
            self.send_header('Content-type', 'application/json')
            self.end_headers()
            stats = self.get_stats()
            self.wfile.write(json.dumps(stats).encode())
        else:
            super().do_GET()

    def do_POST(self):
        if self.path == '/api/run':
            content_length = int(self.headers['Content-Length'])
            post_data = self.rfile.read(content_length)
            try:
                data = json.loads(post_data)
                script = data.get('script')
                allowed = ['backup', 'verify', 'organize', 'diskcheck']
                if script not in allowed:
                    raise ValueError('Invalid script')
                script_map = {
                    'backup': 'backup-to-nas.sh',
                    'verify': 'backup-verifier.sh',
                    'organize': 'organize-downloads.sh',
                    'diskcheck': 'disk-sentinel.sh'
                }
                script_file = os.path.join(SCRIPT_DIR, script_map[script])
                proc = subprocess.run(
                    [script_file, '--verbose'],
                    capture_output=True,
                    text=True,
                    timeout=120,
                    cwd=SCRIPT_DIR
                )
                output = proc.stdout + proc.stderr
                success = proc.returncode == 0
            except subprocess.TimeoutExpired:
                output = "Script timed out after 120 seconds."
                success = False
            except Exception as e:
                output = f"Error: {str(e)}"
                success = False
            result = {'success': success, 'output': output}
            self.send_response(200)
            self.send_header('Content-type', 'application/json')
            self.end_headers()
            self.wfile.write(json.dumps(result).encode())
        else:
            self.send_response(404)
            self.end_headers()

    def get_stats(self):
        stats = {}
        stats['timestamp'] = time.strftime('%Y-%m-%d %H:%M:%S')
        try:
            with open('/proc/uptime') as f:
                uptime_seconds = float(f.read().split()[0])
                hours = int(uptime_seconds // 3600)
                minutes = int((uptime_seconds % 3600) // 60)
                stats['uptime'] = f"{hours}h {minutes}m"
        except:
            stats['uptime'] = 'N/A'

        try:
            with open('/proc/loadavg') as f:
                stats['loadavg'] = f.read().split()[0]
        except:
            stats['loadavg'] = 'N/A'

        try:
            mem = subprocess.check_output(['free', '-h'], text=True).split('\n')[1].split()
            stats['memory'] = f"{mem[2]}/{mem[1]}"
        except:
            stats['memory'] = 'N/A'

        try:
            temp = subprocess.check_output(['sensors'], text=True)
            match = re.search(r'Package id 0:\s+\+([0-9.]+)°C', temp)
            if match:
                stats['cpuTemp'] = float(match.group(1))
            else:
                stats['cpuTemp'] = 0
        except:
            stats['cpuTemp'] = 0

        backup_log = os.path.expanduser('~/.local/share/backup-to-nas.log')
        try:
            with open(backup_log) as f:
                lines = f.readlines()
                last_line = lines[-1] if lines else ''
                if 'ERROR' in last_line:
                    stats['backupStatus'] = '❌ Failed'
                elif 'Backup finished' in last_line:
                    stats['backupStatus'] = '✅ OK'
                else:
                    stats['backupStatus'] = '❓ Unknown'
                stats['backupTime'] = last_line[:16] if last_line else ''
                stats['backupLog'] = ''.join(lines[-3:])
        except:
            stats['backupStatus'] = 'No log'
            stats['backupTime'] = ''
            stats['backupLog'] = 'No backup log'

        try:
            dnf = subprocess.run(['dnf', 'check-update', '-q'], capture_output=True, text=True, timeout=10)
            stats['dnfUpdates'] = len(dnf.stdout.strip().split('\n')) if dnf.stdout.strip() else 0
        except:
            stats['dnfUpdates'] = 0
        try:
            flatpak = subprocess.run(['flatpak', 'remote-ls', '--updates'], capture_output=True, text=True, timeout=10)
            stats['flatpakUpdates'] = len(flatpak.stdout.strip().split('\n')) if flatpak.stdout.strip() else 0
        except:
            stats['flatpakUpdates'] = 0

        disks = []
        try:
            df = subprocess.check_output(['df', '-h'], text=True).split('\n')
            for line in df[1:]:
                if line.startswith('/dev/'):
                    parts = line.split()
                    if len(parts) >= 6:
                        mount = parts[5]
                        if 'snap' in mount or 'loop' in mount:
                            continue
                        percent = parts[4].replace('%', '')
                        try:
                            percent = int(percent)
                        except:
                            continue
                        barClass = 'success' if percent < 75 else 'warning' if percent < 90 else 'danger'
                        disks.append({'mount': mount, 'percent': percent, 'barClass': barClass})
        except:
            pass
        stats['disks'] = disks

        org_log = os.path.expanduser('~/.local/share/download-organizer.log')
        try:
            with open(org_log) as f:
                lines = f.readlines()
                moved = sum(1 for l in lines if 'Moved:' in l)
                stats['movedFiles'] = moved
                last_move_line = next((l for l in reversed(lines) if 'Moved:' in l), '')
                stats['lastMove'] = last_move_line[:50] + '...' if last_move_line else 'Never'
                stats['organizerLog'] = ''.join(lines[-3:])
        except:
            stats['movedFiles'] = 0
            stats['lastMove'] = 'Never'
            stats['organizerLog'] = 'No log'

        disk_log = os.path.expanduser('~/.local/share/disk-sentinel.log')
        try:
            with open(disk_log) as f:
                lines = f.readlines()
                alerts = [l for l in lines if 'WARNING' in l or 'ERROR' in l]
                stats['diskAlerts'] = ''.join(alerts[-5:]) if alerts else 'No recent alerts'
        except:
            stats['diskAlerts'] = 'No log'

        return stats

if __name__ == '__main__':
    with socketserver.TCPServer(("", PORT), Handler) as httpd:
        print(f"Serving at http://localhost:{PORT}")
        httpd.serve_forever()
EOF

# Start the server
nohup python3 server.py > "$LOG_FILE" 2>&1 &
SERVER_PID=$!
echo $SERVER_PID > "$SERVER_PID_FILE"

# Start the updater
(
    while true; do
        sleep 60
        echo "Page updated at $(date)" >> "$LOG_FILE"
    done
) >> "$LOG_FILE" 2>&1 &
UPDATER_PID=$!
echo $UPDATER_PID > "$UPDATER_PID_FILE"

echo "✅ Interactive dashboard started on http://localhost:$PORT"
echo "   Server PID: $SERVER_PID, Updater PID: $UPDATER_PID"
echo "Use 'kill $SERVER_PID $UPDATER_PID' to stop both processes."
