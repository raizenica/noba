/**
 * System actions mixin for the NOBA dashboard component.
 *
 * Provides history/metrics, audit, config backup/restore, SMART,
 * backup explorer, sessions, alert rules, system health, journal,
 * disk prediction, system info, incidents, runbooks, Graylog,
 * InfluxDB, correlation, backup scheduling, user profile, API keys,
 * TOTP, and container stats.
 *
 * @returns {Object} Alpine component mixin (state + methods)
 */
function systemActionsMixin() {
    return {

        // ── History & Audit state ────────────────────────────────────────────
        showHistoryModal: false,
        historyMetric: '',
        historyData: [],
        historyRange: 24,
        historyResolution: 60,
        historyChart: null,
        showAuditModal: false,
        auditLog: [],
        auditPage: 1,
        auditPageSize: 50,
        auditTotal: 0,
        auditSortField: 'time',
        auditSortDir: 'desc',
        historyAnomalyEnabled: false,

        // ── SMART disk health state ──────────────────────────────────────────
        smartData: [], smartLoading: false, showSmartModal: false,

        // ── Backup explorer state ────────────────────────────────────────────
        showBackupExplorer: false,
        snapshotList: [], snapshotLoading: false, snapshotDest: '',
        showFileBrowser: false, browseSnapshot: '', browsePath: '',
        browseEntries: [], browseLoading: false, browseBreadcrumbs: [],
        showDiffModal: false, diffA: '', diffB: '', diffPath: '',
        diffResult: null, diffLoading: false,
        showConfigHistory: false, configVersions: [], configHistoryLoading: false,
        restoreLoading: false,

        // ── Custom Monitoring Dashboard state ────────────────────────────────
        multiMetrics: ['cpu_percent'],
        multiMetricData: {},
        multiMetricLoading: false,
        showMultiChartModal: false,
        availableMetrics: [],
        _multiChart: null,

        // ── Alert Rule Builder state ─────────────────────────────────────────
        showAlertRuleModal: false,
        alertRulesList: [],
        editingRule: null,
        newRule: { condition: '', severity: 'warning', message: '', channels: [], cooldown: 300, group: '' },
        ruleTestResult: null,

        // ── User Profile state ───────────────────────────────────────────────
        userProfile: null,
        showProfileModal: false,
        changePasswordCurrent: '',
        changePasswordNew: '',
        changePasswordConfirm: '',

        // ── API Key Management state ─────────────────────────────────────────
        apiKeys: [],
        showApiKeysModal: false,
        newApiKeyName: '',
        newApiKeyRole: 'viewer',
        lastCreatedKey: '',

        // ── TOTP 2FA state ───────────────────────────────────────────────────
        totpSecret: '',
        totpUri: '',
        totpCode: '',
        showTotpSetup: false,

        // ── System Health Dashboard state ────────────────────────────────────
        systemHealth: null,
        showHealthModal: false,

        // ── Infrastructure Health Score state (Feature 7) ────────────────────
        healthScore: null,
        healthScoreExpanded: false,

        // ── Network Analysis state ───────────────────────────────────────────
        networkConnections: [],
        listeningPorts: [],
        networkInterfaces: [],
        showNetworkModal: false,

        // ── Process History state ────────────────────────────────────────────
        processHistory: [],
        processList: [],
        showProcessModal: false,

        // ── Service Map state ────────────────────────────────────────────────
        serviceMap: null,
        showServiceMapModal: false,

        // ── Uptime Dashboard state ───────────────────────────────────────────
        uptimeItems: [],
        showUptimeModal: false,

        // ── Journal Viewer state ─────────────────────────────────────────────
        journalOutput: '',
        journalUnit: '',
        journalPriority: '',
        journalLines: 100,
        journalGrep: '',
        journalUnits: [],
        showJournalModal: false,

        // ── Disk Prediction state ────────────────────────────────────────────
        diskPredictions: [],

        // ── System Info state ────────────────────────────────────────────────
        systemInfo: null,
        showSystemInfoModal: false,

        // ── Backup Scheduling state ──────────────────────────────────────────
        backupSchedules: [],
        backupHealth: null,
        backupProgress: null,
        showBackupScheduleModal: false,
        newBackupSchedule: { type: 'backup', schedule: '0 3 * * *', name: '' },

        // ── Container Stats state ────────────────────────────────────────────
        showContainerStatsModal: false,

        // ── Correlation chart state ──────────────────────────────────────────
        _correlateChart: null,

        // ── Network Traffic Analysis state ──────────────────────────────
        trafficAgent: '',
        trafficData: {},
        trafficLoading: false,
        trafficConnFilter: '',


        // ── History & Metrics ──────────────────────────────────────────────────

        /** Fetch metric history data and render the chart. */
        async fetchHistory() {
            if (!this.historyMetric) return;
            try {
                const anomalyParam = this.historyAnomalyEnabled ? '&anomaly=1' : '';
                const res = await fetch(
                    `/api/history/${this.historyMetric}?range=${this.historyRange}&resolution=${this.historyResolution}${anomalyParam}`,
                    { headers: { 'Authorization': 'Bearer ' + this._token() } }
                );
                if (!res.ok) throw new Error(`HTTP ${res.status}`);
                this.historyData = await res.json();
                this.$nextTick(() => this.renderHistoryChart());
            } catch (e) {
                this.addToast('Failed to load history: ' + e.message, 'error');
            }
        },

        /** Reset zoom on the history chart. */
        resetChartZoom() {
            if (this.historyChart) this.historyChart.resetZoom();
        },

        /** Render or re-render the Chart.js history chart. */
        renderHistoryChart() {
            const canvas = document.getElementById('historyChart');
            if (!canvas) return;

            // Load zoom plugin if needed
            if (typeof window.ChartZoom === 'undefined' && !window._chartZoomLoading) {
                window._chartZoomLoading = true;
                const script = document.createElement('script');
                script.src = 'https://cdn.jsdelivr.net/npm/chartjs-plugin-zoom@2.0.1/dist/chartjs-plugin-zoom.min.js';
                document.head.appendChild(script);
            }

            if (this.historyChart instanceof Chart) {
                this.historyChart.destroy();
            }

            const ctx    = canvas.getContext('2d');
            const times  = this.historyData.map(d => new Date(d.time * 1000).toLocaleTimeString());
            const values = this.historyData.map(d => d.value);
            const hasAnomaly = this.historyAnomalyEnabled && this.historyData.length > 0 && 'upper_band' in this.historyData[0];

            const datasets = [{
                label: this.historyMetric,
                data: values,
                borderColor: 'var(--accent)',
                backgroundColor: 'color-mix(in srgb, var(--accent) 10%, transparent)',
                tension: 0.2,
                fill: true,
                pointRadius: hasAnomaly
                    ? this.historyData.map(d => d.anomaly ? 5 : 0)
                    : 0,
                pointBackgroundColor: 'rgba(255,80,80,0.9)',
            }];

            if (hasAnomaly) {
                datasets.push({
                    label: 'Upper band',
                    data: this.historyData.map(d => d.upper_band),
                    borderColor: 'rgba(255,160,50,0.45)',
                    borderDash: [4, 4],
                    borderWidth: 1,
                    pointRadius: 0,
                    fill: false,
                    tension: 0.2,
                });
                datasets.push({
                    label: 'Lower band',
                    data: this.historyData.map(d => d.lower_band),
                    borderColor: 'rgba(255,160,50,0.45)',
                    borderDash: [4, 4],
                    borderWidth: 1,
                    pointRadius: 0,
                    fill: '-1',
                    backgroundColor: 'rgba(255,160,50,0.06)',
                    tension: 0.2,
                });
            }

            let newChart = new Chart(ctx, {
                type: 'line',
                data: { labels: times, datasets },
                options: {
                    responsive: true,
                    maintainAspectRatio: false,
                    scales: {
                        y: { beginAtZero: true, grid: { color: 'rgba(255,255,255,0.1)' } },
                        x: { grid: { display: false } }
                    },
                    plugins: {
                        legend: { display: hasAnomaly },
                        tooltip: {
                            callbacks: {
                                afterLabel: (ctx) => {
                                    const d = this.historyData[ctx.dataIndex];
                                    return d && d.anomaly ? '\u26a0 Anomaly detected' : '';
                                }
                            }
                        },
                        zoom: {
                            zoom: {
                                wheel: { enabled: true },
                                pinch: { enabled: true },
                                mode: 'x',
                            },
                            pan: {
                                enabled: true,
                                mode: 'x',
                            },
                        },
                    },
                    animation: { duration: 0 }
                }
            });

            this.historyChart = newChart;
        },

        /** Open the history modal for a given metric. */
        showHistory(metric) {
            this.historyMetric = metric;
            this.showHistoryModal = true;
            this.fetchHistory();
        },


        // ── Audit ──────────────────────────────────────────────────────────────

        /** Fetch the audit log (admin only) with pagination. */
        async fetchAuditLog(page) {
            if (page !== undefined) this.auditPage = page;
            const offset = (this.auditPage - 1) * this.auditPageSize;
            try {
                const res = await fetch(`/api/audit?limit=${this.auditPageSize}&offset=${offset}`, {
                    headers: { 'Authorization': 'Bearer ' + this._token() },
                });
                if (!res.ok) return;
                const data = await res.json();
                this.auditLog = Array.isArray(data) ? data : [];
            } catch { /* silent */ }
        },

        /** Return audit log sorted by the current sort field/direction. */
        get auditSorted() {
            const log = [...(this.auditLog || [])];
            const field = this.auditSortField;
            const dir = this.auditSortDir === 'asc' ? 1 : -1;
            return log.sort((a, b) => {
                const va = a[field] || '';
                const vb = b[field] || '';
                if (typeof va === 'number') return (va - vb) * dir;
                return String(va).localeCompare(String(vb)) * dir;
            });
        },

        /** Toggle sort direction or change sort field for the audit log. */
        toggleAuditSort(field) {
            if (this.auditSortField === field) {
                this.auditSortDir = this.auditSortDir === 'asc' ? 'desc' : 'asc';
            } else {
                this.auditSortField = field;
                this.auditSortDir = 'desc';
            }
        },

        /** Export the current audit log data as a CSV file download. */
        exportAuditCsv() {
            const rows = this.auditLog || [];
            const header = 'timestamp,username,action,details,ip';
            const lines = rows.map(r => {
                const ts = new Date((r.time || 0) * 1000).toISOString();
                const details = (r.details || '').replace(/"/g, '""');
                return `${ts},"${r.username}","${r.action}","${details}","${r.ip || ''}"`;
            });
            const csv = [header, ...lines].join('\n');
            const blob = new Blob([csv], { type: 'text/csv' });
            const url = URL.createObjectURL(blob);
            const a = document.createElement('a');
            a.href = url; a.download = 'noba-audit.csv'; a.click();
            URL.revokeObjectURL(url);
        },

        /** Go to the next audit log page. */
        auditNextPage() {
            this.auditPage++;
            this.fetchAuditLog();
        },

        /** Go to the previous audit log page. */
        auditPrevPage() {
            if (this.auditPage > 1) { this.auditPage--; this.fetchAuditLog(); }
        },

        /** Open the audit log page. */
        openAuditModal() {
            if (this.userRole !== 'admin') return;
            this.navigateTo('logs'); this.logsTab = 'audit';
            this.fetchAuditLog();
        },


        // ── History Export ──────────────────────────────────────────────────────

        /** Download the current history metric data as CSV. */
        async downloadHistoryCSV() {
            if (!this.historyMetric) return;
            const url = `/api/history/${encodeURIComponent(this.historyMetric)}/export`
                + `?range=${this.historyRange}&resolution=${this.historyResolution}`;
            try {
                const res = await fetch(url, {
                    headers: { 'Authorization': 'Bearer ' + this._token() },
                });
                if (!res.ok) throw new Error(`HTTP ${res.status}`);
                const blob = await res.blob();
                const objUrl = URL.createObjectURL(blob);
                try {
                    const a = document.createElement('a');
                    a.href = objUrl;
                    a.download = `noba-${this.historyMetric}-${this.historyRange}h.csv`;
                    document.body.appendChild(a);
                    a.click();
                    document.body.removeChild(a);
                } finally {
                    URL.revokeObjectURL(objUrl);
                }
            } catch (e) {
                this.addToast('CSV download failed: ' + e.message, 'error');
            }
        },


        // ── Config Backup / Restore ────────────────────────────────────────────

        /** Download the full NOBA config as a YAML backup. */
        async downloadConfigBackup() {
            try {
                const res = await fetch('/api/config/backup', {
                    headers: { 'Authorization': 'Bearer ' + this._token() },
                });
                if (!res.ok) throw new Error(`HTTP ${res.status}`);
                const blob = await res.blob();
                const objUrl = URL.createObjectURL(blob);
                try {
                    const a = document.createElement('a');
                    a.href = objUrl;
                    a.download = 'noba-config-backup.yaml';
                    document.body.appendChild(a);
                    a.click();
                    document.body.removeChild(a);
                } finally {
                    URL.revokeObjectURL(objUrl);
                }
            } catch (e) {
                this.addToast('Config backup failed: ' + e.message, 'error');
            }
        },

        /** Encrypt config backup with a password before download. */
        async downloadEncryptedConfig() {
            const password = prompt('Enter encryption password:');
            if (!password) return;
            try {
                const res = await fetch('/api/config/backup', {
                    headers: { 'Authorization': 'Bearer ' + this._token() },
                });
                const data = await res.arrayBuffer();

                // Derive key from password
                const enc = new TextEncoder();
                const keyMaterial = await crypto.subtle.importKey('raw', enc.encode(password), 'PBKDF2', false, ['deriveKey']);
                const salt = crypto.getRandomValues(new Uint8Array(16));
                const key = await crypto.subtle.deriveKey(
                    { name: 'PBKDF2', salt, iterations: 100000, hash: 'SHA-256' },
                    keyMaterial,
                    { name: 'AES-GCM', length: 256 },
                    false,
                    ['encrypt']
                );
                const iv = crypto.getRandomValues(new Uint8Array(12));
                const encrypted = await crypto.subtle.encrypt({ name: 'AES-GCM', iv }, key, data);

                // Pack: salt(16) + iv(12) + ciphertext
                const packed = new Uint8Array(16 + 12 + encrypted.byteLength);
                packed.set(salt, 0);
                packed.set(iv, 16);
                packed.set(new Uint8Array(encrypted), 28);

                const blob = new Blob([packed], { type: 'application/octet-stream' });
                const url = URL.createObjectURL(blob);
                const a = document.createElement('a');
                a.href = url;
                a.download = 'noba-config-encrypted.bin';
                a.click();
                URL.revokeObjectURL(url);
                this.addToast('Encrypted config downloaded', 'success');
            } catch (e) {
                this.addToast('Encryption failed: ' + e.message, 'error');
            }
        },

        /** Decrypt and restore an encrypted config backup. */
        async restoreEncryptedConfig(event) {
            const file = event.target.files[0];
            if (!file) return;
            const password = prompt('Enter decryption password:');
            if (!password) return;
            try {
                const packed = new Uint8Array(await file.arrayBuffer());
                if (packed.length < 29) throw new Error('File too small');

                const salt = packed.slice(0, 16);
                const iv = packed.slice(16, 28);
                const ciphertext = packed.slice(28);

                const enc = new TextEncoder();
                const keyMaterial = await crypto.subtle.importKey('raw', enc.encode(password), 'PBKDF2', false, ['deriveKey']);
                const key = await crypto.subtle.deriveKey(
                    { name: 'PBKDF2', salt, iterations: 100000, hash: 'SHA-256' },
                    keyMaterial,
                    { name: 'AES-GCM', length: 256 },
                    false,
                    ['decrypt']
                );
                const decrypted = await crypto.subtle.decrypt({ name: 'AES-GCM', iv }, key, ciphertext);

                // Upload decrypted YAML
                const res = await fetch('/api/config/restore', {
                    method: 'POST',
                    headers: { 'Authorization': 'Bearer ' + this._token() },
                    body: new Uint8Array(decrypted),
                });
                if (!res.ok) throw new Error(`HTTP ${res.status}`);
                this.addToast('Encrypted config restored', 'success');
            } catch (e) {
                this.addToast('Decryption failed: ' + (e.message || 'Wrong password?'), 'error');
            }
        },

        /**
         * Upload a YAML config file to restore settings.
         * @param {Event} event - File input change event
         */
        async uploadConfigRestore(event) {
            const file = event.target.files && event.target.files[0];
            if (!file) return;
            if (!file.name.match(/\.(yaml|yml)$/i)) {
                this.addToast('Please select a .yaml or .yml file', 'error');
                return;
            }
            try {
                const body = await file.arrayBuffer();
                const res  = await fetch('/api/config/restore', {
                    method:  'POST',
                    headers: {
                        'Content-Type':   'application/x-yaml',
                        'Content-Length': String(body.byteLength),
                        'Authorization':  'Bearer ' + this._token(),
                    },
                    body,
                });
                const data = await res.json();
                if (res.ok) {
                    this.addToast('Config restored — reloading settings\u2026', 'success');
                    await this.fetchSettings();
                } else {
                    this.addToast(data.detail || data.error || 'Restore failed', 'error');
                }
            } catch (e) {
                this.addToast('Restore error: ' + e.message, 'error');
            } finally {
                event.target.value = '';
            }
        },


        // ── Layout Backup / Restore ─────────────────────────────────────────────

        /** Export all noba- localStorage keys as a JSON file. */
        exportLayoutJSON() {
            const layout = {};
            for (let i = 0; i < localStorage.length; i++) {
                const key = localStorage.key(i);
                if (key && key.startsWith('noba-')) {
                    layout[key] = localStorage.getItem(key);
                }
            }
            const blob = new Blob([JSON.stringify(layout, null, 2)], { type: 'application/json' });
            const url = URL.createObjectURL(blob);
            try {
                const a = document.createElement('a');
                a.href = url;
                a.download = 'noba-layout-backup.json';
                a.click();
                this.addToast('Layout exported', 'success');
            } finally {
                URL.revokeObjectURL(url);
            }
        },

        /** Import a previously exported layout JSON file. */
        importLayoutJSON(event) {
            const file = event.target?.files?.[0];
            if (!file) return;
            const reader = new FileReader();
            reader.onload = (e) => {
                try {
                    const data = JSON.parse(e.target.result);
                    if (typeof data !== 'object' || Array.isArray(data)) {
                        this.addToast('Invalid layout file', 'error');
                        return;
                    }
                    for (const [key, value] of Object.entries(data)) {
                        if (key.startsWith('noba-') && key !== 'noba-token') {
                            localStorage.setItem(key, value);
                        }
                    }
                    this.addToast('Layout restored — reloading\u2026', 'success');
                    setTimeout(() => location.reload(), 1000);
                } catch {
                    this.addToast('Invalid JSON file', 'error');
                }
            };
            reader.readAsText(file);
        },


        // ── SMART disk health ──────────────────────────────────────────────────

        /** Fetch SMART health data for all disks. */
        async fetchSmartData() {
            this.smartLoading = true;
            try {
                const res = await fetch('/api/smart', {
                    headers: { 'Authorization': 'Bearer ' + this._token() }
                });
                if (!res.ok) throw new Error(`HTTP ${res.status}`);
                this.smartData = await res.json();
                this.showSmartModal = true;
            } catch (e) {
                this.addToast('Failed to load SMART data: ' + e.message, 'error');
            } finally {
                this.smartLoading = false;
            }
        },

        /** Return the CSS badge class for a SMART risk score. */
        smartRiskClass(score) {
            if (score >= 75) return 'bd';
            if (score >= 40) return 'bw';
            return 'bs';
        },

        /** Return a human-readable label for a SMART risk score. */
        smartRiskLabel(score) {
            if (score >= 75) return 'Critical';
            if (score >= 40) return 'Warning';
            return 'Healthy';
        },

        /** Format power-on hours as "Xd Yh". */
        formatPoh(hours) {
            if (hours == null) return '\u2014';
            const d = Math.floor(hours / 24);
            const h = hours % 24;
            return d > 0 ? `${d}d ${h}h` : `${h}h`;
        },


        // ── Backup Explorer ────────────────────────────────────────────────────

        /** Open the backup explorer modal and fetch snapshot history. */
        async openBackupExplorer() {
            this.showBackupExplorer = true;
            await this.fetchSnapshotHistory();
        },

        /** Fetch list of backup snapshots. */
        async fetchSnapshotHistory() {
            this.snapshotLoading = true;
            try {
                const res = await fetch('/api/backup/history', {
                    headers: { 'Authorization': 'Bearer ' + this._token() },
                });
                if (!res.ok) throw new Error(`HTTP ${res.status}`);
                const d = await res.json();
                this.snapshotList = d.snapshots || [];
                this.snapshotDest = d.dest || '';
            } catch (e) {
                this.addToast('Failed to load backup history: ' + e.message, 'error');
            } finally {
                this.snapshotLoading = false;
            }
        },

        /** Open the file browser for a specific snapshot. */
        async openFileBrowser(name, path) {
            this.browseSnapshot = name;
            this.browsePath = path || '';
            this.showFileBrowser = true;
            this.browseLoading = true;
            this._updateBreadcrumbs();
            try {
                const qs = this.browsePath ? '?path=' + encodeURIComponent(this.browsePath) : '';
                const res = await fetch(`/api/backup/snapshots/${encodeURIComponent(name)}/browse${qs}`, {
                    headers: { 'Authorization': 'Bearer ' + this._token() },
                });
                if (!res.ok) throw new Error(`HTTP ${res.status}`);
                const d = await res.json();
                this.browseEntries = d.entries || [];
            } catch (e) {
                this.addToast('Failed to browse snapshot: ' + e.message, 'error');
                this.browseEntries = [];
            } finally {
                this.browseLoading = false;
            }
        },

        /** Navigate into a subdirectory in the file browser. */
        browseInto(entry) {
            if (entry.type === 'dir') {
                const newPath = this.browsePath ? this.browsePath + '/' + entry.name : entry.name;
                this.openFileBrowser(this.browseSnapshot, newPath);
            }
        },

        /** Navigate up in the file browser. */
        browseUp() {
            const parts = this.browsePath.split('/').filter(Boolean);
            parts.pop();
            this.openFileBrowser(this.browseSnapshot, parts.join('/'));
        },

        /** Navigate to a specific breadcrumb level. */
        browseTo(idx) {
            const parts = this.browsePath.split('/').filter(Boolean);
            this.openFileBrowser(this.browseSnapshot, parts.slice(0, idx + 1).join('/'));
        },

        /** Update breadcrumb array from current path. */
        _updateBreadcrumbs() {
            const parts = this.browsePath.split('/').filter(Boolean);
            this.browseBreadcrumbs = parts.map((p, i) => ({ name: p, idx: i }));
        },

        /** Restore a file from the current snapshot. */
        async restoreFile(filePath) {
            const fullPath = this.browsePath ? this.browsePath + '/' + filePath : filePath;
            this.requestConfirm(
                `Restore "${filePath}" from snapshot ${this.browseSnapshot}?`,
                async () => {
                    this.restoreLoading = true;
                    try {
                        const res = await fetch('/api/backup/restore', {
                            method: 'POST',
                            headers: { 'Content-Type': 'application/json', 'Authorization': 'Bearer ' + this._token() },
                            body: JSON.stringify({ snapshot: this.browseSnapshot, path: fullPath }),
                        });
                        const d = await res.json();
                        if (res.ok) {
                            this.addToast(`Restored to ${d.restored_to}`, 'success');
                        } else {
                            this.addToast(d.detail || 'Restore failed', 'error');
                        }
                    } catch (e) {
                        this.addToast('Restore error: ' + e.message, 'error');
                    } finally {
                        this.restoreLoading = false;
                    }
                }
            );
        },

        /** Open the diff modal for two snapshots. */
        async openSnapshotDiff(a, b) {
            if (!a || !b || a === b) {
                this.addToast('Select two different snapshots to compare', 'error');
                return;
            }
            this.diffA = a;
            this.diffB = b;
            this.diffPath = '';
            this.showDiffModal = true;
            await this.fetchDiff();
        },

        /** Fetch the diff between two snapshots. */
        async fetchDiff() {
            this.diffLoading = true;
            try {
                const params = new URLSearchParams({ a: this.diffA, b: this.diffB });
                if (this.diffPath) params.set('path', this.diffPath);
                const res = await fetch('/api/backup/snapshots/diff?' + params, {
                    headers: { 'Authorization': 'Bearer ' + this._token() },
                });
                if (!res.ok) throw new Error(`HTTP ${res.status}`);
                this.diffResult = await res.json();
            } catch (e) {
                this.addToast('Diff failed: ' + e.message, 'error');
                this.diffResult = null;
            } finally {
                this.diffLoading = false;
            }
        },

        /** Navigate into a subdirectory in the diff view. */
        diffInto(name) {
            this.diffPath = this.diffPath ? this.diffPath + '/' + name : name;
            this.fetchDiff();
        },

        /** Navigate up in the diff view. */
        diffUp() {
            const parts = this.diffPath.split('/').filter(Boolean);
            parts.pop();
            this.diffPath = parts.join('/');
            this.fetchDiff();
        },

        /** Open config version history. */
        async openConfigHistory() {
            this.showConfigHistory = true;
            this.configHistoryLoading = true;
            try {
                const res = await fetch('/api/backup/config-history', {
                    headers: { 'Authorization': 'Bearer ' + this._token() },
                });
                if (!res.ok) throw new Error(`HTTP ${res.status}`);
                const d = await res.json();
                this.configVersions = d.versions || [];
            } catch (e) {
                this.addToast('Failed to load config history: ' + e.message, 'error');
            } finally {
                this.configHistoryLoading = false;
            }
        },

        /** Download a specific config version. */
        async downloadConfigVersion(filename) {
            try {
                const res = await fetch(`/api/backup/config-history/${encodeURIComponent(filename)}`, {
                    headers: { 'Authorization': 'Bearer ' + this._token() },
                });
                if (!res.ok) throw new Error(`HTTP ${res.status}`);
                const blob = await res.blob();
                const url = URL.createObjectURL(blob);
                try {
                    const a = document.createElement('a');
                    a.href = url;
                    a.download = filename;
                    document.body.appendChild(a);
                    a.click();
                    document.body.removeChild(a);
                } finally {
                    URL.revokeObjectURL(url);
                }
            } catch (e) {
                this.addToast('Download failed: ' + e.message, 'error');
            }
        },


        // ── Session Management ──────────────────────────────────────────────────

        /** Fetch active sessions (admin only). */
        async fetchSessions() {
            try {
                const res = await fetch('/api/admin/sessions', {
                    headers: { 'Authorization': 'Bearer ' + this._token() },
                });
                if (!res.ok) throw new Error(`HTTP ${res.status}`);
                this.sessionList = await res.json();
            } catch (e) {
                this.addToast('Failed to fetch sessions: ' + e.message, 'error');
            }
        },

        /** Revoke a session by token prefix. */
        async revokeSession(prefix) {
            try {
                const res = await fetch('/api/admin/sessions/revoke', {
                    method: 'POST',
                    headers: { 'Content-Type': 'application/json', 'Authorization': 'Bearer ' + this._token() },
                    body: JSON.stringify({ prefix }),
                });
                if (!res.ok) throw new Error(`HTTP ${res.status}`);
                this.addToast('Session revoked', 'success');
                await this.fetchSessions();
            } catch (e) {
                this.addToast('Failed to revoke session: ' + e.message, 'error');
            }
        },


        // ── Filtered Audit ──────────────────────────────────────────────────────

        /** Fetch audit log with optional filters. */
        async fetchFilteredAudit(userFilter, actionFilter, fromTs, toTs) {
            try {
                const params = new URLSearchParams();
                if (userFilter) params.set('user', userFilter);
                if (actionFilter) params.set('action', actionFilter);
                if (fromTs) params.set('from', Math.floor(new Date(fromTs).getTime() / 1000));
                if (toTs) params.set('to', Math.floor(new Date(toTs).getTime() / 1000));
                const res = await fetch(`/api/audit?${params}`, {
                    headers: { 'Authorization': 'Bearer ' + this._token() },
                });
                if (!res.ok) throw new Error(`HTTP ${res.status}`);
                this.auditLog = await res.json();
            } catch (e) {
                this.addToast('Failed to fetch audit log: ' + e.message, 'error');
            }
        },


        // ── Custom Monitoring Dashboard ─────────────────────────────────────────

        async fetchAvailableMetrics() {
            try {
                const res = await fetch('/api/metrics/available', {
                    headers: { 'Authorization': 'Bearer ' + this._token() },
                });
                if (res.ok) this.availableMetrics = await res.json();
            } catch { /* silent */ }
        },

        async fetchMultiMetricChart() {
            if (!this.multiMetrics.length) return;
            this.multiMetricLoading = true;
            try {
                const metrics = this.multiMetrics.join(',');
                const res = await fetch(`/api/history/multi?metrics=${metrics}&range=${this.historyRange}&resolution=${this.historyResolution}`, {
                    headers: { 'Authorization': 'Bearer ' + this._token() },
                });
                if (res.ok) this.multiMetricData = await res.json();
            } catch { /* silent */ }
            this.multiMetricLoading = false;
            this.renderMultiChart();
        },

        addMultiMetric(metric) {
            if (!this.multiMetrics.includes(metric) && this.multiMetrics.length < 10) {
                this.multiMetrics.push(metric);
                this.fetchMultiMetricChart();
            }
        },

        removeMultiMetric(metric) {
            this.multiMetrics = this.multiMetrics.filter(m => m !== metric);
            this.fetchMultiMetricChart();
        },

        renderMultiChart() {
            if (typeof Chart === 'undefined') return;
            const canvas = document.getElementById('multi-chart-canvas');
            if (!canvas) return;
            if (this._multiChart && this._multiChart.destroy) this._multiChart.destroy();
            const colors = ['#7aa2f7','#f7768e','#9ece6a','#e0af68','#bb9af7','#7dcfff','#ff9e64','#c0caf5','#73daca','#b4f9f8'];
            const datasets = [];
            let i = 0;
            for (const [metric, points] of Object.entries(this.multiMetricData)) {
                datasets.push({
                    label: metric,
                    data: points.map(p => ({ x: p.time * 1000, y: p.value })),
                    borderColor: colors[i % colors.length],
                    backgroundColor: 'transparent',
                    borderWidth: 1.5,
                    pointRadius: 0,
                    tension: 0.3,
                });
                i++;
            }
            this._multiChart = new Chart(canvas, {
                type: 'line',
                data: { datasets },
                options: {
                    responsive: true,
                    maintainAspectRatio: false,
                    scales: {
                        x: { type: 'time', time: { tooltipFormat: 'HH:mm' },
                             ticks: { color: 'rgba(255,255,255,.5)' }, grid: { color: 'rgba(255,255,255,.05)' } },
                        y: { ticks: { color: 'rgba(255,255,255,.5)' }, grid: { color: 'rgba(255,255,255,.05)' } },
                    },
                    plugins: { legend: { labels: { color: 'rgba(255,255,255,.7)' } } },
                },
            });
        },


        // ── Alert Rule Builder ──────────────────────────────────────────────────

        async fetchAlertRules() {
            try {
                const res = await fetch('/api/alert-rules', {
                    headers: { 'Authorization': 'Bearer ' + this._token() },
                });
                if (res.ok) this.alertRulesList = await res.json();
            } catch { /* silent */ }
        },

        async saveAlertRule() {
            const rule = this.editingRule || this.newRule;
            if (!rule.condition) { this.addToast('Condition is required', 'error'); return; }
            const method = this.editingRule ? 'PUT' : 'POST';
            const url = this.editingRule ? `/api/alert-rules/${this.editingRule.id}` : '/api/alert-rules';
            try {
                const res = await fetch(url, {
                    method,
                    headers: { 'Content-Type': 'application/json', 'Authorization': 'Bearer ' + this._token() },
                    body: JSON.stringify(rule),
                });
                if (!res.ok) { const d = await res.json(); this.addToast(d.detail || 'Failed', 'error'); return; }
                this.addToast(this.editingRule ? 'Rule updated' : 'Rule created', 'success');
                this.editingRule = null;
                this.newRule = { condition: '', severity: 'warning', message: '', channels: [], cooldown: 300, group: '' };
                this.fetchAlertRules();
            } catch (e) {
                this.addToast('Save failed: ' + e.message, 'error');
            }
        },

        async deleteAlertRule(ruleId) {
            if (!confirm('Delete this alert rule?')) return;
            try {
                const res = await fetch(`/api/alert-rules/${ruleId}`, {
                    method: 'DELETE', headers: { 'Authorization': 'Bearer ' + this._token() },
                });
                if (!res.ok) throw new Error(`HTTP ${res.status}`);
                this.addToast('Alert rule deleted', 'success');
                this.fetchAlertRules();
            } catch (e) {
                this.addToast('Delete failed: ' + e.message, 'error');
            }
        },

        async testAlertRule(ruleId) {
            try {
                const res = await fetch(`/api/alert-rules/test/${ruleId}`, {
                    headers: { 'Authorization': 'Bearer ' + this._token() },
                });
                if (res.ok) {
                    this.ruleTestResult = await res.json();
                    this.addToast(`Rule test: ${this.ruleTestResult.result ? 'TRIGGERED' : 'not triggered'}`,
                                 this.ruleTestResult.result ? 'warning' : 'success');
                }
            } catch { /* silent */ }
        },

        editAlertRule(rule) {
            this.editingRule = { ...rule };
        },


        // ── System Health Dashboard ─────────────────────────────────────────────

        async fetchSystemHealth() {
            try {
                const res = await fetch('/api/system/health', {
                    headers: { 'Authorization': 'Bearer ' + this._token() },
                });
                if (res.ok) this.systemHealth = await res.json();
            } catch { /* silent */ }
        },

        get healthScoreClass() {
            if (!this.systemHealth) return 'bn';
            const s = this.systemHealth.score;
            return s >= 90 ? 'bs' : s >= 60 ? 'bw' : 'bd';
        },


        // ── Infrastructure Health Score (Feature 7) ─────────────────────────────

        async fetchHealthScore() {
            try {
                const res = await fetch('/api/health-score', {
                    headers: { 'Authorization': 'Bearer ' + this._token() },
                });
                if (res.ok) this.healthScore = await res.json();
            } catch { /* silent */ }
        },

        get infraScoreColor() {
            if (!this.healthScore) return '#888';
            const s = this.healthScore.score;
            if (s > 80) return 'var(--success)';
            if (s > 50) return 'var(--warning)';
            return 'var(--danger)';
        },

        get infraScoreRingStyle() {
            if (!this.healthScore) return 'background: conic-gradient(var(--surface-2) 0deg, var(--surface-2) 360deg)';
            const pct = this.healthScore.score / 100;
            const deg = Math.round(pct * 360);
            const color = this.infraScoreColor;
            return `background: conic-gradient(${color} 0deg, ${color} ${deg}deg, var(--surface-2) ${deg}deg, var(--surface-2) 360deg)`;
        },


        // ── Webhook Management (Feature 8) ──────────────────────────────────────

        webhookList: [],
        webhookListLoading: false,
        showWebhookCreateModal: false,
        newWebhookName: '',
        newWebhookAutoId: '',
        lastCreatedWebhook: null,

        async fetchWebhooks() {
            this.webhookListLoading = true;
            try {
                const res = await fetch('/api/webhooks', {
                    headers: { 'Authorization': 'Bearer ' + this._token() },
                });
                if (res.ok) this.webhookList = await res.json();
            } catch (e) {
                this.addToast('Failed to load webhooks: ' + e.message, 'error');
            } finally {
                this.webhookListLoading = false;
            }
        },

        async createWebhook() {
            const name = this.newWebhookName.trim();
            if (!name) { this.addToast('Name is required', 'error'); return; }
            try {
                const body = { name };
                if (this.newWebhookAutoId) body.automation_id = this.newWebhookAutoId;
                const res = await fetch('/api/webhooks', {
                    method: 'POST',
                    headers: {
                        'Authorization': 'Bearer ' + this._token(),
                        'Content-Type': 'application/json',
                    },
                    body: JSON.stringify(body),
                });
                if (!res.ok) { const e = await res.json(); throw new Error(e.detail || 'Failed'); }
                const data = await res.json();
                this.lastCreatedWebhook = data;
                this.addToast('Webhook created', 'success');
                this.newWebhookName = '';
                this.newWebhookAutoId = '';
                await this.fetchWebhooks();
            } catch (e) {
                this.addToast('Error: ' + e.message, 'error');
            }
        },

        async deleteWebhook(id) {
            if (!confirm('Delete this webhook?')) return;
            try {
                const res = await fetch('/api/webhooks/' + id, {
                    method: 'DELETE',
                    headers: { 'Authorization': 'Bearer ' + this._token() },
                });
                if (!res.ok) throw new Error('Failed to delete');
                this.addToast('Webhook deleted', 'success');
                this.lastCreatedWebhook = null;
                await this.fetchWebhooks();
            } catch (e) {
                this.addToast('Error: ' + e.message, 'error');
            }
        },

        webhookUrl(hookId) {
            return location.origin + '/api/webhooks/receive/' + hookId;
        },

        copyToClipboard(text) {
            navigator.clipboard.writeText(text).then(
                () => this.addToast('Copied to clipboard', 'success'),
                () => this.addToast('Copy failed', 'error')
            );
        },


        // ── Network Analysis ────────────────────────────────────────────────────

        async fetchNetworkInfo() {
            try {
                const [conns, ports, ifaces] = await Promise.all([
                    fetch('/api/network/connections', { headers: { 'Authorization': 'Bearer ' + this._token() } }).then(r => r.ok ? r.json() : []),
                    fetch('/api/network/ports', { headers: { 'Authorization': 'Bearer ' + this._token() } }).then(r => r.ok ? r.json() : []),
                    fetch('/api/network/interfaces', { headers: { 'Authorization': 'Bearer ' + this._token() } }).then(r => r.ok ? r.json() : []),
                ]);
                this.networkConnections = conns;
                this.listeningPorts = ports;
                this.networkInterfaces = ifaces;
            } catch { /* silent */ }
        },


        // ── Process History ─────────────────────────────────────────────────────

        async fetchProcessHistory() {
            try {
                const res = await fetch('/api/processes/history', {
                    headers: { 'Authorization': 'Bearer ' + this._token() },
                });
                if (res.ok) this.processHistory = await res.json();
            } catch { /* silent */ }
        },

        async fetchProcessList() {
            try {
                const res = await fetch('/api/processes/current', {
                    headers: { 'Authorization': 'Bearer ' + this._token() },
                });
                if (res.ok) this.processList = await res.json();
            } catch { /* silent */ }
        },


        // ── Service Map ─────────────────────────────────────────────────────────

        async fetchServiceMap() {
            try {
                const res = await fetch('/api/services/map', {
                    headers: { 'Authorization': 'Bearer ' + this._token() },
                });
                if (res.ok) this.serviceMap = await res.json();
            } catch { /* silent */ }
        },


        // ── Uptime Dashboard ────────────────────────────────────────────────────

        async fetchUptime() {
            try {
                const res = await fetch('/api/uptime', {
                    headers: { 'Authorization': 'Bearer ' + this._token() },
                });
                if (res.ok) this.uptimeItems = await res.json();
            } catch { /* silent */ }
        },

        get uptimePercent() {
            if (!this.uptimeItems.length) return 100;
            const up = this.uptimeItems.filter(i => i.status === 'up').length;
            return Math.round(up / this.uptimeItems.length * 100);
        },


        // ── Journal Viewer ──────────────────────────────────────────────────────

        async fetchJournal() {
            const params = new URLSearchParams({ lines: this.journalLines });
            if (this.journalUnit) params.set('unit', this.journalUnit);
            if (this.journalPriority) params.set('priority', this.journalPriority);
            if (this.journalGrep) params.set('grep', this.journalGrep);
            try {
                const res = await fetch('/api/journal?' + params, {
                    headers: { 'Authorization': 'Bearer ' + this._token() },
                });
                this.journalOutput = res.ok ? await res.text() : 'Failed to fetch journal.';
            } catch (e) { this.journalOutput = 'Error: ' + e.message; }
        },

        async fetchJournalUnits() {
            try {
                const res = await fetch('/api/journal/units', {
                    headers: { 'Authorization': 'Bearer ' + this._token() },
                });
                if (res.ok) this.journalUnits = await res.json();
            } catch { /* silent */ }
        },

        openJournal() {
            this.navigateTo('logs'); this.logsTab = 'journal';
            this.fetchJournalUnits();
            this.fetchJournal();
        },


        // ── Disk Prediction ─────────────────────────────────────────────────────

        async fetchDiskPredictions() {
            try {
                const res = await fetch('/api/disks/prediction', {
                    headers: { 'Authorization': 'Bearer ' + this._token() },
                });
                if (res.ok) this.diskPredictions = await res.json();
            } catch { /* silent */ }
        },


        // ── System Info ─────────────────────────────────────────────────────────

        async fetchSystemInfo() {
            try {
                const res = await fetch('/api/system/info', {
                    headers: { 'Authorization': 'Bearer ' + this._token() },
                });
                if (res.ok) this.systemInfo = await res.json();
            } catch { /* silent */ }
        },


        // ── Ops Center ──────────────────────────────────────────────────────────

        async fetchDiskIntelligence() {
            this.diskIntelLoading = true;
            try {
                const res = await fetch('/api/disks/intelligence', {
                    headers: { 'Authorization': 'Bearer ' + this._token() },
                });
                if (res.ok) this.diskIntelligence = await res.json();
            } catch (e) {
                this.addToast('Failed to fetch disk intelligence: ' + e.message, 'error');
            } finally { this.diskIntelLoading = false; }
        },

        async fetchConfigChangelog() {
            this.changelogLoading = true;
            try {
                const res = await fetch('/api/config/changelog', {
                    headers: { 'Authorization': 'Bearer ' + this._token() },
                });
                if (res.ok) this.configChangelog = await res.json();
            } catch { /* silent */ }
            finally { this.changelogLoading = false; }
        },

        async fetchSyncStatus() {
            this.syncLoading = true;
            try {
                const res = await fetch('/api/sites/sync-status', {
                    headers: { 'Authorization': 'Bearer ' + this._token() },
                });
                if (res.ok) this.syncStatus = await res.json();
            } catch { /* silent */ }
            finally { this.syncLoading = false; }
        },

        async runRecovery(action, params = {}) {
            if (!confirm(`Run recovery action: ${action}?`)) return;
            this.recoveryLoading = true;
            this.recoveryResult = '';
            try {
                const res = await fetch(`/api/recovery/${action}`, {
                    method: 'POST',
                    headers: { 'Authorization': 'Bearer ' + this._token(), 'Content-Type': 'application/json' },
                    body: JSON.stringify(params),
                });
                const data = await res.json();
                this.recoveryResult = data.status === 'ok' ? 'Success' : `Error: ${data.error || 'Unknown'}`;
                this.addToast(this.recoveryResult, data.status === 'ok' ? 'success' : 'error');
            } catch (e) {
                this.recoveryResult = 'Failed: ' + e.message;
                this.addToast(this.recoveryResult, 'error');
            } finally { this.recoveryLoading = false; }
        },

        async runInfluxQuery() {
            if (!this.influxQuery.trim()) return;
            this.influxLoading = true;
            try {
                const res = await fetch('/api/influxdb/query', {
                    method: 'POST',
                    headers: { 'Authorization': 'Bearer ' + this._token(), 'Content-Type': 'application/json' },
                    body: JSON.stringify({ query: this.influxQuery }),
                });
                if (res.ok) {
                    this.influxResults = await res.json();
                    this.$nextTick(() => this.renderInfluxChart());
                } else {
                    const err = await res.json().catch(() => ({}));
                    this.addToast('Query failed: ' + (err.detail || 'error'), 'error');
                }
            } catch (e) { this.addToast('InfluxDB error: ' + e.message, 'error'); }
            finally { this.influxLoading = false; }
        },

        renderInfluxChart() {
            const canvas = document.getElementById('influx-chart');
            if (!canvas || !this.influxResults.length) return;
            if (this._influxChart instanceof Chart) this._influxChart.destroy();
            const keys = Object.keys(this.influxResults[0]);
            const timeKey = keys.find(k => k.includes('time')) || keys[0];
            const valKey = keys.find(k => k.includes('value') || k === '_value') || keys[1];
            const labels = this.influxResults.map(r => { try { return new Date(r[timeKey]).toLocaleTimeString(); } catch { return r[timeKey]; } });
            const values = this.influxResults.map(r => parseFloat(r[valKey]) || 0);
            this._influxChart = new Chart(canvas.getContext('2d'), {
                type: 'line',
                data: { labels, datasets: [{ label: valKey, data: values, borderColor: getComputedStyle(document.documentElement).getPropertyValue('--accent').trim(), borderWidth: 1.5, pointRadius: 0, fill: false }] },
                options: { responsive: true, animation: { duration: 0 } },
            });
        },

        async fetchBlastRadius(node) {
            try {
                const res = await fetch(`/api/services/dependencies/blast-radius?node=${encodeURIComponent(node)}`, {
                    headers: { 'Authorization': 'Bearer ' + this._token() },
                });
                if (res.ok) return await res.json();
            } catch { /* silent */ }
            return null;
        },


        // ── Incident Timeline ───────────────────────────────────────────────────

        async fetchIncidents(hours) {
            this.incidentLoading = true;
            try {
                const res = await fetch('/api/incidents?hours=' + (hours || 24), {
                    headers: { 'Authorization': 'Bearer ' + this._token() },
                });
                if (res.ok) this.incidents = await res.json();
            } catch { /* silent */ }
            finally { this.incidentLoading = false; }
        },

        async resolveIncident(id) {
            try {
                await fetch('/api/incidents/' + id + '/resolve', {
                    method: 'POST',
                    headers: { 'Authorization': 'Bearer ' + this._token() },
                });
                this.fetchIncidents();
            } catch { /* silent */ }
        },


        // ── Runbooks ────────────────────────────────────────────────────────────

        async fetchRunbooks() {
            this.runbookLoading = true;
            try {
                const res = await fetch('/api/runbooks', {
                    headers: { 'Authorization': 'Bearer ' + this._token() },
                });
                if (res.ok) this.runbooks = await res.json();
            } catch { /* silent */ }
            finally { this.runbookLoading = false; }
        },


        // ── Graylog ─────────────────────────────────────────────────────────────

        async searchGraylog() {
            this.graylogLoading = true;
            try {
                const res = await fetch('/api/graylog/search?q=' + encodeURIComponent(this.graylogQuery) + '&hours=1', {
                    headers: { 'Authorization': 'Bearer ' + this._token() },
                });
                if (res.ok) this.graylogResults = await res.json();
            } catch (e) { this.addToast('Graylog error: ' + e.message, 'error'); }
            finally { this.graylogLoading = false; }
        },


        // ── Metrics Correlation ─────────────────────────────────────────────────

        async fetchCorrelation() {
            if (!this.correlateMetrics.trim()) return;
            this.correlateLoading = true;
            try {
                const res = await fetch('/api/metrics/correlate?metrics=' + encodeURIComponent(this.correlateMetrics) + '&hours=' + this.correlateHours, {
                    headers: { 'Authorization': 'Bearer ' + this._token() },
                });
                if (res.ok) {
                    this.correlateData = await res.json();
                    this.$nextTick(function() { this.renderCorrelationChart(); });
                }
            } catch (e) { this.addToast('Correlation error: ' + e.message, 'error'); }
            finally { this.correlateLoading = false; }
        },

        renderCorrelationChart() {
            var canvas = document.getElementById('correlate-chart');
            if (!canvas || !this.correlateData) return;
            if (this._correlateChart instanceof Chart) this._correlateChart.destroy();
            var colors = ['#00c8ff', '#00e676', '#ffb300', '#ff1744', '#ab47bc', '#26c6da', '#ff7043', '#66bb6a'];
            var datasets = [];
            var i = 0;
            for (var name in this.correlateData) {
                if (!Object.prototype.hasOwnProperty.call(this.correlateData, name)) continue;
                var points = this.correlateData[name];
                datasets.push({
                    label: name,
                    data: points.map(function(p) { return { x: p.time * 1000, y: p.value }; }),
                    borderColor: colors[i % colors.length],
                    borderWidth: 1.5,
                    pointRadius: 0,
                    fill: false,
                });
                i++;
            }
            this._correlateChart = new Chart(canvas.getContext('2d'), {
                type: 'line',
                data: { datasets: datasets },
                options: {
                    responsive: true,
                    animation: { duration: 0 },
                    scales: {
                        x: { type: 'linear', ticks: { callback: function(v) { return new Date(v).toLocaleTimeString(); } } },
                    },
                    plugins: { legend: { labels: { color: '#c8dff0', font: { size: 10 } } } },
                },
            });
        },


        // ── Backup Scheduling ───────────────────────────────────────────────────

        async fetchBackupSchedules() {
            try {
                const res = await fetch('/api/backup/schedules', {
                    headers: { 'Authorization': 'Bearer ' + this._token() },
                });
                if (res.ok) this.backupSchedules = await res.json();
            } catch { /* silent */ }
        },

        async createBackupSchedule() {
            const s = this.newBackupSchedule;
            if (!s.name) s.name = `Scheduled ${s.type}`;
            try {
                const res = await fetch('/api/backup/schedule', {
                    method: 'POST',
                    headers: { 'Content-Type': 'application/json', 'Authorization': 'Bearer ' + this._token() },
                    body: JSON.stringify(s),
                });
                if (res.ok) {
                    this.addToast('Backup schedule created', 'success');
                    this.fetchBackupSchedules();
                    this.fetchAutomations();
                }
            } catch (e) {
                this.addToast('Failed: ' + e.message, 'error');
            }
        },

        async fetchBackupHealth() {
            try {
                const res = await fetch('/api/backup/health', {
                    headers: { 'Authorization': 'Bearer ' + this._token() },
                });
                if (res.ok) this.backupHealth = await res.json();
            } catch { /* silent */ }
        },

        async fetchBackupProgress() {
            try {
                const res = await fetch('/api/backup/progress', {
                    headers: { 'Authorization': 'Bearer ' + this._token() },
                });
                if (res.ok) this.backupProgress = await res.json();
            } catch { /* silent */ }
        },


        // ── Container Stats ─────────────────────────────────────────────────────

        openContainerStats() {
            this.showContainerStatsModal = true;
            this.fetchContainerStats();
        },


        // ── User Profile ────────────────────────────────────────────────────────

        async fetchProfile() {
            try {
                const res = await fetch('/api/profile', {
                    headers: { 'Authorization': 'Bearer ' + this._token() },
                });
                if (res.ok) this.userProfile = await res.json();
            } catch { /* silent */ }
        },

        async changeOwnPassword() {
            if (this.changePasswordNew !== this.changePasswordConfirm) {
                this.addToast('Passwords do not match', 'error');
                return;
            }
            try {
                const res = await fetch('/api/profile/password', {
                    method: 'POST',
                    headers: { 'Content-Type': 'application/json', 'Authorization': 'Bearer ' + this._token() },
                    body: JSON.stringify({ current: this.changePasswordCurrent, new: this.changePasswordNew }),
                });
                if (!res.ok) {
                    const d = await res.json();
                    this.addToast(d.detail || 'Failed', 'error');
                    return;
                }
                this.addToast('Password changed', 'success');
                this.changePasswordCurrent = '';
                this.changePasswordNew = '';
                this.changePasswordConfirm = '';
            } catch (e) {
                this.addToast('Failed: ' + e.message, 'error');
            }
        },


        // ── API Key Management ──────────────────────────────────────────────────

        /** Fetch all API keys (admin only). */
        async fetchApiKeys() {
            try {
                const res = await fetch('/api/admin/api-keys', {
                    headers: { 'Authorization': 'Bearer ' + this._token() },
                });
                if (res.ok) this.apiKeys = await res.json();
                else this.addToast('Failed to load API keys', 'error');
            } catch (e) {
                this.addToast('Failed to fetch API keys: ' + e.message, 'error');
            }
        },

        /** Create a new API key. */
        async createApiKey() {
            if (!this.newApiKeyName.trim()) return;
            try {
                const res = await fetch('/api/admin/api-keys', {
                    method: 'POST',
                    headers: { 'Content-Type': 'application/json', 'Authorization': 'Bearer ' + this._token() },
                    body: JSON.stringify({ name: this.newApiKeyName, role: this.newApiKeyRole }),
                });
                const d = await res.json();
                if (!res.ok) {
                    this.addToast(d.detail || 'Failed to create key', 'error');
                    return;
                }
                if (!d.key) {
                    this.addToast('Server returned no key', 'error');
                    return;
                }
                this.lastCreatedKey = d.key;
                this.addToast('API key created — copy it now, it won\'t be shown again', 'success');
                this.newApiKeyName = '';
                this.fetchApiKeys();
            } catch (e) {
                this.addToast('Failed to create key: ' + e.message, 'error');
            }
        },

        /** Delete an API key by ID. */
        async deleteApiKey(keyId) {
            if (!confirm('Delete this API key?')) return;
            try {
                await fetch(`/api/admin/api-keys/${keyId}`, {
                    method: 'DELETE',
                    headers: { 'Authorization': 'Bearer ' + this._token() },
                });
                this.addToast('API key deleted', 'success');
            } catch (e) {
                this.addToast('Delete failed: ' + e.message, 'error');
            }
            this.fetchApiKeys();
        },


        // ── TOTP 2FA Setup ─────────────────────────────────────────────────────

        /** Initiate TOTP 2FA setup (generates secret & provisioning URI). */
        async setupTotp() {
            try {
                const res = await fetch('/api/auth/totp/setup', {
                    method: 'POST',
                    headers: { 'Authorization': 'Bearer ' + this._token() },
                });
                const d = await res.json();
                this.totpSecret = d.secret;
                this.totpUri = d.provisioning_uri;
                this.showTotpSetup = true;
            } catch (e) {
                this.addToast('TOTP setup failed: ' + e.message, 'error');
            }
        },

        /** Verify a TOTP code and enable 2FA for the current user. */
        async enableTotp() {
            try {
                const res = await fetch('/api/auth/totp/enable', {
                    method: 'POST',
                    headers: { 'Content-Type': 'application/json', 'Authorization': 'Bearer ' + this._token() },
                    body: JSON.stringify({ secret: this.totpSecret, code: this.totpCode }),
                });
                if (!res.ok) { this.addToast('Invalid code', 'error'); return; }
                this.addToast('2FA enabled', 'success');
                this.showTotpSetup = false;
            } catch (e) {
                this.addToast('Failed: ' + e.message, 'error');
            }
        },


        // ── Prometheus Export ────────────────────────────────────────────────────

        /** Return the Prometheus metrics endpoint URL. */
        get prometheusUrl() {
            return '/api/metrics/prometheus';
        },

        // ── Saved Custom Dashboards ──────────────────────────────────────────────

        async fetchDashboards() {
            try {
                const res = await fetch('/api/dashboards', {
                    headers: { 'Authorization': 'Bearer ' + this._token() },
                });
                if (res.ok) this.savedDashboards = await res.json();
            } catch { /* silent */ }
        },

        async saveDashboard() {
            const name = (this.saveDashboardName || '').trim();
            if (!name) { this.addToast('Dashboard name is required', 'error'); return; }
            const config = {
                metrics: [...this.multiMetrics],
                range: this.historyRange,
                resolution: this.historyResolution,
            };
            const body = {
                name,
                config_json: JSON.stringify(config),
                shared: this.saveDashboardShared,
            };
            const isEdit = !!this.saveDashboardId;
            const url = isEdit ? '/api/dashboards/' + this.saveDashboardId : '/api/dashboards';
            const method = isEdit ? 'PUT' : 'POST';
            try {
                const res = await fetch(url, {
                    method,
                    headers: { 'Content-Type': 'application/json', 'Authorization': 'Bearer ' + this._token() },
                    body: JSON.stringify(body),
                });
                if (!res.ok) {
                    const err = await res.json().catch(() => ({}));
                    this.addToast(err.detail || 'Failed to save dashboard', 'error');
                    return;
                }
                this.addToast(isEdit ? 'Dashboard updated' : 'Dashboard saved', 'success');
                this.showSaveDashboardModal = false;
                this.saveDashboardName = '';
                this.saveDashboardShared = false;
                this.saveDashboardId = null;
                this.fetchDashboards();
            } catch (e) {
                this.addToast('Error: ' + e.message, 'error');
            }
        },

        loadDashboard(dashboard) {
            try {
                const config = JSON.parse(dashboard.config_json);
                if (config.metrics && Array.isArray(config.metrics)) {
                    this.multiMetrics = config.metrics;
                }
                if (config.range) this.historyRange = config.range;
                if (config.resolution) this.historyResolution = config.resolution;
                this.monitoringTab = 'charts';
                this.fetchAvailableMetrics();
                this.fetchMultiMetricChart();
                this.addToast('Loaded dashboard: ' + dashboard.name, 'success');
            } catch (e) {
                this.addToast('Failed to load dashboard config', 'error');
            }
        },

        async deleteDashboard(id, name) {
            if (!confirm('Delete dashboard "' + name + '"?')) return;
            try {
                const res = await fetch('/api/dashboards/' + id, {
                    method: 'DELETE',
                    headers: { 'Authorization': 'Bearer ' + this._token() },
                });
                if (res.ok) {
                    this.addToast('Dashboard deleted', 'success');
                    this.fetchDashboards();
                } else {
                    const err = await res.json().catch(() => ({}));
                    this.addToast(err.detail || 'Failed to delete', 'error');
                }
            } catch (e) {
                this.addToast('Error: ' + e.message, 'error');
            }
        },


        // ── Endpoint Monitoring ─────────────────────────────────────────────────

        async fetchEndpointMonitors() {
            this.endpointLoading = true;
            try {
                const res = await fetch('/api/endpoints', { headers: { 'Authorization': 'Bearer ' + this._token() } });
                if (res.ok) this.endpointMonitors = await res.json();
            } catch (e) {
                this.addToast('Failed to load endpoints: ' + e.message, 'error');
            } finally {
                this.endpointLoading = false;
            }
        },

        async saveEndpoint() {
            const body = { ...this.endpointForm };
            const isEdit = !!this.endpointEditId;
            const url = isEdit ? '/api/endpoints/' + this.endpointEditId : '/api/endpoints';
            const method = isEdit ? 'PUT' : 'POST';
            try {
                const res = await fetch(url, {
                    method,
                    headers: { 'Content-Type': 'application/json', 'Authorization': 'Bearer ' + this._token() },
                    body: JSON.stringify(body),
                });
                if (!res.ok) {
                    const err = await res.json().catch(() => ({}));
                    this.addToast(err.detail || 'Failed to save', 'error');
                    return;
                }
                this.addToast(isEdit ? 'Monitor updated' : 'Monitor created', 'success');
                this.showEndpointModal = false;
                this.fetchEndpointMonitors();
            } catch (e) {
                this.addToast('Error: ' + e.message, 'error');
            }
        },

        editEndpoint(ep) {
            this.endpointEditId = ep.id;
            this.endpointForm = {
                name: ep.name,
                url: ep.url,
                method: ep.method || 'GET',
                expected_status: ep.expected_status || 200,
                check_interval: ep.check_interval || 300,
                timeout: ep.timeout || 10,
                agent_hostname: ep.agent_hostname || '',
                enabled: ep.enabled,
                notify_cert_days: ep.notify_cert_days || 14,
            };
            this.showEndpointModal = true;
        },

        async deleteEndpoint(id, name) {
            if (!confirm('Delete monitor "' + name + '"?')) return;
            try {
                const res = await fetch('/api/endpoints/' + id, {
                    method: 'DELETE',
                    headers: { 'Authorization': 'Bearer ' + this._token() },
                });
                if (res.ok) {
                    this.addToast('Deleted', 'success');
                    this.fetchEndpointMonitors();
                } else {
                    this.addToast('Failed to delete', 'error');
                }
            } catch (e) {
                this.addToast('Error: ' + e.message, 'error');
            }
        },

        async checkEndpointNow(id) {
            try {
                const res = await fetch('/api/endpoints/' + id + '/check', {
                    method: 'POST',
                    headers: { 'Authorization': 'Bearer ' + this._token() },
                });
                if (res.ok) {
                    const data = await res.json();
                    this.addToast('Check complete: ' + (data.last_status || 'done'), 'success');
                    this.fetchEndpointMonitors();
                } else {
                    this.addToast('Check failed', 'error');
                }
            } catch (e) {
                this.addToast('Error: ' + e.message, 'error');
            }
        },

        // ── Status Page Management ──────────────────────────────────────────
        async fetchStatusComponents() {
            try {
                var res = await fetch('/api/status/components', {
                    headers: { 'Authorization': 'Bearer ' + this._token() },
                });
                if (res.ok) {
                    var d = await res.json();
                    this.spComponents = d.components || [];
                }
            } catch { /* silent */ }
        },

        async createStatusComponent() {
            var name = (this.spNewComp.name || '').trim();
            if (!name) return;
            try {
                var res = await fetch('/api/status/components', {
                    method: 'POST',
                    headers: { 'Authorization': 'Bearer ' + this._token(), 'Content-Type': 'application/json' },
                    body: JSON.stringify({
                        name: name,
                        group_name: this.spNewComp.group_name || 'Default',
                        service_key: this.spNewComp.service_key || null,
                        display_order: this.spNewComp.display_order || 0,
                    }),
                });
                if (res.ok) {
                    this.spNewComp = { name: '', group_name: 'Default', service_key: '', display_order: 0 };
                    this.fetchStatusComponents();
                    this.addToast('Component added', 'ok');
                } else {
                    var e = await res.json().catch(function() { return {}; });
                    this.addToast('Failed: ' + (e.detail || 'Unknown error'), 'error');
                }
            } catch (err) { this.addToast('Error: ' + err.message, 'error'); }
        },

        async deleteStatusComponent(id) {
            if (!confirm('Delete this component?')) return;
            try {
                var res = await fetch('/api/status/components/' + id, {
                    method: 'DELETE',
                    headers: { 'Authorization': 'Bearer ' + this._token() },
                });
                if (res.ok) {
                    this.fetchStatusComponents();
                    this.addToast('Component deleted', 'ok');
                }
            } catch { /* silent */ }
        },

        async fetchStatusIncidents() {
            try {
                var res = await fetch('/api/status/incidents');
                if (res.ok) {
                    var d = await res.json();
                    this.spIncidents = d.incidents || [];
                }
            } catch { /* silent */ }
        },

        async createStatusIncident() {
            var title = (this.spNewIncident.title || '').trim();
            if (!title) return;
            try {
                var res = await fetch('/api/status/incidents/create', {
                    method: 'POST',
                    headers: { 'Authorization': 'Bearer ' + this._token(), 'Content-Type': 'application/json' },
                    body: JSON.stringify({
                        title: title,
                        severity: this.spNewIncident.severity || 'minor',
                        message: this.spNewIncident.message || '',
                    }),
                });
                if (res.ok) {
                    this.spNewIncident = { title: '', severity: 'minor', message: '' };
                    this.fetchStatusIncidents();
                    this.addToast('Incident created', 'ok');
                } else {
                    var e = await res.json().catch(function() { return {}; });
                    this.addToast('Failed: ' + (e.detail || 'Unknown error'), 'error');
                }
            } catch (err) { this.addToast('Error: ' + err.message, 'error'); }
        },

        async addStatusUpdate(incidentId) {
            var msgEl = document.getElementById('sp-upd-' + incidentId);
            var statusEl = document.getElementById('sp-upd-status-' + incidentId);
            var message = msgEl ? msgEl.value.trim() : '';
            var status = statusEl ? statusEl.value : 'investigating';
            if (!message) { this.addToast('Enter an update message', 'error'); return; }
            try {
                var res = await fetch('/api/status/incidents/' + incidentId + '/update', {
                    method: 'POST',
                    headers: { 'Authorization': 'Bearer ' + this._token(), 'Content-Type': 'application/json' },
                    body: JSON.stringify({ message: message, status: status }),
                });
                if (res.ok) {
                    if (msgEl) msgEl.value = '';
                    this.fetchStatusIncidents();
                    this.addToast('Update posted', 'ok');
                }
            } catch { /* silent */ }
        },

        async resolveStatusIncident(incidentId) {
            if (!confirm('Resolve this incident?')) return;
            try {
                var res = await fetch('/api/status/incidents/' + incidentId + '/resolve', {
                    method: 'PUT',
                    headers: { 'Authorization': 'Bearer ' + this._token() },
                });
                if (res.ok) {
                    this.fetchStatusIncidents();
                    this.addToast('Incident resolved', 'ok');
                }
            } catch { /* silent */ }
        },

        // ── Incident War Room ─────────────────────────────────────────────────

        async openWarRoom(incidentId) {
            this.warRoomLoading = true;
            this.warRoomMessages = [];
            this.warRoomMsg = '';
            this.warRoomAssignTo = '';
            try {
                var incRes = await fetch('/api/status/incidents', {
                    headers: { 'Authorization': 'Bearer ' + this._token() },
                });
                if (incRes.ok) {
                    var data = await incRes.json();
                    var found = (data.incidents || []).find(function(i) { return i.id === incidentId; });
                    this.warRoomIncident = found || null;
                }
                var msgRes = await fetch('/api/incidents/' + incidentId + '/messages', {
                    headers: { 'Authorization': 'Bearer ' + this._token() },
                });
                if (msgRes.ok) {
                    var msgData = await msgRes.json();
                    this.warRoomMessages = msgData.messages || [];
                }
            } catch { /* silent */ }
            finally { this.warRoomLoading = false; }
        },

        closeWarRoom() {
            this.warRoomIncident = null;
            this.warRoomMessages = [];
            this.warRoomMsg = '';
        },

        async sendWarRoomMessage() {
            if (!this.warRoomIncident || !this.warRoomMsg.trim()) return;
            try {
                var res = await fetch('/api/incidents/' + this.warRoomIncident.id + '/messages', {
                    method: 'POST',
                    headers: { 'Authorization': 'Bearer ' + this._token(), 'Content-Type': 'application/json' },
                    body: JSON.stringify({ message: this.warRoomMsg.trim(), msg_type: 'comment' }),
                });
                if (res.ok) {
                    this.warRoomMsg = '';
                    await this.refreshWarRoomMessages();
                } else {
                    var e = await res.json().catch(function() { return {}; });
                    this.addToast('Failed: ' + (e.detail || 'Unknown error'), 'error');
                }
            } catch (err) { this.addToast('Error: ' + err.message, 'error'); }
        },

        async refreshWarRoomMessages() {
            if (!this.warRoomIncident) return;
            try {
                var res = await fetch('/api/incidents/' + this.warRoomIncident.id + '/messages', {
                    headers: { 'Authorization': 'Bearer ' + this._token() },
                });
                if (res.ok) {
                    var data = await res.json();
                    this.warRoomMessages = data.messages || [];
                }
            } catch { /* silent */ }
        },

        async assignWarRoomIncident() {
            if (!this.warRoomIncident || !this.warRoomAssignTo) return;
            try {
                var res = await fetch('/api/incidents/' + this.warRoomIncident.id + '/assign', {
                    method: 'PUT',
                    headers: { 'Authorization': 'Bearer ' + this._token(), 'Content-Type': 'application/json' },
                    body: JSON.stringify({ assigned_to: this.warRoomAssignTo }),
                });
                if (res.ok) {
                    this.warRoomIncident.assigned_to = this.warRoomAssignTo;
                    this.addToast('Incident assigned to ' + this.warRoomAssignTo, 'ok');
                    await this.refreshWarRoomMessages();
                    this.fetchStatusIncidents();
                } else {
                    var e = await res.json().catch(function() { return {}; });
                    this.addToast('Failed: ' + (e.detail || 'Unknown error'), 'error');
                }
            } catch (err) { this.addToast('Error: ' + err.message, 'error'); }
        },

        // ── Service Dependency Topology ─────────────────────────────────────

        async fetchTopology() {
            this.topologyLoading = true;
            try {
                var res = await fetch('/api/dependencies', {
                    headers: { 'Authorization': 'Bearer ' + this._token() },
                });
                if (res.ok) {
                    this.topologyData = await res.json();
                    this.$nextTick(() => { this.renderTopologyGraph(); });
                }
            } catch { /* silent */ }
            this.topologyLoading = false;
        },

        async addDependency() {
            var src = (this.topoNewSource || '').trim();
            var tgt = (this.topoNewTarget || '').trim();
            if (!src || !tgt) { this.addToast('Source and target required', 'error'); return; }
            try {
                var res = await fetch('/api/dependencies', {
                    method: 'POST',
                    headers: { 'Authorization': 'Bearer ' + this._token(), 'Content-Type': 'application/json' },
                    body: JSON.stringify({ source: src, target: tgt, type: this.topoNewType }),
                });
                if (res.ok) {
                    this.topoNewSource = ''; this.topoNewTarget = '';
                    this.fetchTopology();
                    this.addToast('Dependency added', 'ok');
                } else {
                    var err = await res.json().catch(function() { return {}; });
                    this.addToast(err.detail || 'Failed to add dependency', 'error');
                }
            } catch (e) { this.addToast('Error: ' + e.message, 'error'); }
        },

        async deleteDependency(depId) {
            if (!confirm('Delete this dependency?')) return;
            try {
                var res = await fetch('/api/dependencies/' + depId, {
                    method: 'DELETE',
                    headers: { 'Authorization': 'Bearer ' + this._token() },
                });
                if (res.ok) {
                    this.fetchTopology();
                    this.addToast('Dependency deleted', 'ok');
                }
            } catch { /* silent */ }
        },

        async fetchImpactAnalysis(serviceName) {
            this.topologyImpactService = serviceName;
            try {
                var res = await fetch('/api/dependencies/impact/' + encodeURIComponent(serviceName), {
                    headers: { 'Authorization': 'Bearer ' + this._token() },
                });
                if (res.ok) this.topologyImpact = await res.json();
            } catch { /* silent */ }
        },

        async discoverServices(hostname) {
            try {
                var res = await fetch('/api/dependencies/discover/' + encodeURIComponent(hostname), {
                    method: 'POST',
                    headers: { 'Authorization': 'Bearer ' + this._token() },
                });
                if (res.ok) {
                    this.addToast('Discovery queued for ' + hostname, 'ok');
                } else {
                    this.addToast('Discovery failed', 'error');
                }
            } catch (e) { this.addToast('Error: ' + e.message, 'error'); }
        },

        renderTopologyGraph() {
            var svg = document.getElementById('topology-svg');
            if (!svg || !this.topologyData) return;
            var data = this.topologyData;
            var nodes = data.nodes || [];
            var edges = data.edges || [];
            if (nodes.length === 0) { svg.innerHTML = ''; return; }

            var w = svg.clientWidth || 600;
            var h = svg.clientHeight || 400;
            var cx = w / 2, cy = h / 2;

            // Position nodes in a circle
            var positions = {};
            var radius = Math.min(w, h) * 0.35;
            nodes.forEach(function(n, i) {
                var angle = (2 * Math.PI * i) / nodes.length - Math.PI / 2;
                positions[n.id] = {
                    x: cx + radius * Math.cos(angle),
                    y: cy + radius * Math.sin(angle),
                };
            });

            // Simple force-directed adjustment (a few iterations)
            for (var iter = 0; iter < 50; iter++) {
                // Repulsion between all nodes
                for (var i = 0; i < nodes.length; i++) {
                    for (var j = i + 1; j < nodes.length; j++) {
                        var pi = positions[nodes[i].id], pj = positions[nodes[j].id];
                        var dx = pj.x - pi.x, dy = pj.y - pi.y;
                        var dist = Math.sqrt(dx * dx + dy * dy) || 1;
                        var force = 2000 / (dist * dist);
                        var fx = (dx / dist) * force, fy = (dy / dist) * force;
                        pi.x -= fx; pi.y -= fy;
                        pj.x += fx; pj.y += fy;
                    }
                }
                // Attraction along edges
                edges.forEach(function(e) {
                    var ps = positions[e.source], pt = positions[e.target];
                    if (!ps || !pt) return;
                    var dx = pt.x - ps.x, dy = pt.y - ps.y;
                    var dist = Math.sqrt(dx * dx + dy * dy) || 1;
                    var force = (dist - 120) * 0.01;
                    var fx = (dx / dist) * force, fy = (dy / dist) * force;
                    ps.x += fx; ps.y += fy;
                    pt.x -= fx; pt.y -= fy;
                });
                // Keep nodes within bounds
                nodes.forEach(function(n) {
                    var p = positions[n.id];
                    p.x = Math.max(40, Math.min(w - 40, p.x));
                    p.y = Math.max(40, Math.min(h - 40, p.y));
                });
            }

            var self = this;
            var healthColors = { healthy: '#22c55e', warning: '#eab308', critical: '#ef4444', offline: '#6b7280', unknown: '#9ca3af' };

            var html = '<defs><marker id="arrowhead" markerWidth="8" markerHeight="6" refX="8" refY="3" orient="auto"><polygon points="0 0, 8 3, 0 6" fill="var(--text-muted)"/></marker></defs>';

            // Draw edges
            edges.forEach(function(e) {
                var ps = positions[e.source], pt = positions[e.target];
                if (!ps || !pt) return;
                var dx = pt.x - ps.x, dy = pt.y - ps.y;
                var dist = Math.sqrt(dx * dx + dy * dy) || 1;
                var ox = (dx / dist) * 22, oy = (dy / dist) * 22;
                var dash = e.type === 'optional' ? 'stroke-dasharray="5,5"' : '';
                html += '<line x1="' + (ps.x + ox) + '" y1="' + (ps.y + oy) + '" x2="' + (pt.x - ox) + '" y2="' + (pt.y - oy) + '" stroke="var(--text-muted)" stroke-width="1.5" marker-end="url(#arrowhead)" ' + dash + '/>';
            });

            // Draw nodes
            function escSvg(s) { return String(s).replace(/&/g,'&amp;').replace(/</g,'&lt;').replace(/>/g,'&gt;').replace(/"/g,'&quot;').replace(/'/g,'&#39;'); }
            nodes.forEach(function(n) {
                var p = positions[n.id];
                var color = healthColors[n.health] || healthColors.unknown;
                var isImpacted = self.topologyImpact && self.topologyImpact.affected && self.topologyImpact.affected.indexOf(n.id) >= 0;
                var isTarget = self.topologyImpactService === n.id;
                var strokeW = (isImpacted || isTarget) ? 3 : 1.5;
                var strokeC = isTarget ? '#f97316' : (isImpacted ? '#ef4444' : 'var(--border)');
                var safeId = escSvg(n.id);
                var safeLabel = escSvg(n.label);
                html += '<circle cx="' + p.x + '" cy="' + p.y + '" r="20" fill="' + color + '" stroke="' + strokeC + '" stroke-width="' + strokeW + '" style="cursor:pointer" onclick="document.dispatchEvent(new CustomEvent(\'topo-click\',{detail:\'' + safeId + '\'}))" />';
                html += '<text x="' + p.x + '" y="' + (p.y + 34) + '" text-anchor="middle" fill="var(--text)" font-size="11" font-weight="600">' + safeLabel + '</text>';
            });

            svg.innerHTML = html;
        },

        // ── Config Drift Detection ──────────────────────────────────────────

        async fetchDriftBaselines() {
            this.driftLoading = true;
            try {
                var res = await fetch('/api/baselines', {
                    headers: { 'Authorization': 'Bearer ' + this._token() },
                });
                if (res.ok) this.driftBaselines = await res.json();
            } catch { /* silent */ }
            finally { this.driftLoading = false; }
        },

        async createDriftBaseline() {
            var path = (this.driftNewPath || '').trim();
            if (!path) { this.addToast('File path is required', 'warn'); return; }
            // First create with placeholder hash, then optionally set from agent
            try {
                var res = await fetch('/api/baselines', {
                    method: 'POST',
                    headers: {
                        'Authorization': 'Bearer ' + this._token(),
                        'Content-Type': 'application/json',
                    },
                    body: JSON.stringify({
                        path: path,
                        expected_hash: 'pending',
                        agent_group: this.driftNewGroup || '__all__',
                    }),
                });
                if (res.ok) {
                    this.driftNewPath = '';
                    this.driftNewGroup = '__all__';
                    this.addToast('Baseline created', 'ok');
                    this.fetchDriftBaselines();
                } else {
                    var err = await res.json().catch(function() { return {}; });
                    this.addToast(err.detail || 'Failed to create baseline', 'error');
                }
            } catch { /* silent */ }
        },

        async deleteDriftBaseline(id) {
            if (!confirm('Delete this baseline and all its drift history?')) return;
            try {
                var res = await fetch('/api/baselines/' + id, {
                    method: 'DELETE',
                    headers: { 'Authorization': 'Bearer ' + this._token() },
                });
                if (res.ok) {
                    this.addToast('Baseline deleted', 'ok');
                    if (this.driftExpandedId === id) this.driftExpandedId = null;
                    this.fetchDriftBaselines();
                }
            } catch { /* silent */ }
        },

        async setBaselineFromAgent(baselineId, hostname) {
            if (!hostname) { this.addToast('Select an agent first', 'warn'); return; }
            try {
                var res = await fetch('/api/baselines/' + baselineId + '/set-from/' + hostname, {
                    method: 'POST',
                    headers: { 'Authorization': 'Bearer ' + this._token() },
                });
                if (res.ok) {
                    var data = await res.json();
                    this.addToast('Baseline hash set from ' + hostname, 'ok');
                    this.fetchDriftBaselines();
                } else {
                    var err = await res.json().catch(function() { return {}; });
                    this.addToast(err.detail || 'Failed to set from agent', 'error');
                }
            } catch { /* silent */ }
        },

        async triggerDriftCheck() {
            this.driftCheckLoading = true;
            try {
                var res = await fetch('/api/baselines/check', {
                    method: 'POST',
                    headers: { 'Authorization': 'Bearer ' + this._token() },
                });
                if (res.ok) {
                    this.addToast('Drift check started', 'ok');
                    // Refresh after a short delay to let results come in
                    var self = this;
                    setTimeout(function() { self.fetchDriftBaselines(); }, 5000);
                }
            } catch { /* silent */ }
            finally { this.driftCheckLoading = false; }
        },

        async expandDriftBaseline(id) {
            if (this.driftExpandedId === id) {
                this.driftExpandedId = null;
                this.driftResults = [];
                return;
            }
            this.driftExpandedId = id;
            try {
                var res = await fetch('/api/baselines/' + id + '/results', {
                    headers: { 'Authorization': 'Bearer ' + this._token() },
                });
                if (res.ok) {
                    var data = await res.json();
                    this.driftResults = data.results || [];
                }
            } catch { /* silent */ }
        },

        // ── Network Discovery ───────────────────────────────────────────────

        async fetchNetworkDevices() {
            try {
                var res = await fetch('/api/network/devices', {
                    headers: { 'Authorization': 'Bearer ' + this._token() },
                });
                if (res.ok) this.networkDevices = await res.json();
            } catch { /* silent */ }
        },

        async triggerNetworkDiscover() {
            if (!this.networkDiscoverHost) return;
            this.networkDiscoverLoading = true;
            try {
                var res = await fetch('/api/network/discover/' + encodeURIComponent(this.networkDiscoverHost), {
                    method: 'POST',
                    headers: { 'Authorization': 'Bearer ' + this._token() },
                });
                if (res.ok) {
                    this.addToast('Discovery started on ' + this.networkDiscoverHost, 'success');
                    // Poll for results after a delay
                    var self = this;
                    setTimeout(function() { self.fetchNetworkDevices(); }, 8000);
                } else {
                    var data = await res.json().catch(function() { return {}; });
                    this.addToast(data.detail || 'Discovery failed', 'error');
                }
            } catch {
                this.addToast('Network error', 'error');
            } finally {
                this.networkDiscoverLoading = false;
            }
        },

        async deleteNetworkDevice(id) {
            if (!confirm('Remove this device from the list?')) return;
            try {
                var res = await fetch('/api/network/devices/' + id, {
                    method: 'DELETE',
                    headers: { 'Authorization': 'Bearer ' + this._token() },
                });
                if (res.ok) {
                    this.networkDevices = this.networkDevices.filter(function(d) { return d.id !== id; });
                    this.addToast('Device removed', 'success');
                }
            } catch { /* silent */ }
        },

        networkSubnets() {
            var groups = {};
            (this.networkDevices || []).forEach(function(d) {
                var parts = (d.ip || '').split('.');
                var prefix = parts.length >= 3 ? parts.slice(0, 3).join('.') : 'other';
                if (!groups[prefix]) groups[prefix] = { prefix: prefix, devices: [] };
                groups[prefix].devices.push(d);
            });
            var result = Object.values(groups);
            result.sort(function(a, b) { return a.prefix.localeCompare(b.prefix); });
            return result;
        },

        // ── Security Posture Scoring ─────────────────────────────────────────
        securityScore: null,
        securityAgentCount: 0,
        securityAgents: [],
        securityFindings: [],
        securityHistory: [],
        securityScanning: false,
        securityFilterSeverity: '',
        securityFilterHost: '',
        _securityScoreChart: null,

        async fetchSecurityData() {
            try {
                var scoreRes = await fetch('/api/security/score', {
                    headers: { 'Authorization': 'Bearer ' + this._token() },
                });
                if (scoreRes.ok) {
                    var scoreData = await scoreRes.json();
                    this.securityScore = scoreData.score;
                    this.securityAgentCount = scoreData.agent_count || 0;
                    this.securityAgents = scoreData.agents || [];
                }

                var params = new URLSearchParams();
                if (this.securityFilterSeverity) params.set('severity', this.securityFilterSeverity);
                if (this.securityFilterHost) params.set('hostname', this.securityFilterHost);
                var findingsRes = await fetch('/api/security/findings?' + params, {
                    headers: { 'Authorization': 'Bearer ' + this._token() },
                });
                if (findingsRes.ok) {
                    this.securityFindings = await findingsRes.json();
                }

                var histRes = await fetch('/api/security/history?limit=50', {
                    headers: { 'Authorization': 'Bearer ' + this._token() },
                });
                if (histRes.ok) {
                    this.securityHistory = await histRes.json();
                    this.$nextTick(() => this._renderSecurityChart());
                }
            } catch { /* silent */ }
        },

        async securityScanAll() {
            this.securityScanning = true;
            try {
                var res = await fetch('/api/security/scan-all', {
                    method: 'POST',
                    headers: { 'Authorization': 'Bearer ' + this._token() },
                });
                if (res.ok) {
                    var data = await res.json();
                    this.addToast('Security scan queued for ' + (data.count || 0) + ' agent(s)', 'info');
                    // Poll for results after a delay
                    setTimeout(() => this.fetchSecurityData(), 10000);
                } else {
                    this.addToast('Failed to start scan', 'error');
                }
            } catch {
                this.addToast('Scan request failed', 'error');
            }
            this.securityScanning = false;
        },

        async securityScanHost(hostname) {
            try {
                var res = await fetch('/api/security/scan/' + encodeURIComponent(hostname), {
                    method: 'POST',
                    headers: { 'Authorization': 'Bearer ' + this._token() },
                });
                if (res.ok) {
                    this.addToast('Security scan queued for ' + hostname, 'info');
                    setTimeout(() => this.fetchSecurityData(), 10000);
                } else {
                    this.addToast('Failed to start scan for ' + hostname, 'error');
                }
            } catch {
                this.addToast('Scan request failed', 'error');
            }
        },

        _renderSecurityChart() {
            if (typeof Chart === 'undefined' || !this.securityHistory.length) return;
            var canvas = document.getElementById('securityScoreChart');
            if (!canvas) return;
            if (this._securityScoreChart) { this._securityScoreChart.destroy(); this._securityScoreChart = null; }

            // Group by hostname, sort by time
            var byHost = {};
            this.securityHistory.forEach(function(h) {
                if (!byHost[h.hostname]) byHost[h.hostname] = [];
                byHost[h.hostname].push(h);
            });
            var datasets = [];
            var colors = ['#3b82f6', '#10b981', '#f59e0b', '#ef4444', '#8b5cf6', '#ec4899'];
            var ci = 0;
            Object.keys(byHost).forEach(function(host) {
                var points = byHost[host].sort(function(a, b) { return a.scanned_at - b.scanned_at; });
                datasets.push({
                    label: host,
                    data: points.map(function(p) { return { x: new Date(p.scanned_at * 1000), y: p.score }; }),
                    borderColor: colors[ci % colors.length],
                    backgroundColor: 'transparent',
                    tension: 0.3,
                    pointRadius: 3,
                });
                ci++;
            });

            this._securityScoreChart = new Chart(canvas.getContext('2d'), {
                type: 'line',
                data: { datasets: datasets },
                options: {
                    responsive: true,
                    maintainAspectRatio: false,
                    scales: {
                        x: { type: 'time', time: { tooltipFormat: 'MMM d, HH:mm' }, grid: { color: 'rgba(255,255,255,0.05)' } },
                        y: { min: 0, max: 100, grid: { color: 'rgba(255,255,255,0.05)' } },
                    },
                    plugins: { legend: { labels: { color: 'rgba(255,255,255,0.7)', font: { size: 10 } } } },
                },
            });
        },

        // ── Backup Verification (Feature 4) ─────────────────────────────────────

        async fetchBackupVerifications() {
            this.backupVerifLoading = true;
            try {
                const res = await fetch('/api/backup/verifications?limit=50', {
                    headers: { 'Authorization': 'Bearer ' + this._token() },
                });
                if (res.ok) this.backupVerifications = await res.json();
            } catch { /* silent */ }
            this.backupVerifLoading = false;
        },

        async triggerBackupVerify() {
            const f = this.verifyForm;
            if (!f.hostname || !f.path) {
                this.addToast('Hostname and path are required', 'error');
                return;
            }
            this.verifyLoading = true;
            try {
                const res = await fetch('/api/backup/verify', {
                    method: 'POST',
                    headers: { 'Content-Type': 'application/json', 'Authorization': 'Bearer ' + this._token() },
                    body: JSON.stringify({ hostname: f.hostname, path: f.path, verification_type: f.verification_type }),
                });
                if (res.ok) {
                    const data = await res.json();
                    this.addToast(`Verification ${data.status}: ${data.id}`, 'success');
                    setTimeout(() => this.fetchBackupVerifications(), 3000);
                } else {
                    const err = await res.json().catch(() => ({}));
                    this.addToast('Verify failed: ' + (err.detail || res.statusText), 'error');
                }
            } catch (e) {
                this.addToast('Verify failed: ' + e.message, 'error');
            }
            this.verifyLoading = false;
        },

        async fetchBackup321Status() {
            this.backup321Loading = true;
            try {
                const res = await fetch('/api/backup/321-status', {
                    headers: { 'Authorization': 'Bearer ' + this._token() },
                });
                if (res.ok) this.backup321Status = await res.json();
            } catch { /* silent */ }
            this.backup321Loading = false;
        },

        async updateBackup321(name, field, value) {
            const body = { backup_name: name };
            body[field] = value;
            try {
                const res = await fetch('/api/backup/321-status', {
                    method: 'PUT',
                    headers: { 'Content-Type': 'application/json', 'Authorization': 'Bearer ' + this._token() },
                    body: JSON.stringify(body),
                });
                if (res.ok) {
                    this.addToast('3-2-1 status updated', 'success');
                    this.fetchBackup321Status();
                } else {
                    const err = await res.json().catch(() => ({}));
                    this.addToast('Update failed: ' + (err.detail || res.statusText), 'error');
                }
            } catch (e) {
                this.addToast('Update failed: ' + e.message, 'error');
            }
        },

        async addBackup321Entry() {
            const f = this.form321;
            if (!f.backup_name) {
                this.addToast('Backup name is required', 'error');
                return;
            }
            try {
                const res = await fetch('/api/backup/321-status', {
                    method: 'PUT',
                    headers: { 'Content-Type': 'application/json', 'Authorization': 'Bearer ' + this._token() },
                    body: JSON.stringify({
                        backup_name: f.backup_name,
                        copies: f.copies || 0,
                        media_types: f.media_types && f.media_types.length ? f.media_types : [],
                        has_offsite: !!f.has_offsite,
                    }),
                });
                if (res.ok) {
                    this.addToast('3-2-1 entry added', 'success');
                    this.fetchBackup321Status();
                    this.form321 = { backup_name: '', copies: 0, media_types: [], has_offsite: false };
                    this.show321Modal = false;
                }
            } catch (e) {
                this.addToast('Failed: ' + e.message, 'error');
            }
        },

        backupFreshnessClass(verifiedAt) {
            if (!verifiedAt) return 'badge bd';
            const age = (Date.now() / 1000) - verifiedAt;
            if (age < 86400) return 'badge bs';
            if (age < 604800) return 'badge bw';
            return 'badge bd';
        },

        backupFreshnessLabel(verifiedAt) {
            if (!verifiedAt) return 'Never';
            const age = (Date.now() / 1000) - verifiedAt;
            if (age < 3600) return Math.floor(age / 60) + 'm ago';
            if (age < 86400) return Math.floor(age / 3600) + 'h ago';
            return Math.floor(age / 86400) + 'd ago';
        },

        // ── IaC Export ──────────────────────────────────────────────────────

        /** Generate Infrastructure-as-Code output from the selected format + agent. */
        async generateIaC() {
            if (!this.iacFormat) return;
            this.iacLoading = true;
            this.iacOutput = '';
            try {
                var endpoint = '/api/export/' + this.iacFormat;
                var params = this.iacHostname ? '?hostname=' + encodeURIComponent(this.iacHostname) : '';
                var res = await fetch(endpoint + params, {
                    headers: { 'Authorization': 'Bearer ' + this._token() },
                });
                if (!res.ok) {
                    var errText = await res.text();
                    throw new Error(errText || ('HTTP ' + res.status));
                }
                this.iacOutput = await res.text();
            } catch (e) {
                this.addToast('IaC export failed: ' + e.message, 'error');
            } finally {
                this.iacLoading = false;
            }
        },

        /** Download the current IaC output as a file. */
        downloadIaC() {
            if (!this.iacOutput) return;
            var ext = 'txt';
            var mime = 'text/plain';
            if (this.iacFormat === 'ansible') { ext = 'yml'; mime = 'text/yaml'; }
            else if (this.iacFormat === 'docker-compose') { ext = 'yml'; mime = 'text/yaml'; }
            else if (this.iacFormat === 'shell') { ext = 'sh'; mime = 'text/x-shellscript'; }
            var filename = 'noba-export-' + this.iacFormat + (this.iacHostname ? '-' + this.iacHostname : '') + '.' + ext;
            var blob = new Blob([this.iacOutput], { type: mime });
            var url = URL.createObjectURL(blob);
            var a = document.createElement('a');
            a.href = url;
            a.download = filename;
            document.body.appendChild(a);
            a.click();
            document.body.removeChild(a);
            URL.revokeObjectURL(url);
        },

        /** Copy IaC output to clipboard. */
        async copyIaC() {
            if (!this.iacOutput) return;
            try {
                await navigator.clipboard.writeText(this.iacOutput);
                this.addToast('Copied to clipboard', 'success');
            } catch {
                this.addToast('Failed to copy to clipboard', 'error');
            }
        },


        // ── Network Traffic Analysis ─────────────────────────────────────────

        /** Fetch network stats from an agent. */
        async fetchNetworkStats() {
            if (!this.trafficAgent) return;
            this.trafficLoading = true;
            this.trafficData = null;
            try {
                var res = await fetch('/api/agents/' + encodeURIComponent(this.trafficAgent) + '/network-stats', {
                    headers: { 'Authorization': 'Bearer ' + this._token() },
                });
                if (!res.ok) throw new Error('HTTP ' + res.status);
                var data = await res.json();
                if (data.status === 'queued') {
                    this.addToast('Command queued. Refresh in a few seconds.', 'info');
                } else {
                    this.trafficData = data;
                }
            } catch (e) {
                this.addToast('Failed to fetch network stats: ' + e.message, 'error');
            } finally {
                this.trafficLoading = false;
            }
        },

        /** Return traffic connections filtered by the search input. */
        filteredTrafficConns() {
            if (!this.trafficData || !this.trafficData.connections) return [];
            var filter = (this.trafficConnFilter || '').toLowerCase();
            if (!filter) return this.trafficData.connections;
            return this.trafficData.connections.filter(function(c) {
                return (c.process || '').toLowerCase().indexOf(filter) !== -1
                    || (c.local || '').toLowerCase().indexOf(filter) !== -1
                    || (c.remote || '').toLowerCase().indexOf(filter) !== -1
                    || (c.state || '').toLowerCase().indexOf(filter) !== -1
                    || String(c.pid || '').indexOf(filter) !== -1;
            });
        },
    };
}
