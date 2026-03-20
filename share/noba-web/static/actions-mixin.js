/**
 * Core actions mixin for the NOBA dashboard component.
 *
 * Provides log viewer, confirmation dialog, script execution with
 * live polling, run history, and shared formatters / chart export.
 *
 * Domain-specific actions are split into separate mixins:
 *   - integration-actions.js → service/VM/container/HA/K8s/Proxmox/agent controls
 *   - automation-actions.js  → automation CRUD, job polling, workflows
 *   - system-actions.js      → history, audit, SMART, backup, sessions, alerts, etc.
 *
 * All mixin objects are spread into the returned component, so `this`
 * resolves identically across all files.
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
            this._registerInterval('script_poll', async () => {
                if (!this.authenticated) { this._clearInterval('script_poll'); this.runningScript = false; return; }
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
                        this._clearInterval('script_poll');
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


        // ── Run History ────────────────────────────────────────────────────────

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


        // ── Shared formatters ──────────────────────────────────────────────────

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

        /** Format average duration in seconds to human-readable. */
        fmtDuration(secs) {
            if (!secs && secs !== 0) return '\u2014';
            if (secs < 60) return Math.round(secs) + 's';
            return Math.floor(secs / 60) + 'm ' + Math.round(secs % 60) + 's';
        },

        /** Format file size for display. */
        fmtFileSize(bytes) {
            if (bytes == null) return '\u2014';
            if (bytes < 1024) return bytes + ' B';
            if (bytes < 1024 * 1024) return (bytes / 1024).toFixed(1) + ' KB';
            if (bytes < 1024 * 1024 * 1024) return (bytes / (1024 * 1024)).toFixed(1) + ' MB';
            return (bytes / (1024 * 1024 * 1024)).toFixed(2) + ' GB';
        },


        // ── Chart Export ───────────────────────────────────────────────────────

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
    };
}
