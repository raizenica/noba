/**
 * Actions & controls mixin for the NOBA dashboard component.
 *
 * Provides service/VM/container controls, script execution, history & audit,
 * SMART data, config backup/restore, and confirmation dialogs.
 * All methods use `this` which resolves to the parent Alpine component
 * instance after spreading.
 *
 * @returns {Object} Alpine component mixin (state + methods)
 */
function actionsMixin() {
    return {

        // ── Action / modal state ───────────────────────────────────────────────
        selectedLog: 'syserr', logContent: 'Loading...', logLoading: false,
        showModal: false, modalTitle: '', modalOutput: '', runningScript: false,
        showConfirmModal: false, confirmMessage: '', _pendingAction: null,

        // ── Job runner state ─────────────────────────────────────────────────
        activeRunId: null,
        showRunHistoryModal: false,
        runHistory: [],
        runHistoryLoading: false,

        // ── History & Audit state ──────────────────────────────────────────────
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

        // ── SMART disk health ──────────────────────────────────────────────────
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


        // ── Log viewer ─────────────────────────────────────────────────────────

        /**
         * Fetch the selected system log from the backend.
         * Auto-scrolls the log pane to the bottom.
         */
        async fetchLog() {
            if (!this.authenticated) return;
            this.logLoading = true;
            try {
                const res = await fetch('/api/log-viewer?type=' + this.selectedLog, {
                    headers: { 'Authorization': 'Bearer ' + this._token() },
                });
                if (res.ok) {
                    this.logContent = await res.text();
                    this.$nextTick(() => {
                        const el = document.querySelector('.log-pre');
                        if (el) el.scrollTop = el.scrollHeight;
                    });
                } else if (res.status === 401) {
                    this.authenticated = false;
                } else {
                    throw new Error(`HTTP ${res.status}`);
                }
            } catch (e) {
                this.logContent = 'Failed to fetch log: ' + e.message;
            } finally {
                this.logLoading = false;
            }
        },


        // ── Confirmation dialog ────────────────────────────────────────────────

        /** Show a confirmation modal before running a destructive action. */
        requestConfirm(message, fn) {
            this.confirmMessage    = message;
            this._pendingAction    = fn;
            this.showConfirmModal  = true;
        },

        /** Execute the pending confirmed action. */
        async runConfirmedAction() {
            this.showConfirmModal = false;
            if (this._pendingAction) {
                await this._pendingAction();
                this._pendingAction = null;
            }
        },


        // ── Service controls ───────────────────────────────────────────────────

        /**
         * Start/stop/restart a systemd service.
         * Destructive actions (stop, restart) require user confirmation.
         */
        async svcAction(svc, action) {
            if (!this.authenticated) return;
            const label = svc.name.replace('.service', '');
            const run = async () => {
                try {
                    const res = await fetch('/api/service-control', {
                        method: 'POST',
                        headers: { 'Content-Type': 'application/json', 'Authorization': 'Bearer ' + this._token() },
                        body: JSON.stringify({ service: svc.name, action, is_user: svc.is_user }),
                    });
                    if (res.ok) {
                        this.addToast(`${action}: ${label}`, 'success');
                        setTimeout(() => this.refreshStats(), 1200);
                    } else {
                        const d = await res.json().catch(() => ({}));
                        this.addToast(d.detail || `Failed: ${label}`, 'error');
                    }
                } catch {
                    this.addToast('Service control error', 'error');
                }
            };
            if (action === 'start') return run();
            this.requestConfirm(`${action} service "${label}"?`, run);
        },


        // ── TrueNAS VM controls ────────────────────────────────────────────────

        /**
         * Start/stop/restart a TrueNAS VM.
         * Destructive actions require user confirmation.
         */
        async vmAction(vmId, vmName, action) {
            if (!this.authenticated) return;
            const run = async () => {
                this.addToast(`Triggering ${action} on ${vmName}...`, 'info');
                try {
                    const res = await fetch('/api/truenas/vm', {
                        method: 'POST',
                        headers: { 'Content-Type': 'application/json', 'Authorization': 'Bearer ' + this._token() },
                        body: JSON.stringify({ id: vmId, action }),
                    });
                    if (res.ok) {
                        this.addToast(`VM ${vmName}: ${action} successful`, 'success');
                        setTimeout(() => this.refreshStats(), 1500);
                    } else {
                        const d = await res.json().catch(() => ({}));
                        this.addToast(d.detail || `VM ${vmName}: ${action} failed`, 'error');
                    }
                } catch {
                    this.addToast('VM control error', 'error');
                }
            };
            if (action === 'start') return run();
            this.requestConfirm(`${action} VM "${vmName}"?`, run);
        },


        // ── Webhooks ───────────────────────────────────────────────────────────

        /** Fire a custom webhook action by ID. */
        async triggerWebhook(actId, actName) {
            if (!this.authenticated) return;
            this.addToast(`Firing Webhook: ${actName}...`, 'info');
            try {
                const res = await fetch('/api/webhook', {
                    method: 'POST',
                    headers: { 'Content-Type': 'application/json', 'Authorization': 'Bearer ' + this._token() },
                    body: JSON.stringify({ id: actId }),
                });
                if (res.ok) {
                    this.addToast('Webhook successful', 'success');
                } else {
                    const d = await res.json().catch(() => ({}));
                    this.addToast(d.detail || 'Webhook failed', 'error');
                }
            } catch {
                this.addToast('Webhook error', 'error');
            }
        },


        // ── Script execution ───────────────────────────────────────────────────

        /**
         * Run a custom script via /api/run with live output polling.
         * Opens a modal showing the script's stdout in real-time.
         */
        async runScript(script, argStr = '') {
            if (!this.authenticated || this.runningScript) return;
            this.runningScript = true;
            this.activeRunId   = null;
            this.modalTitle    = `Running: ${script}`;
            this.modalOutput   = `>> [${new Date().toLocaleTimeString()}] Starting action...\n`;
            this.showModal     = true;

            const token = this._token();
            let runId = null;

            try {
                const res = await fetch('/api/run', {
                    method: 'POST',
                    headers: { 'Content-Type': 'application/json', 'Authorization': 'Bearer ' + token },
                    body: JSON.stringify({ script, args: argStr }),
                });
                if (!res.ok) {
                    const err = await res.json().catch(() => ({}));
                    this.modalTitle = '\u2717 Failed';
                    this.modalOutput += (err.detail || 'Request failed') + '\n';
                    this.addToast(err.detail || `${script} failed to start`, 'error');
                    this.runningScript = false;
                    return;
                }
                const result = await res.json();
                runId = result.run_id;
                this.activeRunId = runId;
            } catch {
                this.modalTitle = '\u2717 Connection Error';
                this.addToast('Connection error', 'error');
                this.runningScript = false;
                return;
            }

            // Poll for job output until completion
            const poll = setInterval(async () => {
                if (!this.authenticated) { clearInterval(poll); this.runningScript = false; return; }
                try {
                    const r = await fetch(`/api/runs/${runId}`, {
                        headers: { 'Authorization': 'Bearer ' + token },
                    });
                    if (!r.ok) return;
                    const run = await r.json();
                    if (run.output) {
                        this.modalOutput = run.output;
                        const el = document.getElementById('console-out');
                        if (el) el.scrollTop = el.scrollHeight;
                    }
                    if (run.status !== 'running') {
                        clearInterval(poll);
                        const ok = run.status === 'done';
                        this.modalTitle = ok ? '\u2713 Completed'
                            : run.status === 'cancelled' ? '\u2718 Cancelled'
                            : '\u2717 ' + (run.status === 'timeout' ? 'Timed Out' : 'Failed');
                        if (run.error) this.modalOutput += '\n' + run.error + '\n';
                        this.addToast(`${script} ${run.status}`, ok ? 'success' : 'error');
                        this.runningScript = false;
                        this.activeRunId = null;
                        await this.refreshStats();
                    }
                } catch { /* non-fatal */ }
            }, 1000);
        },

        /** Cancel the currently active job run. */
        async cancelActiveRun() {
            if (!this.activeRunId) return;
            try {
                const res = await fetch(`/api/runs/${this.activeRunId}/cancel`, {
                    method: 'POST',
                    headers: { 'Authorization': 'Bearer ' + this._token() },
                });
                if (res.ok) {
                    this.addToast('Cancellation requested', 'info');
                } else {
                    const d = await res.json().catch(() => ({}));
                    this.addToast(d.detail || 'Cancel failed', 'error');
                }
            } catch {
                this.addToast('Cancel request failed', 'error');
            }
        },

        // ── Run History ───────────────────────────────────────────────────────

        /** Open the run history modal and fetch recent runs. */
        async openRunHistory() {
            this.showRunHistoryModal = true;
            await this.fetchRunHistory();
        },

        /** Fetch recent job runs from the API. */
        async fetchRunHistory() {
            this.runHistoryLoading = true;
            try {
                const res = await fetch('/api/runs?limit=50', {
                    headers: { 'Authorization': 'Bearer ' + this._token() },
                });
                if (!res.ok) throw new Error(`HTTP ${res.status}`);
                this.runHistory = await res.json();
            } catch (e) {
                this.addToast('Failed to load run history: ' + e.message, 'error');
            } finally {
                this.runHistoryLoading = false;
            }
        },

        /** Format a Unix timestamp for display. */
        fmtRunTime(ts) {
            if (!ts) return '\u2014';
            return new Date(ts * 1000).toLocaleString();
        },

        /** Return a CSS badge class for a job status. */
        runStatusClass(status) {
            if (status === 'done') return 'bs';
            if (status === 'running') return 'bi';
            if (status === 'cancelled') return 'bw';
            return 'bd';
        },


        // ── Container controls ─────────────────────────────────────────────────

        /**
         * Start/stop/restart a Docker container.
         * Destructive actions require user confirmation.
         */
        async containerAction(name, action) {
            if (!name) return;
            const label = `${action} ${name}`;
            const run = async () => {
                try {
                    const res = await fetch('/api/container-control', {
                        method:  'POST',
                        headers: {
                            'Content-Type':  'application/json',
                            'Authorization': 'Bearer ' + this._token(),
                        },
                        body: JSON.stringify({ name, action }),
                    });
                    if (res.ok) {
                        const data = await res.json();
                        this.addToast(`${label} — OK`, 'success');
                        setTimeout(() => this.refreshStats(), 1500);
                    } else {
                        const data = await res.json().catch(() => ({}));
                        this.addToast(data.detail || `${label} failed`, 'error');
                    }
                } catch (e) {
                    this.addToast(`${label}: ${e.message}`, 'error');
                }
            };
            if (action === 'start') return run();
            this.requestConfirm(`${action} container "${name}"?`, run);
        },


        // ── History & Audit ────────────────────────────────────────────────────

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

        /** Open the audit log modal. */
        openAuditModal() {
            if (this.userRole !== 'admin') return;
            this.showAuditModal = true;
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


        // ── Layout Backup / Restore ─────────────────────────────────────────

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


        // ── Backup Explorer ──────────────────────────────────────────────────

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

        /** Format file size for display. */
        fmtFileSize(bytes) {
            if (bytes == null) return '\u2014';
            if (bytes < 1024) return bytes + ' B';
            if (bytes < 1024 * 1024) return (bytes / 1024).toFixed(1) + ' KB';
            if (bytes < 1024 * 1024 * 1024) return (bytes / (1024 * 1024)).toFixed(1) + ' MB';
            return (bytes / (1024 * 1024 * 1024)).toFixed(2) + ' GB';
        },


        // ── Session Management ──────────────────────────────────────────────

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


        // ── Filtered Audit ──────────────────────────────────────────────────

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


        // ── Automation CRUD ─────────────────────────────────────────────────

        showAutoModal: false,
        autoModalMode: 'create',
        autoForm: { id: '', name: '', type: 'script', config: {}, schedule: '', enabled: true },
        autoList: [],
        autoListLoading: false,
        autoFilter: 'all',
        autoSearch: '',
        autoTemplates: [],
        autoStats: {},

        // ── Run detail ──────────────────────────────────────────────────────
        showRunDetailModal: false,
        runDetail: null,
        runDetailSteps: [],
        runDetailLoading: false,

        // ── Job notification poller ─────────────────────────────────────────
        _jobNotifTimer: null,
        _lastSeenRunId: 0,

        /** Fetch all automations from the DB. */
        async fetchAutomations() {
            this.autoListLoading = true;
            try {
                const res = await fetch('/api/automations', {
                    headers: { 'Authorization': 'Bearer ' + this._token() },
                });
                if (!res.ok) throw new Error(`HTTP ${res.status}`);
                this.autoList = await res.json();
            } catch (e) {
                this.addToast('Failed to load automations: ' + e.message, 'error');
            } finally {
                this.autoListLoading = false;
            }
        },

        /** Open the create automation modal with a blank form. */
        openCreateAuto() {
            this.autoForm = { id: '', name: '', type: 'script', config: {}, schedule: '', enabled: true };
            this.autoModalMode = 'create';
            this.showAutoModal = true;
        },

        /** Open the edit modal populated with an existing automation. */
        openEditAuto(auto) {
            this.autoForm = {
                id: auto.id,
                name: auto.name,
                type: auto.type,
                config: JSON.parse(JSON.stringify(auto.config || {})),
                schedule: auto.schedule || '',
                enabled: auto.enabled,
            };
            this.autoModalMode = 'edit';
            this.showAutoModal = true;
        },

        /** Save (create or update) the automation from the form. */
        async saveAutomation() {
            const f = this.autoForm;
            if (!f.name.trim()) { this.addToast('Name is required', 'error'); return; }
            const payload = { name: f.name, type: f.type, config: f.config,
                              schedule: f.schedule || null, enabled: f.enabled };
            try {
                const url = this.autoModalMode === 'create'
                    ? '/api/automations'
                    : `/api/automations/${f.id}`;
                const method = this.autoModalMode === 'create' ? 'POST' : 'PUT';
                const res = await fetch(url, {
                    method,
                    headers: { 'Content-Type': 'application/json', 'Authorization': 'Bearer ' + this._token() },
                    body: JSON.stringify(payload),
                });
                if (!res.ok) {
                    const d = await res.json().catch(() => ({}));
                    this.addToast(d.detail || 'Save failed', 'error');
                    return;
                }
                this.showAutoModal = false;
                this.addToast(this.autoModalMode === 'create' ? 'Automation created' : 'Automation updated', 'success');
                await this.fetchAutomations();
            } catch (e) {
                this.addToast('Save error: ' + e.message, 'error');
            }
        },

        /** Delete an automation (admin only, with confirmation). */
        confirmDeleteAuto(auto) {
            this.requestConfirm(`Delete automation "${auto.name}"?`, async () => {
                try {
                    const res = await fetch(`/api/automations/${auto.id}`, {
                        method: 'DELETE',
                        headers: { 'Authorization': 'Bearer ' + this._token() },
                    });
                    if (!res.ok) {
                        const d = await res.json().catch(() => ({}));
                        this.addToast(d.detail || 'Delete failed', 'error');
                        return;
                    }
                    this.addToast('Automation deleted', 'success');
                    await this.fetchAutomations();
                } catch (e) {
                    this.addToast('Delete error: ' + e.message, 'error');
                }
            });
        },

        /** Return automations filtered by type tab and search text. */
        get filteredAutoList() {
            let list = this.autoList || [];
            if (this.autoFilter !== 'all') {
                list = list.filter(a => a.type === this.autoFilter);
            }
            if (this.autoSearch) {
                const q = this.autoSearch.toLowerCase();
                list = list.filter(a => a.name.toLowerCase().includes(q));
            }
            return list;
        },

        /** Open the run detail modal for a specific run. */
        async openRunDetail(run) {
            this.runDetail = run;
            this.runDetailSteps = [];
            this.showRunDetailModal = true;
            this.runDetailLoading = true;
            const token = this._token();
            try {
                // Fetch full run detail with output
                const res = await fetch(`/api/runs/${run.id}`, {
                    headers: { 'Authorization': 'Bearer ' + token },
                });
                if (res.ok) this.runDetail = await res.json();

                // If this is a workflow step or parent, fetch sibling steps
                const trigger = this.runDetail.trigger || '';
                let prefix = '';
                if (trigger.startsWith('workflow:')) {
                    // Extract workflow auto_id from trigger like "workflow:abc123:step0"
                    const parts = trigger.split(':');
                    if (parts.length >= 2) prefix = `workflow:${parts[1]}`;
                }
                if (prefix) {
                    const stepsRes = await fetch(`/api/runs?trigger_prefix=${encodeURIComponent(prefix)}&limit=50`, {
                        headers: { 'Authorization': 'Bearer ' + token },
                    });
                    if (stepsRes.ok) {
                        const steps = await stepsRes.json();
                        this.runDetailSteps = steps.sort((a, b) => (a.started_at || 0) - (b.started_at || 0));
                    }
                }
            } catch (e) {
                this.addToast('Failed to load run details: ' + e.message, 'error');
            } finally {
                this.runDetailLoading = false;
            }
        },

        /** Start polling for background job completions. */
        async startJobNotifPoller() {
            if (this._jobNotifTimer) clearInterval(this._jobNotifTimer);
            // Initialize with current max run ID to avoid toasting old runs
            await this._initJobNotifBaseline();
            this._jobNotifTimer = setInterval(() => this._checkJobCompletions(), 15000);
        },

        /** Stop the job notification poller. */
        stopJobNotifPoller() {
            if (this._jobNotifTimer) { clearInterval(this._jobNotifTimer); this._jobNotifTimer = null; }
        },

        async _initJobNotifBaseline() {
            try {
                const res = await fetch('/api/runs?limit=1', {
                    headers: { 'Authorization': 'Bearer ' + this._token() },
                });
                if (res.ok) {
                    const runs = await res.json();
                    this._lastSeenRunId = runs.length > 0 ? runs[0].id : 0;
                }
            } catch { /* silent */ }
        },

        async _checkJobCompletions() {
            if (!this.authenticated) return;
            try {
                const res = await fetch('/api/runs?limit=10', {
                    headers: { 'Authorization': 'Bearer ' + this._token() },
                });
                if (!res.ok) return;
                const runs = await res.json();
                for (const run of runs) {
                    if (run.id <= this._lastSeenRunId) continue;
                    if (run.status === 'running' || run.status === 'queued') continue;
                    // Only notify for scheduled/alert/workflow runs (not manual)
                    const trigger = run.trigger || '';
                    if (trigger.startsWith('schedule:') || trigger.startsWith('alert:') || trigger.startsWith('workflow:')) {
                        const ok = run.status === 'done';
                        const label = trigger.split(':').slice(0, 2).join(':');
                        this.addToast(`Job #${run.id} (${label}) ${run.status}`, ok ? 'success' : 'error');
                    }
                }
                if (runs.length > 0) {
                    this._lastSeenRunId = Math.max(this._lastSeenRunId, ...runs.map(r => r.id));
                }
            } catch { /* silent */ }
        },

        /** Fetch automation templates from the backend. */
        async fetchAutoTemplates() {
            try {
                const res = await fetch('/api/automations/templates', {
                    headers: { 'Authorization': 'Bearer ' + this._token() },
                });
                if (res.ok) this.autoTemplates = await res.json();
            } catch { /* silent */ }
        },

        /** Fetch per-automation run statistics. */
        async fetchAutoStats() {
            try {
                const res = await fetch('/api/automations/stats', {
                    headers: { 'Authorization': 'Bearer ' + this._token() },
                });
                if (res.ok) this.autoStats = await res.json();
            } catch { /* silent */ }
        },

        /** Apply a template to the create automation form. */
        applyTemplate(tpl) {
            this.autoForm.name = tpl.name;
            this.autoForm.type = tpl.type;
            this.autoForm.config = JSON.parse(JSON.stringify(tpl.config || {}));
            this.autoForm.schedule = tpl.schedule || '';
            this.autoForm.enabled = true;
        },

        /** Export all automations as a YAML file download. */
        async exportAutomations() {
            try {
                const res = await fetch('/api/automations/export', {
                    headers: { 'Authorization': 'Bearer ' + this._token() },
                });
                if (!res.ok) throw new Error(`HTTP ${res.status}`);
                const blob = await res.blob();
                const objUrl = URL.createObjectURL(blob);
                try {
                    const a = document.createElement('a');
                    a.href = objUrl;
                    a.download = 'noba-automations.yaml';
                    document.body.appendChild(a);
                    a.click();
                    document.body.removeChild(a);
                } finally {
                    URL.revokeObjectURL(objUrl);
                }
                this.addToast('Automations exported', 'success');
            } catch (e) {
                this.addToast('Export failed: ' + e.message, 'error');
            }
        },

        /** Import automations from a YAML file. */
        async importAutomations(event) {
            const file = event.target.files && event.target.files[0];
            if (!file) return;
            if (!file.name.match(/\.(yaml|yml)$/i)) {
                this.addToast('Please select a .yaml or .yml file', 'error');
                return;
            }
            try {
                const body = await file.arrayBuffer();
                const res = await fetch('/api/automations/import?mode=skip', {
                    method: 'POST',
                    headers: {
                        'Content-Type': 'application/x-yaml',
                        'Authorization': 'Bearer ' + this._token(),
                    },
                    body,
                });
                const data = await res.json();
                if (res.ok) {
                    this.addToast(`Imported ${data.imported}, skipped ${data.skipped}`, 'success');
                    await this.fetchAutomations();
                    await this.fetchAutoStats();
                } else {
                    this.addToast(data.detail || 'Import failed', 'error');
                }
            } catch (e) {
                this.addToast('Import error: ' + e.message, 'error');
            } finally {
                event.target.value = '';
            }
        },

        /** Return stat summary for an automation (from autoStats). */
        getAutoStat(autoId) {
            return this.autoStats[autoId] || null;
        },

        /** Format average duration in seconds to human-readable. */
        fmtDuration(secs) {
            if (!secs && secs !== 0) return '\u2014';
            if (secs < 60) return Math.round(secs) + 's';
            return Math.floor(secs / 60) + 'm ' + Math.round(secs % 60) + 's';
        },

        /** Manually run an automation and show live output. */
        async runAutomation(auto) {
            if (!this.authenticated || this.runningScript) return;
            this.runningScript = true;
            this.activeRunId = null;
            this.modalTitle = `Running: ${auto.name}`;
            this.modalOutput = `>> [${new Date().toLocaleTimeString()}] Starting automation...\n`;
            this.showModal = true;

            const token = this._token();
            let runId = null;

            try {
                const res = await fetch(`/api/automations/${auto.id}/run`, {
                    method: 'POST',
                    headers: { 'Authorization': 'Bearer ' + token },
                });
                if (!res.ok) {
                    const err = await res.json().catch(() => ({}));
                    this.modalTitle = '\u2717 Failed';
                    this.modalOutput += (err.detail || 'Request failed') + '\n';
                    this.addToast(err.detail || `${auto.name} failed to start`, 'error');
                    this.runningScript = false;
                    return;
                }
                const result = await res.json();
                if (result.workflow) {
                    this.modalTitle = '\u2713 Workflow Started';
                    this.modalOutput += `Workflow "${auto.name}" started with ${result.steps} steps.\nCheck Run History for progress.\n`;
                    this.addToast(`Workflow started (${result.steps} steps)`, 'success');
                    this.runningScript = false;
                    return;
                }
                runId = result.run_id;
                this.activeRunId = runId;
            } catch {
                this.modalTitle = '\u2717 Connection Error';
                this.addToast('Connection error', 'error');
                this.runningScript = false;
                return;
            }

            const poll = setInterval(async () => {
                if (!this.authenticated) { clearInterval(poll); this.runningScript = false; return; }
                try {
                    const r = await fetch(`/api/runs/${runId}`, {
                        headers: { 'Authorization': 'Bearer ' + token },
                    });
                    if (!r.ok) return;
                    const run = await r.json();
                    if (run.output) {
                        this.modalOutput = run.output;
                        const el = document.getElementById('console-out');
                        if (el) el.scrollTop = el.scrollHeight;
                    }
                    if (run.status !== 'running') {
                        clearInterval(poll);
                        const ok = run.status === 'done';
                        this.modalTitle = ok ? '\u2713 Completed'
                            : run.status === 'cancelled' ? '\u2718 Cancelled'
                            : '\u2717 ' + (run.status === 'timeout' ? 'Timed Out' : 'Failed');
                        if (run.error) this.modalOutput += '\n' + run.error + '\n';
                        this.addToast(`${auto.name} ${run.status}`, ok ? 'success' : 'error');
                        this.runningScript = false;
                        this.activeRunId = null;
                    }
                } catch { /* non-fatal */ }
            }, 1000);
        },


        // ── Home Assistant Control (Round 5) ────────────────────────────────

        /** Toggle a Home Assistant entity via the backend proxy. */
        async hassToggle(domain, entityId) {
            if (!confirm(`Toggle ${entityId}?`)) return;
            try {
                const res = await fetch(`/api/hass/services/${domain}/toggle`, {
                    method: 'POST',
                    headers: { 'Content-Type': 'application/json', 'Authorization': 'Bearer ' + this._token() },
                    body: JSON.stringify({ entity_id: entityId }),
                });
                if (!res.ok) throw new Error(`HTTP ${res.status}`);
                this.addToast(`Toggled ${entityId}`, 'success');
            } catch (e) {
                this.addToast('HA toggle failed: ' + e.message, 'error');
            }
        },


        // ── Wake-on-LAN (Round 9) ──────────────────────────────────────────

        /** Send a Wake-on-LAN magic packet to a MAC address. */
        async sendWol(mac, name) {
            try {
                const res = await fetch('/api/wol', {
                    method: 'POST',
                    headers: { 'Content-Type': 'application/json', 'Authorization': 'Bearer ' + this._token() },
                    body: JSON.stringify({ mac }),
                });
                const d = await res.json();
                this.addToast(d.success ? `WOL sent to ${name || mac}` : 'WOL failed', d.success ? 'success' : 'error');
            } catch (e) {
                this.addToast('WOL failed: ' + e.message, 'error');
            }
        },


        // ── Pi-hole / AdGuard DNS Toggle (Round 9) ─────────────────────────

        /** Enable or disable DNS filtering (Pi-hole / AdGuard). */
        async toggleDns(action, duration) {
            try {
                const res = await fetch('/api/pihole/toggle', {
                    method: 'POST',
                    headers: { 'Content-Type': 'application/json', 'Authorization': 'Bearer ' + this._token() },
                    body: JSON.stringify({ action: action || 'disable', duration: duration || 300 }),
                });
                if (!res.ok) throw new Error(`HTTP ${res.status}`);
                this.addToast(`DNS filtering ${action === 'enable' ? 'enabled' : 'disabled'}`, 'success');
            } catch (e) {
                this.addToast('DNS toggle failed: ' + e.message, 'error');
            }
        },


        // ── Docker Compose (Round 9) ────────────────────────────────────────

        composeProjectList: [],
        composeLoading: false,

        /** Fetch the list of Docker Compose projects. */
        async fetchComposeProjects() {
            this.composeLoading = true;
            try {
                const res = await fetch('/api/compose/projects', {
                    headers: { 'Authorization': 'Bearer ' + this._token() },
                });
                if (res.ok) this.composeProjectList = await res.json();
            } catch { /* silent */ }
            this.composeLoading = false;
        },

        /** Run an action (up, down, restart, pull) on a Compose project. */
        async composeAction(project, action) {
            if (!confirm(`${action} compose project "${project}"?`)) return;
            try {
                const res = await fetch(`/api/compose/${encodeURIComponent(project)}/${action}`, {
                    method: 'POST',
                    headers: { 'Authorization': 'Bearer ' + this._token() },
                });
                const d = await res.json();
                this.addToast(d.success ? `${action} ${project}: OK` : `${action} ${project}: failed`, d.success ? 'success' : 'error');
                this.fetchComposeProjects();
            } catch (e) {
                this.addToast(`Compose action failed: ${e.message}`, 'error');
            }
        },


        // ── Alert History (Round 2) ─────────────────────────────────────────

        alertHistory: [],
        alertHistoryLoading: false,
        showAlertHistoryModal: false,

        /** Fetch recent alert history entries. */
        async fetchAlertHistory() {
            this.alertHistoryLoading = true;
            try {
                const res = await fetch('/api/alert-history?limit=100', {
                    headers: { 'Authorization': 'Bearer ' + this._token() },
                });
                if (res.ok) this.alertHistory = await res.json();
            } catch { /* silent */ }
            this.alertHistoryLoading = false;
        },


        // ── SLA Reporting (Round 2) ─────────────────────────────────────────

        slaData: null,
        slaLoading: false,

        /** Fetch SLA uptime data for a given alert rule. */
        async fetchSla(ruleId, windowHours) {
            this.slaLoading = true;
            try {
                const res = await fetch(`/api/sla/${encodeURIComponent(ruleId)}?window=${windowHours || 720}`, {
                    headers: { 'Authorization': 'Bearer ' + this._token() },
                });
                if (res.ok) this.slaData = await res.json();
            } catch { /* silent */ }
            this.slaLoading = false;
        },


        // ── CPU Governor (Round 9) ──────────────────────────────────────────

        /** Set the CPU frequency scaling governor. */
        async setCpuGovernor(governor) {
            if (!confirm(`Set CPU governor to ${governor}?`)) return;
            try {
                const res = await fetch('/api/system/cpu-governor', {
                    method: 'POST',
                    headers: { 'Content-Type': 'application/json', 'Authorization': 'Bearer ' + this._token() },
                    body: JSON.stringify({ governor }),
                });
                const d = await res.json();
                this.addToast(d.success ? `Governor set to ${governor}` : 'Failed to set governor', d.success ? 'success' : 'error');
            } catch (e) {
                this.addToast('Governor change failed: ' + e.message, 'error');
            }
        },


        // ── API Key Management (Round 6) ────────────────────────────────────

        apiKeys: [],
        showApiKeysModal: false,
        newApiKeyName: '',
        newApiKeyRole: 'viewer',
        lastCreatedKey: '',

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


        // ── TOTP 2FA Setup (Round 6) ────────────────────────────────────────

        totpSecret: '',
        totpUri: '',
        totpCode: '',
        showTotpSetup: false,

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


        // ── Prometheus Export (Round 8) ──────────────────────────────────────

        /** Return the Prometheus metrics endpoint URL. */
        get prometheusUrl() {
            return '/api/metrics/prometheus';
        },


        // ── Chart Export (Round 7) ──────────────────────────────────────────

        /** Export the currently displayed history chart as a PNG download. */
        exportChart() {
            const canvas = document.querySelector('.history-chart canvas');
            if (!canvas) return;
            const url = canvas.toDataURL('image/png');
            const a = document.createElement('a');
            a.href = url;
            a.download = 'noba-chart.png';
            a.click();
        },


        // ── Home Assistant Deep Integration ──────────────────────────────────
        hassEntities: [],
        hassEntitiesLoading: false,
        hassEntityFilter: '',
        hassDomainFilter: '',
        showHassModal: false,

        async fetchHassEntities(domain) {
            this.hassEntitiesLoading = true;
            const qs = domain ? `?domain=${domain}` : '';
            try {
                const res = await fetch(`/api/hass/entities${qs}`, {
                    headers: { 'Authorization': 'Bearer ' + this._token() },
                });
                if (!res.ok) throw new Error(`HTTP ${res.status}`);
                const d = await res.json();
                this.hassEntities = d.entities || [];
            } catch (e) {
                this.addToast('Failed to load HA entities: ' + e.message, 'error');
            }
            this.hassEntitiesLoading = false;
        },

        get filteredHassEntities() {
            let ents = this.hassEntities;
            if (this.hassDomainFilter) ents = ents.filter(e => e.domain === this.hassDomainFilter);
            if (this.hassEntityFilter) {
                const q = this.hassEntityFilter.toLowerCase();
                ents = ents.filter(e => e.name.toLowerCase().includes(q) || e.entity_id.toLowerCase().includes(q));
            }
            return ents.slice(0, 100);
        },

        get hassDomains() {
            const domains = new Set(this.hassEntities.map(e => e.domain));
            return [...domains].sort();
        },

        async hassToggleEntity(entityId) {
            try {
                const res = await fetch(`/api/hass/toggle/${entityId}`, {
                    method: 'POST',
                    headers: { 'Authorization': 'Bearer ' + this._token() },
                });
                if (!res.ok) throw new Error(`HTTP ${res.status}`);
                this.addToast(`Toggled ${entityId}`, 'success');
                setTimeout(() => this.fetchHassEntities(this.hassDomainFilter), 1000);
            } catch (e) {
                this.addToast('Toggle failed: ' + e.message, 'error');
            }
        },


        // ── Docker Deep Management ───────────────────────────────────────────
        containerLogs: '',
        containerLogsName: '',
        containerLogsLoading: false,
        showContainerLogsModal: false,
        containerInspect: null,
        showContainerInspectModal: false,
        containerStats: [],
        containerStatsLoading: false,

        async fetchContainerLogs(name, lines) {
            this.containerLogsName = name;
            this.containerLogsLoading = true;
            this.showContainerLogsModal = true;
            try {
                const res = await fetch(`/api/containers/${encodeURIComponent(name)}/logs?lines=${lines || 200}`, {
                    headers: { 'Authorization': 'Bearer ' + this._token() },
                });
                this.containerLogs = res.ok ? await res.text() : 'Failed to fetch logs.';
            } catch (e) {
                this.containerLogs = 'Error: ' + e.message;
            }
            this.containerLogsLoading = false;
        },

        async fetchContainerInspect(name) {
            this.showContainerInspectModal = true;
            try {
                const res = await fetch(`/api/containers/${encodeURIComponent(name)}/inspect`, {
                    headers: { 'Authorization': 'Bearer ' + this._token() },
                });
                this.containerInspect = res.ok ? await res.json() : null;
            } catch { this.containerInspect = null; }
        },

        async fetchContainerStats() {
            this.containerStatsLoading = true;
            try {
                const res = await fetch('/api/containers/stats', {
                    headers: { 'Authorization': 'Bearer ' + this._token() },
                });
                this.containerStats = res.ok ? await res.json() : [];
            } catch { this.containerStats = []; }
            this.containerStatsLoading = false;
        },

        async pullContainerImage(name) {
            if (!confirm(`Pull latest image for ${name}?`)) return;
            try {
                const res = await fetch(`/api/containers/${encodeURIComponent(name)}/pull`, {
                    method: 'POST',
                    headers: { 'Authorization': 'Bearer ' + this._token() },
                });
                const d = await res.json();
                this.addToast(d.success ? `Pulling image for ${name} (run ${d.run_id})` : 'Pull failed', d.success ? 'success' : 'error');
            } catch (e) {
                this.addToast('Pull failed: ' + e.message, 'error');
            }
        },


        // ── Kubernetes Browser ───────────────────────────────────────────────
        k8sNamespaces: [],
        k8sPods: [],
        k8sDeployments: [],
        k8sSelectedNs: '',
        k8sLoading: false,
        showK8sModal: false,
        k8sPodLogs: '',
        k8sPodLogsName: '',
        showK8sPodLogsModal: false,

        async fetchK8sNamespaces() {
            try {
                const res = await fetch('/api/k8s/namespaces', {
                    headers: { 'Authorization': 'Bearer ' + this._token() },
                });
                if (res.ok) this.k8sNamespaces = await res.json();
            } catch { /* silent */ }
        },

        async fetchK8sPods(namespace) {
            this.k8sLoading = true;
            const qs = namespace ? `?namespace=${namespace}` : '';
            try {
                const res = await fetch(`/api/k8s/pods${qs}`, {
                    headers: { 'Authorization': 'Bearer ' + this._token() },
                });
                if (res.ok) this.k8sPods = await res.json();
            } catch { /* silent */ }
            this.k8sLoading = false;
        },

        async fetchK8sDeployments(namespace) {
            const qs = namespace ? `?namespace=${namespace}` : '';
            try {
                const res = await fetch(`/api/k8s/deployments${qs}`, {
                    headers: { 'Authorization': 'Bearer ' + this._token() },
                });
                if (res.ok) this.k8sDeployments = await res.json();
            } catch { /* silent */ }
        },

        async fetchK8sPodLogs(namespace, name, container) {
            this.k8sPodLogsName = `${namespace}/${name}`;
            this.showK8sPodLogsModal = true;
            try {
                const qs = container ? `?container=${encodeURIComponent(container)}&lines=200` : '?lines=200';
                const res = await fetch(`/api/k8s/pods/${namespace}/${name}/logs${qs}`, {
                    headers: { 'Authorization': 'Bearer ' + this._token() },
                });
                this.k8sPodLogs = res.ok ? await res.text() : 'Failed to fetch logs.';
            } catch (e) { this.k8sPodLogs = 'Error: ' + e.message; }
        },

        async k8sScale(namespace, name, replicas) {
            const count = prompt(`Scale ${namespace}/${name} to how many replicas?`, replicas);
            if (count === null) return;
            try {
                const res = await fetch(`/api/k8s/deployments/${namespace}/${name}/scale`, {
                    method: 'POST',
                    headers: { 'Content-Type': 'application/json', 'Authorization': 'Bearer ' + this._token() },
                    body: JSON.stringify({ replicas: parseInt(count) }),
                });
                const d = await res.json();
                this.addToast(d.success ? `Scaled to ${d.replicas} replicas` : 'Scale failed', d.success ? 'success' : 'error');
                this.fetchK8sDeployments(namespace);
            } catch (e) {
                this.addToast('Scale failed: ' + e.message, 'error');
            }
        },

        openK8sBrowser() {
            this.showK8sModal = true;
            this.fetchK8sNamespaces();
            this.fetchK8sPods(this.k8sSelectedNs);
            this.fetchK8sDeployments(this.k8sSelectedNs);
        },


        // ── Proxmox Deep ─────────────────────────────────────────────────────
        pmxSnapshots: [],
        pmxSnapshotsLoading: false,
        showPmxSnapshotModal: false,
        pmxSelectedNode: '',
        pmxSelectedVmid: 0,
        pmxSelectedType: 'qemu',

        async fetchPmxSnapshots(node, vmid, vtype) {
            this.pmxSelectedNode = node;
            this.pmxSelectedVmid = vmid;
            this.pmxSelectedType = vtype || 'qemu';
            this.pmxSnapshotsLoading = true;
            this.showPmxSnapshotModal = true;
            try {
                const res = await fetch(`/api/proxmox/nodes/${node}/vms/${vmid}/snapshots?type=${vtype || 'qemu'}`, {
                    headers: { 'Authorization': 'Bearer ' + this._token() },
                });
                if (res.ok) this.pmxSnapshots = await res.json();
            } catch { this.pmxSnapshots = []; }
            this.pmxSnapshotsLoading = false;
        },

        async createPmxSnapshot(node, vmid, vtype) {
            const name = prompt('Snapshot name:');
            if (!name) return;
            const desc = prompt('Description (optional):', '');
            try {
                const res = await fetch(`/api/proxmox/nodes/${node}/vms/${vmid}/snapshot`, {
                    method: 'POST',
                    headers: { 'Content-Type': 'application/json', 'Authorization': 'Bearer ' + this._token() },
                    body: JSON.stringify({ name, description: desc || '', type: vtype || 'qemu' }),
                });
                const d = await res.json();
                this.addToast(d.success ? 'Snapshot created' : 'Snapshot failed', d.success ? 'success' : 'error');
                this.fetchPmxSnapshots(node, vmid, vtype);
            } catch (e) {
                this.addToast('Snapshot failed: ' + e.message, 'error');
            }
        },

        async openPmxConsole(node, vmid, vtype) {
            try {
                const res = await fetch(`/api/proxmox/nodes/${node}/vms/${vmid}/console?type=${vtype || 'qemu'}`, {
                    headers: { 'Authorization': 'Bearer ' + this._token() },
                });
                const d = await res.json();
                if (d.url) window.open(d.url, '_blank');
            } catch (e) {
                this.addToast('Console failed: ' + e.message, 'error');
            }
        },


        // ── Custom Monitoring Dashboard ──────────────────────────────────────
        multiMetrics: ['cpu_percent'],
        multiMetricData: {},
        multiMetricLoading: false,
        showMultiChartModal: false,
        availableMetrics: [],

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
            const canvas = document.getElementById('multi-chart-canvas');
            if (!canvas) return;
            if (this._multiChart) this._multiChart.destroy();
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
        _multiChart: null,


        // ── Alert Rule Builder ───────────────────────────────────────────────
        showAlertRuleModal: false,
        alertRulesList: [],
        editingRule: null,
        newRule: { condition: '', severity: 'warning', message: '', channels: [], cooldown: 300, group: '' },
        ruleTestResult: null,

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
            await fetch(`/api/alert-rules/${ruleId}`, {
                method: 'DELETE', headers: { 'Authorization': 'Bearer ' + this._token() },
            });
            this.fetchAlertRules();
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


        // ── Workflow Trace ───────────────────────────────────────────────────
        workflowTrace: null,
        workflowTraceLoading: false,
        showWorkflowTraceModal: false,

        async fetchWorkflowTrace(autoId) {
            this.workflowTraceLoading = true;
            this.showWorkflowTraceModal = true;
            try {
                const res = await fetch(`/api/automations/${autoId}/trace`, {
                    headers: { 'Authorization': 'Bearer ' + this._token() },
                });
                if (res.ok) this.workflowTrace = await res.json();
            } catch { this.workflowTrace = null; }
            this.workflowTraceLoading = false;
        },

        async validateWorkflow(steps) {
            try {
                const res = await fetch('/api/automations/validate-workflow', {
                    method: 'POST',
                    headers: { 'Content-Type': 'application/json', 'Authorization': 'Bearer ' + this._token() },
                    body: JSON.stringify({ steps }),
                });
                if (res.ok) {
                    const d = await res.json();
                    if (d.valid) this.addToast('Workflow valid — all steps found', 'success');
                    else this.addToast('Invalid — some steps not found', 'error');
                    return d;
                }
            } catch { /* silent */ }
            return null;
        },


        // ── User Profile ─────────────────────────────────────────────────────
        userProfile: null,
        showProfileModal: false,
        changePasswordCurrent: '',
        changePasswordNew: '',
        changePasswordConfirm: '',

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

        // ── Backup Scheduling ────────────────────────────────────────────────
        backupSchedules: [],
        backupHealth: null,
        backupProgress: null,
        showBackupScheduleModal: false,
        newBackupSchedule: { type: 'backup', schedule: '0 3 * * *', name: '' },

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

        // ── Container Stats ──────────────────────────────────────────────────
        showContainerStatsModal: false,

        openContainerStats() {
            this.showContainerStatsModal = true;
            this.fetchContainerStats();
        },


        // ── System Health Dashboard ──────────────────────────────────────────
        systemHealth: null,
        showHealthModal: false,

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

        // ── Network Analysis ─────────────────────────────────────────────────
        networkConnections: [],
        listeningPorts: [],
        networkInterfaces: [],
        showNetworkModal: false,

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

        // ── Process History ──────────────────────────────────────────────────
        processHistory: [],
        processList: [],
        showProcessModal: false,

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

        // ── Service Map ──────────────────────────────────────────────────────
        serviceMap: null,
        showServiceMapModal: false,

        async fetchServiceMap() {
            try {
                const res = await fetch('/api/services/map', {
                    headers: { 'Authorization': 'Bearer ' + this._token() },
                });
                if (res.ok) this.serviceMap = await res.json();
            } catch { /* silent */ }
        },


        // ── Uptime Dashboard ─────────────────────────────────────────────────
        uptimeItems: [],
        showUptimeModal: false,

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

        // ── Journal Viewer ───────────────────────────────────────────────────
        journalOutput: '',
        journalUnit: '',
        journalPriority: '',
        journalLines: 100,
        journalGrep: '',
        journalUnits: [],
        showJournalModal: false,

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
            this.showJournalModal = true;
            this.fetchJournalUnits();
            this.fetchJournal();
        },

        // ── Disk Prediction ──────────────────────────────────────────────────
        diskPredictions: [],

        async fetchDiskPredictions() {
            try {
                const res = await fetch('/api/disks/prediction', {
                    headers: { 'Authorization': 'Bearer ' + this._token() },
                });
                if (res.ok) this.diskPredictions = await res.json();
            } catch { /* silent */ }
        },

        // ── System Info ──────────────────────────────────────────────────────
        systemInfo: null,
        showSystemInfoModal: false,

        async fetchSystemInfo() {
            try {
                const res = await fetch('/api/system/info', {
                    headers: { 'Authorization': 'Bearer ' + this._token() },
                });
                if (res.ok) this.systemInfo = await res.json();
            } catch { /* silent */ }
        },
    };
}
