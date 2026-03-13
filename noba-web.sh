
# Basic help and version handling

# Basic help and version handling

# Help handling

# Basic help and version handling

# Help handling

# Basic help and version handling

# Help handling

# Basic help and version handling

# Help handling

# Basic help and version handling

# Help handling

# Basic help and version handling

# Basic help and version handling

# Help handling
if [ "$1" = "--help" ] || [ "$1" = "-h" ]; then
    echo "Usage: $(basename "$0") [OPTIONS]"
    echo "For detailed help, see the script documentation."
    exit 0
fi
if [ "$1" = "--version" ] || [ "$1" = "-v" ]; then
    echo "$(basename "$0") version 1.0"
    exit 0
fi

if [ "$1" = "--help" ] || [ "$1" = "-h" ]; then
    echo "Usage: $(basename "$0") [OPTIONS]"
    echo "For more information, see the script\x27s documentation or use --help on individual scripts."
    exit 0
fi
if [ "$1" = "--version" ] || [ "$1" = "-v" ]; then
    echo "$(basename "$0") version 1.0"
    exit 0
fi

if [ "$1" = "--help" ] || [ "$1" = "-h" ]; then
    echo "Usage: $(basename "$0") [OPTIONS]"
    echo "For more information, see the script\x27s documentation or use --help on individual scripts."
    exit 0
fi
if [ "$1" = "--version" ] || [ "$1" = "-v" ]; then
    echo "$(basename "$0") version 1.0"
    exit 0
fi

if [ "$1" = "--help" ] || [ "$1" = "-h" ]; then
    echo "Usage: $(basename "$0") [OPTIONS]"
    echo "For detailed help, see the script documentation."
    exit 0
fi
if [ "$1" = "--version" ] || [ "$1" = "-v" ]; then
    echo "$(basename "$0") version 1.0"
    exit 0
fi

if [ "$1" = "--help" ] || [ "$1" = "-h" ]; then
    echo "Usage: $(basename "$0") [OPTIONS]"
    echo "For more information, see the script\x27s documentation or use --help on individual scripts."
    exit 0
fi
if [ "$1" = "--version" ] || [ "$1" = "-v" ]; then
    echo "$(basename "$0") version 1.0"
    exit 0
fi

if [ "$1" = "--help" ] || [ "$1" = "-h" ]; then
    echo "Usage: $(basename "$0") [OPTIONS]"
    echo "For detailed help, see the script documentation."
    exit 0
fi
if [ "$1" = "--version" ] || [ "$1" = "-v" ]; then
    echo "$(basename "$0") version 1.0"
    exit 0
fi

if [ "$1" = "--help" ] || [ "$1" = "-h" ]; then
    echo "Usage: $(basename "$0") [OPTIONS]"
    echo "For more information, see the script\x27s documentation or use --help on individual scripts."
    exit 0
fi
if [ "$1" = "--version" ] || [ "$1" = "-v" ]; then
    echo "$(basename "$0") version 1.0"
    exit 0
fi

if [ "$1" = "--help" ] || [ "$1" = "-h" ]; then
    echo "Usage: $(basename "$0") [OPTIONS]"
    echo "For detailed help, see the script documentation."
    exit 0
fi
if [ "$1" = "--version" ] || [ "$1" = "-v" ]; then
    echo "$(basename "$0") version 1.0"
    exit 0
fi

if [ "$1" = "--help" ] || [ "$1" = "-h" ]; then
    echo "Usage: $(basename "$0") [OPTIONS]"
    echo "For more information, see the script\x27s documentation or use --help on individual scripts."
    exit 0
fi
if [ "$1" = "--version" ] || [ "$1" = "-v" ]; then
    echo "$(basename "$0") version 1.0"
    exit 0
fi

if [ "$1" = "--help" ] || [ "$1" = "-h" ]; then
    echo "Usage: $(basename "$0") [OPTIONS]"
    echo "For detailed help, see the script documentation."
    exit 0
fi
if [ "$1" = "--version" ] || [ "$1" = "-v" ]; then
    echo "$(basename "$0") version 1.0"
    exit 0
fi

if [ "$1" = "--help" ] || [ "$1" = "-h" ]; then
    echo "Usage: $(basename "$0") [OPTIONS]"
    echo "For more information, see the script\x27s documentation or use --help on individual scripts."
    exit 0
fi
if [ "$1" = "--version" ] || [ "$1" = "-v" ]; then
    echo "$(basename "$0") version 1.0"
    exit 0
fi

