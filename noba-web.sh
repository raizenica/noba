#!/bin/bash
# noba-web.sh – Interactive web dashboard with automatic port fallback

set -euo pipefail

SCRIPT_DIR="$(cd "$(dirname "${BASH_SOURCE[0]}")" && pwd)"
# shellcheck source=/dev/null
source "$SCRIPT_DIR/noba-lib.sh"

# -------------------------------------------------------------------
# Default configuration
# -------------------------------------------------------------------
START_PORT="${START_PORT:-8080}"
MAX_PORT="${MAX_PORT:-8090}"
HTML_DIR="${HTML_DIR:-/tmp/noba-web}"
SERVER_PID_FILE="${SERVER_PID_FILE:-/tmp/noba-web-server.pid}"
LOG_FILE="${LOG_FILE:-/tmp/noba-web.log}"
KILL_ONLY=false

# Default service list (space-separated, will be converted to comma for Python)
DEFAULT_SERVICES="backup-to-nas.service organize-downloads.service noba-web.service syncthing.service"

# -------------------------------------------------------------------
# Load user configuration (if any)
# -------------------------------------------------------------------
load_config || true
if [ "$CONFIG_LOADED" = true ]; then
    START_PORT="$(get_config ".web.start_port" "$START_PORT")"
    MAX_PORT="$(get_config ".web.max_port" "$MAX_PORT")"
    # Read services list from YAML (if defined)
    SERVICES_LIST=$(get_config_array ".web.service_list" | tr '\n' ',' | sed 's/,$//')
    if [ -n "$SERVICES_LIST" ]; then
        export NOBA_WEB_SERVICES="$SERVICES_LIST"
    else
        export NOBA_WEB_SERVICES="${DEFAULT_SERVICES// /,}"
    fi
else
    export NOBA_WEB_SERVICES="${DEFAULT_SERVICES// /,}"
fi

# -------------------------------------------------------------------
# Helper functions
# -------------------------------------------------------------------
show_version() {
    echo "noba-web.sh version 1.0"
    exit 0
}

show_help() {
    cat <<EOF
Usage: $0 [OPTIONS]

Launch an interactive web dashboard for Nobara automation.

Options:
  -p, --port PORT   Start searching from PORT (default: $START_PORT)
  -m, --max PORT    Maximum port to try (default: $MAX_PORT)
  -k, --kill        Kill any running noba-web server and exit
  --help            Show this help message
  --version         Show version information
EOF
    exit 0
}

kill_server() {
    if [ -f "$SERVER_PID_FILE" ]; then
        local pid
        pid=$(cat "$SERVER_PID_FILE" 2>/dev/null || true)
        if [ -n "$pid" ] && kill -0 "$pid" 2>/dev/null; then
            log_info "Stopping old server (PID $pid)..."
            kill "$pid" 2>/dev/null && sleep 1
            if kill -0 "$pid" 2>/dev/null; then
                log_warn "Force killing server..."
                kill -9 "$pid" 2>/dev/null || true
            fi
        fi
        rm -f "$SERVER_PID_FILE"
    fi
}

find_free_port() {
    local start="$1"
    local max="$2"
    local port
    for port in $(seq "$start" "$max"); do
        if ! ss -tuln 2>/dev/null | grep -q ":$port "; then
            echo "$port"
            return 0
        fi
    done
    return 1
}

# -------------------------------------------------------------------
# Parse arguments
# -------------------------------------------------------------------
if ! PARSED_ARGS=$(getopt -o p:m:k -l port:,max:,kill,help,version -- "$@"); then
    show_help
fi
eval set -- "$PARSED_ARGS"

while true; do
    case "$1" in
        -p|--port)    START_PORT="$2"; shift 2 ;;
        -m|--max)     MAX_PORT="$2"; shift 2 ;;
        -k|--kill)    KILL_ONLY=true; shift ;;
        --help)       show_help ;;
        --version)    show_version ;;
        --)           shift; break ;;
        *)            break ;;
    esac
done

# -------------------------------------------------------------------
# Kill mode
# -------------------------------------------------------------------
if [ "$KILL_ONLY" = true ]; then
    kill_server
    log_info "Server stopped (if any)."
    exit 0
fi

