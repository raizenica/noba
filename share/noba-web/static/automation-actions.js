/**
 * Automation actions mixin for the NOBA dashboard component.
 *
 * Provides automation CRUD, job notification polling, templates,
 * stats, import/export, run execution, and workflow management.
 *
 * @returns {Object} Alpine component mixin (state + methods)
 */
function automationActionsMixin() {
    return {

        // ── Automation CRUD state ───────────────────────────────────────────
        showAutoModal: false,
        autoModalMode: 'create',
        autoForm: { id: '', name: '', type: 'script', config: {}, schedule: '', enabled: true },
        autoList: [],
        autoListLoading: false,
        autoFilter: 'all',
        autoSearch: '',
        autoTemplates: [],
        autoStats: {},

        // ── Run detail state ────────────────────────────────────────────────
        showRunDetailModal: false,
        runDetail: null,
        runDetailSteps: [],
        runDetailLoading: false,

        // ── Job notification poller state ────────────────────────────────────
        _lastSeenRunId: 0,

        // ── Workflow Trace state ────────────────────────────────────────────
        workflowTrace: null,
        workflowTraceLoading: false,
        showWorkflowTraceModal: false,


        // ── Automation CRUD ────────────────────────────────────────────────────

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


        // ── Job notification poller ────────────────────────────────────────────

        /** Start polling for background job completions. */
        async startJobNotifPoller() {
            // Initialize with current max run ID to avoid toasting old runs
            await this._initJobNotifBaseline();
            this._registerInterval('job_notif', () => this._checkJobCompletions(), 15000);
        },

        /** Stop the job notification poller. */
        stopJobNotifPoller() {
            this._clearInterval('job_notif');
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


        // ── Templates & Stats ──────────────────────────────────────────────────

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


        // ── Run Automation ─────────────────────────────────────────────────────

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

            this._registerInterval('auto_poll', async () => {
                if (!this.authenticated) { this._clearInterval('auto_poll'); this.runningScript = false; return; }
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
                        this._clearInterval('auto_poll');
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


        // ── Workflow ────────────────────────────────────────────────────────────

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
    };
}