if [ "$1" = "--help" ] || [ "$1" = "-h" ]; then
    echo "Usage: $(basename "$0") [OPTIONS]"
    echo "For detailed help, see the script documentation."
    exit 0
fi
if [ "$1" = "--version" ] || [ "$1" = "-v" ]; then
    echo "$(basename "$0") version 1.0"
    exit 0
fi

if [ "$1" = "--help" ] || [ "$1" = "-h" ]; then
    echo "Usage: $(basename "$0") [OPTIONS]"
    echo "For more information, see the script\x27s documentation or use --help on individual scripts."
    exit 0
fi
if [ "$1" = "--version" ] || [ "$1" = "-v" ]; then
    echo "$(basename "$0") version 1.0"
    exit 0
fi

if [ "$1" = "--help" ] || [ "$1" = "-h" ]; then
    echo "Usage: $(basename "$0") [OPTIONS]"
    echo "For more information, see the script\x27s documentation or use --help on individual scripts."
    exit 0
fi
if [ "$1" = "--version" ] || [ "$1" = "-v" ]; then
    echo "$(basename "$0") version 1.0"
    exit 0
fi

#!/bin/bash
SCRIPT_DIR="$(cd "$(dirname "${BASH_SOURCE[0]}")" && pwd)"
source "$SCRIPT_DIR/noba-lib.sh"
# noba-web.sh – Interactive dashboard with real-time logs, stop button, graphs, system info, auto-refresh toggle

# Load configuration
load_config
if [ "$CONFIG_LOADED" = true ]; then
    # Override defaults with config values (script-specific)
    # Example:
    # VAR=$(get_config ".${script%.sh}.var" "$VAR")
fi

# Load configuration
load_config
if [ "$CONFIG_LOADED" = true ]; then
    # Override defaults with config values (script-specific)
    # Example:
    # VAR=$(get_config ".${script%.sh}.var" "$VAR")
