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
    };
}
