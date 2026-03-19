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

        // ── History & Audit state ──────────────────────────────────────────────
        showHistoryModal: false,
        historyMetric: '',
        historyData: [],
        historyRange: 24,
        historyResolution: 60,
        historyChart: null,
        showAuditModal: false,
        auditLog: [],
        historyAnomalyEnabled: false,

        // ── SMART disk health ──────────────────────────────────────────────────
        smartData: [], smartLoading: false, showSmartModal: false,


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
            this.modalTitle    = `Running: ${script}`;
            this.modalOutput   = `>> [${new Date().toLocaleTimeString()}] Starting action...\n`;
            this.showModal     = true;

            const token = this._token();

            const poll = setInterval(async () => {
                try {
                    const r = await fetch('/api/action-log', { headers: { 'Authorization': 'Bearer ' + token } });
                    if (r.ok) {
                        this.modalOutput = await r.text();
                        const el = document.getElementById('console-out');
                        if (el) el.scrollTop = el.scrollHeight;
                    }
                } catch { /* non-fatal */ }
            }, 800);

            try {
                const res = await fetch('/api/run', {
                    method: 'POST',
                    headers: { 'Content-Type': 'application/json', 'Authorization': 'Bearer ' + token },
                    body: JSON.stringify({ script, args: argStr }),
                });
                const result = await res.json();
                this.modalTitle = result.success ? '\u2713 Completed' : '\u2717 Failed';
                this.addToast(`${script} ${result.success ? 'completed' : 'failed'}`,
                              result.success ? 'success' : 'error');
            } catch {
                this.modalTitle = '\u2717 Connection Error';
                this.addToast('Connection error', 'error');
            } finally {
                clearInterval(poll);
                try {
                    const r = await fetch('/api/action-log', { headers: { 'Authorization': 'Bearer ' + token } });
                    if (r.ok) {
                        this.modalOutput = await r.text();
                        const el = document.getElementById('console-out');
                        if (el) el.scrollTop = el.scrollHeight;
                    }
                } catch { /* non-fatal */ }
                this.runningScript = false;
                await this.refreshStats();
            }
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

        /** Render or re-render the Chart.js history chart. */
        renderHistoryChart() {
            const canvas = document.getElementById('historyChart');
            if (!canvas) return;

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
                        }
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

        /** Fetch the audit log (admin only). */
        async fetchAuditLog() {
            try {
                const res = await fetch('/api/audit?limit=100', {
                    headers: { 'Authorization': 'Bearer ' + this._token() }
                });
                if (!res.ok) throw new Error(`HTTP ${res.status}`);
                this.auditLog = await res.json();
            } catch (e) {
                this.addToast('Failed to load audit log: ' + e.message, 'error');
            }
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
                const a = document.createElement('a');
                a.href = URL.createObjectURL(blob);
                a.download = `noba-${this.historyMetric}-${this.historyRange}h.csv`;
                document.body.appendChild(a);
                a.click();
                document.body.removeChild(a);
                URL.revokeObjectURL(a.href);
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
                const a = document.createElement('a');
                a.href = URL.createObjectURL(blob);
                a.download = 'noba-config-backup.yaml';
                document.body.appendChild(a);
                a.click();
                document.body.removeChild(a);
                URL.revokeObjectURL(a.href);
            } catch (e) {
                this.addToast('Config backup failed: ' + e.message, 'error');
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
            if (!hours) return '\u2014';
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
    };
}
