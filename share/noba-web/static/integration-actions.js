/**
 * Integration actions mixin for the NOBA dashboard component.
 *
 * Provides service/VM/container controls, webhooks, Home Assistant,
 * Docker deep management, Kubernetes, Proxmox, Docker Compose,
 * Wake-on-LAN, DNS toggle, CPU governor, alert history, SLA,
 * and agent commands.
 *
 * @returns {Object} Alpine component mixin (state + methods)
 */
function integrationActionsMixin() {
    return {

        // ── Docker Compose state ────────────────────────────────────────────
        composeProjectList: [],
        composeLoading: false,

        // ── Alert History state ─────────────────────────────────────────────
        alertHistory: [],
        alertHistoryLoading: false,
        showAlertHistoryModal: false,

        // ── Home Assistant Deep Integration state ───────────────────────────
        hassEntities: [],
        hassEntitiesLoading: false,
        hassEntityFilter: '',
        hassDomainFilter: '',
        showHassModal: false,

        // ── Docker Deep Management state ────────────────────────────────────
        containerLogs: '',
        containerLogsName: '',
        containerLogsLoading: false,
        showContainerLogsModal: false,
        containerInspect: null,
        showContainerInspectModal: false,
        containerStats: [],
        containerStatsLoading: false,

        // ── Kubernetes Browser state ────────────────────────────────────────
        k8sNamespaces: [],
        k8sPods: [],
        k8sDeployments: [],
        k8sSelectedNs: '',
        k8sLoading: false,
        showK8sModal: false,
        k8sPodLogs: '',
        k8sPodLogsName: '',
        showK8sPodLogsModal: false,

        // ── Proxmox Deep state ──────────────────────────────────────────────
        pmxSnapshots: [],
        pmxSnapshotsLoading: false,
        showPmxSnapshotModal: false,
        pmxSelectedNode: '',
        pmxSelectedVmid: 0,
        pmxSelectedType: 'qemu',


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


        // ── Home Assistant Control ─────────────────────────────────────────────

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


        // ── Home Assistant Deep Integration ─────────────────────────────────────

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


        // ── Docker Deep Management ──────────────────────────────────────────────

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


        // ── Kubernetes Browser ──────────────────────────────────────────────────

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


        // ── Proxmox Deep ───────────────────────────────────────────────────────

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


        // ── Docker Compose ─────────────────────────────────────────────────────

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


        // ── Wake-on-LAN ────────────────────────────────────────────────────────

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


        // ── Pi-hole / AdGuard DNS Toggle ────────────────────────────────────────

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


        // ── CPU Governor ────────────────────────────────────────────────────────

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


        // ── Alert History ───────────────────────────────────────────────────────

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


        // ── Agent Commands ──────────────────────────────────────────────────────

        async sendAgentCmd(hostname, type, params = {}) {
            try {
                const res = await fetch(`/api/agents/${encodeURIComponent(hostname)}/command`, {
                    method: 'POST',
                    headers: { 'Authorization': 'Bearer ' + this._token(), 'Content-Type': 'application/json' },
                    body: JSON.stringify({ type, params }),
                });
                if (res.ok) {
                    const d = await res.json();
                    this.addToast(`Command queued for ${hostname} (${type})`, 'success');
                    // Poll for results after a delay
                    setTimeout(() => this.pollAgentResult(hostname), 5000);
                    setTimeout(() => this.pollAgentResult(hostname), 15000);
                    setTimeout(() => this.pollAgentResult(hostname), 35000);
                } else {
                    this.addToast('Failed to queue command', 'error');
                }
            } catch (e) { this.addToast('Command error: ' + e.message, 'error'); }
        },

        async sendAgentExec() {
            if (!this.agentCmdTarget || !this.agentCmdInput.trim()) return;
            this.agentCmdSending = true;
            const targets = this.agentCmdTarget === '__all__'
                ? (this.agents || []).filter(a => a.online).map(a => a.hostname)
                : [this.agentCmdTarget];
            for (const host of targets) {
                await this.sendAgentCmd(host, 'exec', { command: this.agentCmdInput });
            }
            this.agentCmdSending = false;
        },

        async pollAgentResult(hostname) {
            try {
                const res = await fetch(`/api/agents/${encodeURIComponent(hostname)}/results`, {
                    headers: { 'Authorization': 'Bearer ' + this._token() },
                });
                if (res.ok) {
                    const results = await res.json();
                    if (results.length > 0) {
                        const last = results[results.length - 1];
                        let output = '';
                        if (last.stdout) output = last.stdout;
                        else if (last.pong) output = `pong v${last.version || '?'}`;
                        else if (last.message) output = last.message;
                        else if (last.error) output = `Error: ${last.error}`;
                        else output = JSON.stringify(last);
                        this.agentCmdOutput = { ...this.agentCmdOutput, [hostname]: output.trim() };
                    }
                }
            } catch { /* silent */ }
        },

        async deployAgent(host, user, pass_, port) {
            if (!confirm(`Deploy agent to ${user}@${host}?`)) return;
            this.deploying = true;
            this.deployResult = '';
            try {
                const res = await fetch('/api/agents/deploy', {
                    method: 'POST',
                    headers: { 'Authorization': 'Bearer ' + this._token(), 'Content-Type': 'application/json' },
                    body: JSON.stringify({ host, ssh_user: user, ssh_pass: pass_, ssh_port: port }),
                });
                const d = await res.json();
                this.deployResult = d.status === 'ok'
                    ? `Success! Agent deployed to ${host}`
                    : `Error: ${d.error || d.output || 'Deploy failed'}`;
                if (d.status === 'ok') this.addToast(`Agent deployed to ${host}`, 'success');
            } catch (e) { this.deployResult = 'error: ' + e.message; }
            finally { this.deploying = false; }
        },

        async generateInstallCmd() {
            const cfg = await fetch('/api/settings', {
                headers: { 'Authorization': 'Bearer ' + this._token() },
            }).then(r => r.json()).catch(() => ({}));
            const key = (cfg.agentKeys || '').split(',')[0]?.trim() || 'YOUR_KEY';
            const server = window.location.origin;
            this.installCmd = `curl -sf "${server}/api/agent/install-script?key=${key}" | sudo bash`;
        },

        async generateWinCmd() {
            const cfg = await fetch('/api/settings', {
                headers: { 'Authorization': 'Bearer ' + this._token() },
            }).then(r => r.json()).catch(() => ({}));
            const key = (cfg.agentKeys || '').split(',')[0]?.trim() || 'YOUR_KEY';
            const server = window.location.origin;
            this.installCmd = `irm "${server}/api/agent/update" -Headers @{"X-Agent-Key"="${key}"} -OutFile agent.py; python agent.py --server ${server} --key ${key} --once`;
        },

        /** Fetch SLA uptime data. */
        async fetchSla(hours) {
            this.slaLoading = true;
            try {
                const res = await fetch(`/api/sla/summary?hours=${hours || this.slaPeriod}`, {
                    headers: { 'Authorization': 'Bearer ' + this._token() },
                });
                if (res.ok) this.slaData = await res.json();
            } catch { /* silent */ }
            finally { this.slaLoading = false; }
        },

        async fetchAgentHistory(hostname, metric, hours) {
            try {
                const res = await fetch(`/api/agents/${encodeURIComponent(hostname)}/history?metric=${metric || 'cpu'}&hours=${hours || 24}`, {
                    headers: { 'Authorization': 'Bearer ' + this._token() },
                });
                if (res.ok) {
                    this.agentHistoryData = await res.json();
                    this.agentHistoryHost = hostname;
                    this.agentHistoryMetric = metric || 'cpu';
                    this.$nextTick(() => this.renderAgentHistoryChart());
                }
            } catch { /* silent */ }
        },

        renderAgentHistoryChart() {
            const canvas = document.getElementById('agent-history-chart');
            if (!canvas || !this.agentHistoryData.length) return;
            if (this._agentHistChart instanceof Chart) this._agentHistChart.destroy();
            const labels = this.agentHistoryData.map(d => new Date(d.time * 1000).toLocaleTimeString());
            const values = this.agentHistoryData.map(d => d.value);
            const colors = { cpu: '#00c8ff', mem: '#00e676', disk: '#ffb300' };
            this._agentHistChart = new Chart(canvas.getContext('2d'), {
                type: 'line',
                data: { labels, datasets: [{ label: `${this.agentHistoryHost} ${this.agentHistoryMetric}%`, data: values, borderColor: colors[this.agentHistoryMetric] || '#00c8ff', borderWidth: 1.5, pointRadius: 0, fill: true, backgroundColor: (colors[this.agentHistoryMetric] || '#00c8ff') + '15' }] },
                options: { responsive: true, animation: { duration: 0 }, scales: { y: { min: 0, max: 100 } }, plugins: { legend: { labels: { color: '#c8dff0' } } } },
            });
        },
    };
}