# -------------------------------------------------------------------
# Pre-flight checks
# -------------------------------------------------------------------
check_deps python3 ss
if ! command -v ss &>/dev/null; then
    log_warn "ss not found – using lsof as fallback."
    check_deps lsof
fi

# -------------------------------------------------------------------
# Find a free port
# -------------------------------------------------------------------
PORT=$(find_free_port "$START_PORT" "$MAX_PORT")
if [ -z "$PORT" ]; then
    log_error "No free port found between $START_PORT and $MAX_PORT."
    exit 1
fi
log_info "Using port $PORT"

# -------------------------------------------------------------------
# Prepare directory
# -------------------------------------------------------------------
mkdir -p "$HTML_DIR"
rm -f "$HTML_DIR"/*.html "$HTML_DIR"/server.py "$HTML_DIR"/stats.json 2>/dev/null || true

# -------------------------------------------------------------------
# Generate HTML file (with GPU and Docker cards)
# -------------------------------------------------------------------
cat > "$HTML_DIR/index.html" <<'EOF'
<!DOCTYPE html>
<html lang="en">
<head>
    <meta charset="utf-8">
    <meta name="viewport" content="width=device-width, initial-scale=1">
    <title>Nobara Interactive Dashboard</title>
    <link rel="stylesheet" href="https://cdnjs.cloudflare.com/ajax/libs/font-awesome/6.0.0-beta3/css/all.min.css">
    <script src="https://cdn.jsdelivr.net/npm/alpinejs@3.x.x/dist/cdn.min.js" defer></script>
    <style>
        :root {
            --bg: #1a1e24;
            --card: #2d333b;
            --text: #e1e4e8;
            --accent: #3b82f6;
            --success: #10b981;
            --warning: #f59e0b;
            --danger: #ef4444;
        }
        body { background: var(--bg); color: var(--text); font-family: system-ui, -apple-system, sans-serif; margin: 20px; }
        h1 { font-size: 2rem; margin-bottom: 0.5rem; }
        .timestamp { color: #9ca3af; margin-bottom: 2rem; }
        .grid { display: grid; grid-template-columns: repeat(auto-fit, minmax(300px, 1fr)); gap: 1.5rem; }
        .card { background: var(--card); border-radius: 1rem; padding: 1.5rem; box-shadow: 0 4px 6px rgba(0,0,0,0.3); }
        .card-header { font-size: 1.25rem; font-weight: 600; margin-bottom: 1rem; display: flex; align-items: center; gap: 0.5rem; }
        .stat-row { display: flex; justify-content: space-between; margin: 0.75rem 0; }
        .stat-label { color: #9ca3af; }
        .stat-value { font-weight: 600; }
        .success { color: var(--success); }
        .warning { color: var(--warning); }
        .danger { color: var(--danger); }
        .disk-item { display: flex; align-items: center; gap: 0.5rem; margin: 0.5rem 0; }
        .disk-bar { flex: 1; height: 0.5rem; background: #4b5563; border-radius: 1rem; overflow: hidden; }
        .disk-bar-fill { height: 100%; border-radius: 1rem; }
        .disk-percent { min-width: 3rem; text-align: right; }
        pre { background: #1a1e24; padding: 0.75rem; border-radius: 0.5rem; overflow-x: auto; font-size: 0.85rem; margin: 1rem 0; white-space: pre-wrap; word-wrap: break-word; }
        .button-grid { display: flex; gap: 0.5rem; margin-top: 1rem; }
        .btn { padding: 0.5rem 1rem; border: none; border-radius: 0.5rem; background: #4b5563; color: white; cursor: pointer; font-size: 0.9rem; transition: 0.2s; display: inline-flex; align-items: center; gap: 0.25rem; }
        .btn:hover { background: #6b7280; }
        .btn-primary { background: var(--accent); }
        .btn-primary:hover { background: #2563eb; }
        .modal { position: fixed; top: 0; left: 0; width: 100%; height: 100%; background: rgba(0,0,0,0.7); display: flex; align-items: center; justify-content: center; }
        .modal-content { background: var(--card); border-radius: 1rem; padding: 2rem; max-width: 600px; width: 90%; max-height: 80vh; overflow-y: auto; }
        .modal-header { font-size: 1.25rem; font-weight: 600; margin-bottom: 1rem; }
        .footer { margin-top: 2rem; text-align: center; color: #9ca3af; display: flex; justify-content: center; gap: 1rem; align-items: center; }
    </style>
</head>
<body x-data="dashboard()" x-init="init()">
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

        <!-- GPU Temperature Card -->
        <div class="card">
            <div class="card-header"><i class="fas fa-microchip"></i> GPU Temperature</div>
            <div class="stat-row">
                <span class="stat-label">GPU Temp</span>
                <span class="stat-value" x-text="gpuTemp"></span>
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

        <!-- Network Stats Card -->
        <div class="card">
            <div class="card-header"><i class="fas fa-network-wired"></i> Network</div>
            <div class="stat-row"><span class="stat-label">Default IP</span><span class="stat-value" x-text="defaultIp"></span></div>
            <template x-for="iface in interfaces" :key="iface.name">
                <div class="stat-row">
                    <span class="stat-label" x-text="iface.name"></span>
                    <span class="stat-value" x-text="'↓' + iface.rx + ' ↑' + iface.tx"></span>
                </div>
            </template>
            <template x-if="interfaces.length === 0">
                <div class="stat-row"><span class="stat-label">No data</span></div>
            </template>
        </div>

        <!-- Services Status Card -->
        <div class="card">
            <div class="card-header"><i class="fas fa-cogs"></i> User Services</div>
            <template x-for="svc in services" :key="svc.name">
                <div class="stat-row">
                    <span class="stat-label" x-text="svc.name.replace('.service','')"></span>
                    <span class="stat-value" :class="{
                        'success': svc.status === 'active',
                        'warning': svc.status === 'inactive',
                        'danger': svc.status === 'failed'
                    }" x-text="svc.status"></span>
                </div>
            </template>
        </div>

        <!-- Docker Containers Card -->
        <div class="card">
            <div class="card-header"><i class="fab fa-docker"></i> Docker Containers</div>
            <template x-if="dockerContainers.length === 0">
                <div class="stat-row"><span class="stat-label">No running containers</span></div>
            </template>
            <template x-for="container in dockerContainers" :key="container">
                <div class="stat-row">
                    <span class="stat-label" x-text="container.split('(')[0]"></span>
                    <span class="stat-value success" x-text="container.split('(')[1].replace(')','')"></span>
                </div>
            </template>
        </div>
    </div>

    <!-- Modal for script output -->
    <div x-show="showModal" class="modal" @click.self="showModal=false">
        <div class="modal-content">
            <div class="modal-header" x-text="modalTitle"></div>
            <pre x-text="modalOutput"></pre>
            <div class="button-grid" style="justify-content: flex-end;">
                <button class="btn" @click="showModal=false">Close</button>
            </div>
        </div>
    </div>

    <div class="footer">
        <i class="fas fa-sync-alt"></i> Auto‑refreshes every minute •
        <button class="btn" @click="refreshStats"><i class="fas fa-redo"></i> Refresh Now</button>
    </div>

    <script>
        function dashboard() {
            return {
                timestamp: '', uptime: '', loadavg: '', memory: '', cpuTemp: '',
                tempClass: '', backupStatus: '', backupClass: '', backupTime: '',
                backupLog: '', dnfUpdates: 0, flatpakUpdates: 0, totalUpdates: 0,
                disks: [], movedFiles: 0, lastMove: '', organizerLog: '',
                diskAlerts: '', showModal: false, modalTitle: '', modalOutput: '',
                runningScript: false,
                defaultIp: '', interfaces: [], services: [],
                gpuTemp: '', dockerContainers: [],

                async init() {
                    await this.refreshStats();
                    setInterval(() => this.refreshStats(), 60000);
                },

                async refreshStats() {
                    try {
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
                        this.totalUpdates = data.dnfUpdates + data.flatpakUpdates;
                        this.disks = data.disks;
                        this.movedFiles = data.movedFiles;
                        this.lastMove = data.lastMove;
                        this.organizerLog = data.organizerLog;
                        this.diskAlerts = data.diskAlerts;
                        this.defaultIp = data.defaultIp || 'N/A';
                        this.interfaces = data.interfaces || [];
                        this.services = data.services || [];
                        this.gpuTemp = data.gpuTemp || 'N/A';
                        this.dockerContainers = data.dockerContainers || [];
                    } catch (e) {
                        console.error('Stats fetch failed', e);
                    }
                },

                async runScript(script) {
                    if (this.runningScript) return;
                    this.runningScript = true;
                    this.modalTitle = `Running ${script}...`;
                    this.modalOutput = 'Starting...';
                    this.showModal = true;

                    try {
                        const response = await fetch('/api/run', {
                            method: 'POST',
                            headers: { 'Content-Type': 'application/json' },
                            body: JSON.stringify({ script })
                        });
                        const result = await response.json();
                        this.modalOutput = result.output;
                        this.modalTitle = result.success ? '✅ Success' : '❌ Failed';
                    } catch (e) {
                        this.modalOutput = 'Error: ' + e.message;
                        this.modalTitle = '❌ Failed';
                    }
                    this.runningScript = false;
                    await this.refreshStats();
                }
            }
        }
    </script>
</body>
</html>
EOF

# -------------------------------------------------------------------
# Generate Python server (with enhanced stats)
# -------------------------------------------------------------------
cat > "$HTML_DIR/server.py" <<'EOF'
import http.server
import socketserver
import json
import subprocess
import os
import sys
import time
import re

PORT = int(os.environ.get('PORT', 8080))
SCRIPT_DIR = os.path.expanduser("~/.local/bin")
LOG_DIR = os.path.expanduser("~/.local/share")

# ANSI escape code stripper
ansi_escape = re.compile(r'\x1B(?:[@-Z\\-_]|\[[0-?]*[ -/]*[@-~])')
def strip_ansi(s):
    return ansi_escape.sub('', s)

class Handler(http.server.SimpleHTTPRequestHandler):
    def human_bytes(self, b):
        for unit in ['B', 'KiB', 'MiB', 'GiB', 'TiB']:
            if b < 1024.0:
                return f"{b:.1f} {unit}"
            b /= 1024.0
        return f"{b:.1f} PiB"

    def get_gpu_temp(self):
        # Try NVIDIA first
        try:
            result = subprocess.run(['nvidia-smi', '--query-gpu=temperature.gpu', '--format=csv,noheader'],
                                    capture_output=True, text=True, timeout=2)
            if result.returncode == 0:
                temp = result.stdout.strip()
                if temp:
                    return temp + "°C"
        except:
            pass
        # Try AMD via sensors (if configured)
        try:
            result = subprocess.run(['sensors', '-u'], capture_output=True, text=True, timeout=2)
            # Look for temp1_input in amdgpu or k10temp
            import re
            match = re.search(r'edge:.*?temp1_input: (\d+\.\d+)', result.stdout, re.DOTALL)
            if match:
                return f"{float(match.group(1)):.0f}°C"
            # Fallback to k10temp
            match = re.search(r'Tdie:.*?temp1_input: (\d+\.\d+)', result.stdout, re.DOTALL)
            if match:
                return f"{float(match.group(1)):.0f}°C"
        except:
            pass
        return "N/A"

    def get_docker_containers(self):
        containers = []
        try:
            result = subprocess.run(['docker', 'ps', '--format', '{{.Names}} ({{.Status}})'],
                                    capture_output=True, text=True, timeout=3)
            if result.returncode == 0:
                for line in result.stdout.splitlines():
                    if line:
                        containers.append(line.strip())
        except:
            pass
        return containers

    def do_GET(self):
        try:
            if self.path == '/api/stats':
                self.send_response(200)
                self.send_header('Content-type', 'application/json')
                self.end_headers()
                stats = self.get_stats()
                self.wfile.write(json.dumps(stats).encode())
            else:
                super().do_GET()
        except (BrokenPipeError, ConnectionResetError):
            pass
        except Exception as e:
            print(f"GET error: {e}", file=sys.stderr)

    def do_POST(self):
        if self.path == '/api/run':
            try:
                content_len = int(self.headers.get('Content-Length', 0))
                post_data = self.rfile.read(content_len)
                data = json.loads(post_data)
                script = data.get('script', '')
                script_map = {
                    'backup': 'backup-to-nas.sh',
                    'verify': 'backup-verifier.sh',
                    'organize': 'organize-downloads.sh',
                    'diskcheck': 'disk-sentinel.sh'
                }
                script_file = os.path.join(SCRIPT_DIR, script_map.get(script, ''))
                if not os.path.exists(script_file):
                    output = f"Script {script} not found"
                    success = False
                else:
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
        stats = {'timestamp': time.strftime('%Y-%m-%d %H:%M:%S')}

        # Uptime
        try:
            with open('/proc/uptime') as f:
                uptime_sec = float(f.read().split()[0])
                hours = int(uptime_sec // 3600)
                minutes = int((uptime_sec % 3600) // 60)
                stats['uptime'] = f"{hours}h {minutes}m"
        except:
            stats['uptime'] = 'N/A'

        # Load average
        try:
            stats['loadavg'] = open('/proc/loadavg').read().split()[0]
        except:
            stats['loadavg'] = 'N/A'

        # Memory
        try:
            meminfo = {}
            with open('/proc/meminfo') as f:
                for line in f:
                    if line.startswith('MemTotal:'):
                        meminfo['total'] = int(line.split()[1]) // 1024
                    elif line.startswith('MemAvailable:'):
                        meminfo['avail'] = int(line.split()[1]) // 1024
            stats['memory'] = f"{meminfo.get('avail',0)}Mi/{meminfo.get('total',0)}Mi"
        except:
            stats['memory'] = 'N/A'

        # CPU Temp
        temp = 'N/A'
        try:
            for path in ['/sys/class/thermal/thermal_zone0/temp',
                         '/sys/class/hwmon/hwmon0/temp1_input',
                         '/sys/class/hwmon/hwmon1/temp1_input']:
                if os.path.exists(path):
                    with open(path) as f:
                        temp_val = int(f.read().strip()) // 1000
                        temp = str(temp_val)
                        break
        except:
            pass
        stats['cpuTemp'] = temp

        # Backup status and log (stripped)
        backup_log = os.path.join(LOG_DIR, 'backup-to-nas.log')
        if os.path.exists(backup_log):
            with open(backup_log) as f:
                lines = [strip_ansi(l) for l in f.readlines()]
                last_line = lines[-1].strip() if lines else ''
                if 'ERROR' in last_line:
                    stats['backupStatus'] = 'Failed'
                elif 'finished' in last_line:
                    stats['backupStatus'] = 'OK'
                else:
                    stats['backupStatus'] = 'Unknown'
                stats['backupLog'] = ''.join(lines[-5:])[-500:]
                stats['backupTime'] = time.ctime(os.path.getmtime(backup_log))
        else:
            stats['backupStatus'] = 'No log'
            stats['backupLog'] = ''
            stats['backupTime'] = ''

        # Updates
        dnf_out = ''
        try:
            dnf_out = subprocess.run(['dnf', 'check-update', '-q'], capture_output=True, text=True, timeout=10).stdout
        except:
            pass
        stats['dnfUpdates'] = len([l for l in dnf_out.splitlines() if l and not l.startswith('Last metadata')])
        flatpak_out = ''
        try:
            flatpak_out = subprocess.run(['flatpak', 'remote-ls', '--updates'], capture_output=True, text=True, timeout=10).stdout
        except:
            pass
        stats['flatpakUpdates'] = len([l for l in flatpak_out.splitlines() if l])

        # Disk usage
        disks = []
        try:
            output = subprocess.run(['df', '-h'], capture_output=True, text=True).stdout
            for line in output.splitlines()[1:]:
                parts = line.split()
                if len(parts) >= 5 and parts[0].startswith('/dev/'):
                    mount = parts[5] if len(parts) > 5 else ''
                    if mount.startswith('/var/lib/snapd'):
                        continue
                    percent = parts[4].replace('%', '')
                    if int(percent) >= 90:
                        bar_class = 'danger'
                    elif int(percent) >= 75:
                        bar_class = 'warning'
                    else:
                        bar_class = 'success'
                    disks.append({'mount': mount, 'percent': percent, 'barClass': bar_class})
        except:
            pass
        stats['disks'] = disks

        # Download organizer stats (stripped)
        organizer_log = os.path.join(LOG_DIR, 'download-organizer.log')
        moved = 0
        last_move = ''
        if os.path.exists(organizer_log):
            with open(organizer_log) as f:
                lines = [strip_ansi(l) for l in f.readlines()]
                moved = sum(1 for l in lines if 'Moved:' in l)
                last_line = next((l for l in reversed(lines) if 'Moved:' in l), '')
                if last_line:
                    last_move = last_line.split('Moved:')[-1].strip()
            stats['movedFiles'] = moved
            stats['lastMove'] = last_move
            stats['organizerLog'] = ''.join(lines[-5:])[-500:]
        else:
            stats['movedFiles'] = 0
            stats['lastMove'] = ''
            stats['organizerLog'] = ''

        # Disk alerts (stripped)
        disk_log = os.path.join(LOG_DIR, 'disk-sentinel.log')
        if os.path.exists(disk_log):
            with open(disk_log) as f:
                lines = [strip_ansi(l) for l in f.readlines()]
                alerts = [l for l in lines if 'WARNING' in l or 'exceeded' in l]
                stats['diskAlerts'] = ''.join(alerts[-5:])[-500:] if alerts else 'No recent warnings'
        else:
            stats['diskAlerts'] = 'No log'

        # --- Network stats ---
        # Improved IP detection using ip route
        try:
            result = subprocess.run(['ip', '-4', 'route', 'get', '1'],
                                    capture_output=True, text=True, timeout=2)
            if result.returncode == 0:
                # Extract IP from line like "1.0.0.0 via 192.168.1.1 dev wlp5s0 src 192.168.1.100 uid 1000"
                import re
                match = re.search(r'src\s+(\d+\.\d+\.\d+\.\d+)', result.stdout)
                if match:
                    stats['default_ip'] = match.group(1)
                else:
                    stats['default_ip'] = 'N/A'
            else:
                stats['default_ip'] = 'N/A'
        except:
            stats['default_ip'] = 'N/A'

        # Interface list and traffic
        interfaces = []
        try:
            with open('/proc/net/dev') as f:
                lines = f.readlines()[2:]
                for line in lines:
                    parts = line.split()
                    iface = parts[0].strip(':')
                    # Skip loopback if desired (optional)
                    # if iface == 'lo': continue
                    rx_bytes = int(parts[1])
                    tx_bytes = int(parts[9])
                    interfaces.append({
                        'name': iface,
                        'rx': self.human_bytes(rx_bytes),
                        'tx': self.human_bytes(tx_bytes)
                    })
            stats['interfaces'] = interfaces[:3]  # show up to 3 interfaces
        except:
            stats['interfaces'] = []

        # --- Services status (configurable via environment) ---
        service_list = os.environ.get('NOBA_WEB_SERVICES', 'backup-to-nas.service,organize-downloads.service,noba-web.service,syncthing.service').split(',')
        services_status = []
        for svc in service_list:
            svc = svc.strip()
            if not svc:
                continue
            try:
                result = subprocess.run(['systemctl', '--user', 'is-active', svc],
                                        capture_output=True, text=True, timeout=2)
                status = result.stdout.strip()
                if status not in ('active', 'inactive', 'failed'):
                    status = 'unknown'
            except:
                status = 'error'
            services_status.append({'name': svc, 'status': status})
        stats['services'] = services_status

        # --- GPU Temperature ---
        stats['gpuTemp'] = self.get_gpu_temp()

        # --- Docker Containers ---
        stats['dockerContainers'] = self.get_docker_containers()

        return stats

if __name__ == '__main__':
    with socketserver.TCPServer(("", PORT), Handler) as httpd:
        print(f"Serving at port {PORT}")
        httpd.serve_forever()
EOF

# -------------------------------------------------------------------
# Clean up any old server process and start new one
# -------------------------------------------------------------------
kill_server

export PORT
cd "$HTML_DIR"
nohup python3 server.py > "$LOG_FILE" 2>&1 &
SERVER_PID=$!
echo $SERVER_PID > "$SERVER_PID_FILE"

log_info "Web dashboard started on http://localhost:$PORT"
log_info "Log file: $LOG_FILE"
log_info "Use '$0 --kill' to stop the server."