fi

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
    <link rel="stylesheet" href="https://cdnjs.cloudflare.com/ajax/libs/font-awesome/6.0.0-beta3/css/all.min.css">
    <script src="https://cdn.jsdelivr.net/npm/alpinejs@3.x.x/dist/cdn.min.js" defer></script>
    <!-- Chart.js for graphs -->
    <script src="https://cdn.jsdelivr.net/npm/chart.js@4.4.0/dist/chart.umd.min.js"></script>
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
        .stop-btn { background: var(--danger); }
        .stop-btn:hover { background: #dc2626; }
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
        /* New styles for tabs */
        .tab-container { margin-top: 1rem; }
        .tab-buttons { display: flex; gap: 0.5rem; margin-bottom: 1rem; flex-wrap: wrap; }
        .tab-button {
            background: var(--card);
            border: none;
            color: var(--text);
            padding: 0.5rem 1rem;
            border-radius: 0.5rem;
            cursor: pointer;
            transition: background 0.2s;
        }
        .tab-button.active { background: var(--accent); }
        .tab-content { display: none; }
        .tab-content.active { display: block; }
        .graph-container { height: 200px; margin: 1rem 0; }
        .auto-refresh-toggle {
            display: flex;
            align-items: center;
            gap: 0.5rem;
            margin-bottom: 1rem;
        }
        .log-stream {
            background: #1a1e24;
            padding: 0.5rem;
            border-radius: 0.5rem;
            font-family: monospace;
            height: 300px;
            overflow-y: auto;
            white-space: pre-wrap;
            font-size: 0.85rem;
        }
    </style>
</head>
<body>
<div class="container" x-data="dashboard()" x-init="init()">
    <h1><i class="fas fa-chart-line"></i> Nobara Interactive Dashboard</h1>
    <div class="timestamp"><i class="far fa-clock"></i> Last updated: <span x-text="timestamp"></span></div>

    <!-- Auto-refresh toggle -->
    <div class="auto-refresh-toggle">
        <input type="checkbox" id="autoRefresh" x-model="autoRefresh" @change="toggleAutoRefresh">
        <label for="autoRefresh">Auto-refresh every 60 seconds</label>
    </div>

    <!-- Tab navigation -->
    <div class="tab-buttons">
        <button class="tab-button" :class="{ 'active': activeTab === 'system' }" @click="activeTab = 'system'">System</button>
        <button class="tab-button" :class="{ 'active': activeTab === 'backup' }" @click="activeTab = 'backup'">Backup</button>
        <button class="tab-button" :class="{ 'active': activeTab === 'disks' }" @click="activeTab = 'disks'">Disks</button>
        <button class="tab-button" :class="{ 'active': activeTab === 'services' }" @click="activeTab = 'services'">Services</button>
        <button class="tab-button" :class="{ 'active': activeTab === 'logs' }" @click="activeTab = 'logs'">Live Logs</button>
    </div>

    <!-- System Tab -->
    <div class="tab-content" :class="{ 'active': activeTab === 'system' }">
        <div class="grid">
            <div class="card">
                <div class="card-header"><i class="fas fa-microchip"></i> System Health</div>
                <div class="stat-row"><span class="stat-label">Hostname</span><span class="stat-value" x-text="hostname"></span></div>
                <div class="stat-row"><span class="stat-label">Uptime</span><span class="stat-value" x-text="uptime"></span></div>
                <div class="stat-row"><span class="stat-label">Load Average</span><span class="stat-value" x-text="loadavg"></span></div>
                <div class="stat-row"><span class="stat-label">Memory</span><span class="stat-value" x-text="memory"></span></div>
                <div class="stat-row"><span class="stat-label">CPU Temp</span>
                    <span class="stat-value" :class="tempClass" x-text="cpuTemp + '°C'"></span>
                </div>
            </div>
            <div class="card">
                <div class="card-header"><i class="fas fa-network-wired"></i> Network</div>
                <pre x-text="networkInfo"></pre>
            </div>
            <div class="card">
                <div class="card-header"><i class="fas fa-history"></i> Recent Backups</div>
                <pre x-text="recentBackups"></pre>
            </div>
        </div>
    </div>

    <!-- Backup Tab -->
    <div class="tab-content" :class="{ 'active': activeTab === 'backup' }">
        <div class="grid">
            <div class="card">
                <div class="card-header"><i class="fas fa-database"></i> Backup Status</div>
                <div class="stat-row"><span class="stat-label">Last backup</span>
                    <span class="stat-value" :class="backupClass" x-text="backupStatus"></span>
                </div>
                <div class="stat-row"><span class="stat-label">Time</span><span class="stat-value" x-text="backupTime"></span></div>
                <pre x-text="backupLog"></pre>
                <div class="button-grid">
                    <button class="btn btn-primary" @click="runScript('backup')"><i class="fas fa-play"></i> Run Backup</button>
                    <button class="btn" @click="runScript('verify')"><i class="fas fa-check"></i> Verify</button>
                    <button class="btn stop-btn" @click="stopScript('backup')" x-show="runningScripts.includes('backup')"><i class="fas fa-stop"></i> Stop</button>
                    <button class="btn stop-btn" @click="stopScript('verify')" x-show="runningScripts.includes('verify')"><i class="fas fa-stop"></i> Stop</button>
                </div>
            </div>
        </div>
    </div>

    <!-- Disks Tab -->
    <div class="tab-content" :class="{ 'active': activeTab === 'disks' }">
        <div class="card">
            <div class="card-header"><i class="fas fa-hdd"></i> Disk Usage</div>
            <div class="graph-container">
                <canvas id="diskChart" width="400" height="200"></canvas>
            </div>
            <div class="disk-list">
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
        </div>
    </div>

    <!-- Services Tab -->
    <div class="tab-content" :class="{ 'active': activeTab === 'services' }">
        <div class="card">
            <div class="card-header"><i class="fas fa-cogs"></i> Running Services</div>
            <pre x-text="runningServices"></pre>
        </div>
    </div>

    <!-- Live Logs Tab -->
    <div class="tab-content" :class="{ 'active': activeTab === 'logs' }">
        <div class="card">
            <div class="card-header"><i class="fas fa-terminal"></i> Real-time Logs</div>
            <div class="log-stream" id="logStream" x-ref="logStream"></div>
            <div class="button-grid">
                <button class="btn" @click="clearLogs">Clear</button>
            </div>
        </div>
    </div>

    <!-- Modal for script output (optional, we now have stop button and logs) -->
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
        <i class="fas fa-sync-alt"></i> <span x-text="autoRefresh ? 'Auto-refresh on' : 'Auto-refresh off'"></span>
    </div>
</div>

<script>
function dashboard() {
    return {
        // Existing state
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
        // New state
        hostname: '',
        networkInfo: '',
        recentBackups: '',
        runningServices: '',
        activeTab: 'system',
        autoRefresh: true,
        refreshInterval: null,
        runningScripts: [],
        showModal: false,
        modalTitle: '',
        modalOutput: '',
        logSource: null,

        async init() {
            await this.refreshStats();
            if (this.autoRefresh) {
                this.startAutoRefresh();
            }
            this.initLogStream();
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
            this.hostname = data.hostname;
            this.networkInfo = data.networkInfo;
            this.recentBackups = data.recentBackups;
            this.runningServices = data.runningServices;
            if (this.activeTab === 'disks') {
                this.updateDiskChart();
            }
        },

        startAutoRefresh() {
            if (this.refreshInterval) clearInterval(this.refreshInterval);
            this.refreshInterval = setInterval(() => this.refreshStats(), 60000);
        },

        stopAutoRefresh() {
            if (this.refreshInterval) {
                clearInterval(this.refreshInterval);
                this.refreshInterval = null;
            }
        },

        toggleAutoRefresh() {
            if (this.autoRefresh) {
                this.startAutoRefresh();
            } else {
                this.stopAutoRefresh();
            }
        },

        async runScript(script) {
            if (this.runningScripts.includes(script)) return;
            this.runningScripts.push(script);
            this.modalTitle = `Running ${script}...`;
            this.modalOutput = 'Started, check logs for output.';
            this.showModal = true;
            try {
                const response = await fetch('/api/run', {
                    method: 'POST',
                    headers: { 'Content-Type': 'application/json' },
                    body: JSON.stringify({ script: script })
                });
                const result = await response.json();
                if (!result.success) {
                    this.modalOutput = result.error || 'Failed to start.';
                }
            } catch (e) {
                this.modalOutput = 'Error starting script.';
            }
            // Remove from running after a delay (process will be tracked server-side)
            setTimeout(() => {
                this.runningScripts = this.runningScripts.filter(s => s !== script);
            }, 5000);
        },

        async stopScript(script) {
            const response = await fetch('/api/stop', {
                method: 'POST',
                headers: { 'Content-Type': 'application/json' },
                body: JSON.stringify({ script: script })
            });
            const result = await response.json();
            if (result.success) {
                this.modalTitle = 'Stopped';
                this.modalOutput = `Script ${script} stopped.`;
            } else {
                this.modalTitle = 'Error';
                this.modalOutput = result.error || 'Could not stop script.';
            }
            this.showModal = true;
            this.runningScripts = this.runningScripts.filter(s => s !== script);
        },

        initLogStream() {
            if (window.EventSource) {
                this.logSource = new EventSource('/api/log-stream');
                this.logSource.onmessage = (event) => {
                    const logDiv = this.$refs.logStream;
                    logDiv.innerHTML += event.data + '<br>';
                    logDiv.scrollTop = logDiv.scrollHeight;
                };
                this.logSource.onerror = (e) => {
                    console.log('Log stream error, reconnecting...');
                    this.logSource.close();
                    setTimeout(() => this.initLogStream(), 5000);
                };
            }
        },

        clearLogs() {
            this.$refs.logStream.innerHTML = '';
        },

        updateDiskChart() {
            const ctx = document.getElementById('diskChart')?.getContext('2d');
            if (!ctx) return;
            // Destroy existing chart if any
            if (this.diskChartInstance) {
                this.diskChartInstance.destroy();
            }
            const labels = this.disks.map(d => d.mount);
            const data = this.disks.map(d => d.percent);
            const colors = ['#3b82f6', '#10b981', '#f59e0b', '#ef4444', '#8b5cf6', '#ec4899'];
            this.diskChartInstance = new Chart(ctx, {
                type: 'doughnut',
                data: {
                    labels: labels,
                    datasets: [{
                        data: data,
                        backgroundColor: colors.slice(0, data.length)
                    }]
                },
                options: {
                    responsive: true,
                    maintainAspectRatio: false,
                    plugins: {
                        legend: { display: false },
                        tooltip: { callbacks: { label: (ctx) => `${ctx.raw}%` } }
                    }
                }
            });
        }
    }
}
</script>
</body>
</html>
EOF

# Generate the initial stats JSON (will be overwritten by the server)
cat > "$HTML_DIR/stats.json" <<EOF
{"timestamp":"$(date)","uptime":"loading...","loadavg":"","memory":"","cpuTemp":"","backupStatus":"","backupTime":"","backupLog":"","dnfUpdates":0,"flatpakUpdates":0,"disks":[],"movedFiles":0,"lastMove":"","organizerLog":"","diskAlerts":"","hostname":"","networkInfo":"","recentBackups":"","runningServices":""}
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
import signal
import threading
from collections import defaultdict

PORT = int(os.environ.get('PORT', 8080))
SCRIPT_DIR = os.path.expanduser("~/.local/bin")

# Allow immediate port reuse
socketserver.TCPServer.allow_reuse_address = True

# Track running processes
running_processes = defaultdict(lambda: None)
process_lock = threading.Lock()

# Simple in-memory log buffer (for simplicity, we'll just broadcast via SSE)
log_messages = []
log_lock = threading.Lock()

def add_log(message):
    with log_lock:
        log_messages.append(message)
        if len(log_messages) > 100:
            log_messages.pop(0)

class Handler(http.server.SimpleHTTPRequestHandler):
    def do_GET(self):
        if self.path == '/api/stats':
            self.send_response(200)
            self.send_header('Content-type', 'application/json')
            self.end_headers()
            stats = self.get_stats()
            self.wfile.write(json.dumps(stats).encode())
        elif self.path == '/api/log-stream':
            self.send_response(200)
            self.send_header('Content-type', 'text/event-stream')
            self.send_header('Cache-Control', 'no-cache')
            self.end_headers()
            self.stream_logs()
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
                # Run asynchronously
                proc = subprocess.Popen(
                    [script_file, '--verbose'],
                    stdout=subprocess.PIPE,
                    stderr=subprocess.STDOUT,
                    text=True,
                    cwd=SCRIPT_DIR,
                    bufsize=1  # line buffered
                )
                with process_lock:
                    running_processes[script] = proc
                # Start a thread to collect output and add to logs
                threading.Thread(target=self.collect_output, args=(script, proc), daemon=True).start()
                add_log(f"[{script}] Started")
                result = {'success': True, 'message': 'Started'}
            except Exception as e:
                result = {'success': False, 'error': str(e)}
            self.send_response(200)
            self.send_header('Content-type', 'application/json')
            self.end_headers()
            self.wfile.write(json.dumps(result).encode())
        elif self.path == '/api/stop':
            content_length = int(self.headers['Content-Length'])
            post_data = self.rfile.read(content_length)
            try:
                data = json.loads(post_data)
                script = data.get('script')
                with process_lock:
                    proc = running_processes.get(script)
                    if proc and proc.poll() is None:
                        proc.terminate()
                        # Give it a moment, then force kill if needed
                        time.sleep(1)
                        if proc.poll() is None:
                            proc.kill()
                        running_processes[script] = None
                        add_log(f"[{script}] Stopped")
                        result = {'success': True}
                    else:
                        result = {'success': False, 'error': 'No running process'}
            except Exception as e:
                result = {'success': False, 'error': str(e)}
            self.send_response(200)
            self.send_header('Content-type', 'application/json')
            self.end_headers()
            self.wfile.write(json.dumps(result).encode())
        else:
            self.send_response(404)
            self.end_headers()

    def collect_output(self, script, proc):
        for line in iter(proc.stdout.readline, ''):
            add_log(f"[{script}] {line.rstrip()}")
        proc.wait()
        with process_lock:
            running_processes[script] = None
        add_log(f"[{script}] Finished with exit code {proc.returncode}")

    def stream_logs(self):
        last_index = 0
        while True:
            with log_lock:
                new_messages = log_messages[last_index:]
                last_index = len(log_messages)
            for msg in new_messages:
                self.wfile.write(f"data: {msg}\n\n".encode())
                self.wfile.flush()
            time.sleep(1)

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

        # New system stats
        try:
            stats['hostname'] = os.uname().nodename
        except:
            stats['hostname'] = 'unknown'

        try:
            ip_output = subprocess.check_output(['ip', '-4', 'addr', 'show'], text=True)
            addrs = []
            for line in ip_output.split('\n'):
                if 'inet ' in line:
                    parts = line.strip().split()
                    if len(parts) >= 2:
                        addrs.append(parts[1])
            stats['networkInfo'] = '\n'.join(addrs) if addrs else 'No IPv4 addresses'
        except:
            stats['networkInfo'] = 'N/A'

        try:
            services = subprocess.check_output(['systemctl', 'list-units', '--type=service', '--state=running', '--no-pager'], text=True)
            # Keep only the first 20 lines to avoid huge output
            lines = services.split('\n')[:20]
            stats['runningServices'] = '\n'.join(lines)
        except:
            stats['runningServices'] = 'N/A'

        backup_root = '/mnt/vnnas/backups/raizen'
        try:
            dirs = [d for d in os.listdir(backup_root) if os.path.isdir(os.path.join(backup_root, d)) and re.match(r'\d{8}-\d{6}', d)]
            dirs.sort(reverse=True)
            stats['recentBackups'] = '\n'.join(dirs[:5]) if dirs else 'None'
        except:
            stats['recentBackups'] = 'N/A'

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

# Start the updater (simple heartbeat for logs)
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
