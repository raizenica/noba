function dashboard() {
    // ── 1. Defaults & State ──
    const DEF_VIS = {
        core: true, netio: true, hw: true, battery: true, pihole: true,
        storage: true, radar: true, kuma: true, procs: true, containers: true,
        services: true, logs: true, actions: true, bookmarks: true, plex: true,
        truenas: true, downloads: true
    };

    const DEF_BOOKMARKS = 'Router|http://192.168.1.1|fa-network-wired, Pi-hole|http://pi.hole/admin|fa-shield-alt';
    const savedTheme = localStorage.getItem('noba-theme');
    const autoTheme  = savedTheme || (window.matchMedia('(prefers-color-scheme: light)').matches ? 'nord' : 'default');

    return {
        // UI & Vis
        theme: autoTheme,
        vis:   { ...DEF_VIS, ...JSON.parse(localStorage.getItem('noba-vis') || '{}') },
        collapsed: JSON.parse(localStorage.getItem('noba-collapsed') || '{}'),
        svcFilter: '',
        settingsTab: 'visibility',

        // Core Integrations
        piholeUrl:         localStorage.getItem('noba-pihole')    || '',
        piholeToken:       localStorage.getItem('noba-pihole-tok')|| '',
        bookmarksStr:      localStorage.getItem('noba-bookmarks') || DEF_BOOKMARKS,
        monitoredServices: localStorage.getItem('noba-services')  || 'sshd, docker, NetworkManager',
        radarIps:          localStorage.getItem('noba-radar')     || '192.168.1.1, 1.1.1.1, 8.8.8.8',
        plexUrl:           localStorage.getItem('noba-plex-url')  || '',
        plexToken:         localStorage.getItem('noba-plex-tok')  || '',
        kumaUrl:           localStorage.getItem('noba-kuma-url')  || '',
        bmcMap:            localStorage.getItem('noba-bmc-map')   || '',

        // TrueNAS & Download Integrations
        truenasUrl:        localStorage.getItem('noba-truenas-url') || '',
        truenasKey:        localStorage.getItem('noba-truenas-key') || '',
        radarrUrl:         localStorage.getItem('noba-radarr-url')  || '',
        radarrKey:         localStorage.getItem('noba-radarr-key')  || '',
        sonarrUrl:         localStorage.getItem('noba-sonarr-url')  || '',
        sonarrKey:         localStorage.getItem('noba-sonarr-key')  || '',
        qbitUrl:           localStorage.getItem('noba-qbit-url')    || '',
        qbitUser:          localStorage.getItem('noba-qbit-user')   || '',
        qbitPass:          localStorage.getItem('noba-qbit-pass')   || '',

        // Dynamic Features
        customActions:     [],

        // Job Settings
        backupSources: [], backupDest: '', cloudRemote: '', downloadsDir: '',
        cloudRemotes: [], selectedCloudRemote: '', cloudRemotesLoading: false,
        rcloneAvailable: null, rcloneVersion: '', cloudTestResults: {},

        // Live Data Objects
        timestamp:'--:--', uptime:'--', loadavg:'--', memory:'--', hostname:'--', defaultIp:'--',
        memPercent:0, cpuPercent:0, cpuHistory:[], cpuTemp:'N/A', gpuTemp:'N/A',
        osName:'--', kernel:'--', hwCpu:'--', hwGpu:'--', netRx:'0 B/s', netTx:'0 B/s',
        battery:{ percent:0, status:'Unknown', desktop:false },
        disks:[], services:[], zfs:{pools:[]}, radar:[], kuma:[],
        topCpu:[], topMem:[], pihole:null, plex:null, containers:[], alerts:[],
        truenas:null, radarr:null, sonarr:null, qbit:null,

        // App States
        selectedLog:'syserr', logContent:'Loading...', logLoading:false,
        showModal:false, showSettings:false,
        modalTitle:'', modalOutput:'', runningScript:false, refreshing:false,
        toasts:[], _es:null, _poll:null, _lastHeartbeat: 0,

        // Auth
        authenticated: !!localStorage.getItem('noba-token'),
        loginUsername: '', loginPassword: '', loginLoading: false, loginError: '',
        connStatus: 'offline', countdown: 5, _countdownTimer: null,
        _dismissedAlerts: new Set(),

        // Admin
        userRole: 'viewer', username: '', userList: [], usersLoading: false,
        showAddUserForm: false, newUsername: '', newPassword: '', newRole: 'viewer',
        showPassModal: false, passModalUser: '', passModalValue: '',
        showRemoveModal: false, removeModalUser: '',

        // ── 2. Computed Properties ──
        get cpuTempClass() { const t=parseInt(this.cpuTemp)||0; return t>80?'bd':t>65?'bw':'bn'; },
        get gpuTempClass() { const t=parseInt(this.gpuTemp)||0; return t>85?'bd':t>70?'bw':'bn'; },
        get visibleAlerts() { return (this.alerts||[]).filter(a => !this._dismissedAlerts.has(a.msg)); },
        get livePillText() {
            let state = '';
            if (this.refreshing) state = 'Syncing…';
            else if (this.connStatus === 'sse') state = 'Live';
            else if (this.connStatus === 'polling') state = this.countdown + 's';
            else state = 'Offline';
            return (this.timestamp && this.timestamp !== '--:--') ? `${state} • ${this.timestamp}` : state;
        },
        get parsedBookmarks() {
            return (this.bookmarksStr||'').split(',').filter(b=>b.trim()).map(b => {
                const p = b.split('|');
                return { name:(p[0]||'Link').trim(), url:(p[1]||'#').trim(), icon:(p[2]||'fa-link').trim() };
            });
        },
        get cpuLine() {
            const h = this.cpuHistory;
            if (h.length < 2) return '0,36 120,36';
            return h.map((v,i) => `${Math.round((i/(h.length-1))*120)},${Math.round(36-(v/100)*32)}`).join(' ');
        },
        get cpuFill() {
            const h = this.cpuHistory;
            if (h.length < 2) return '0,38 120,38 120,38 0,38';
            const pts = h.map((v,i) => `${Math.round((i/(h.length-1))*120)},${Math.round(36-(v/100)*32)}`).join(' ');
            return `${pts} 120,38 0,38`;
        },
        get filteredServices() {
            if (!this.svcFilter) return this.services || [];
            const q = this.svcFilter.toLowerCase();
            return (this.services || []).filter(s => s.name.toLowerCase().includes(q));
        },

        // ── 3. Lifecycle ──
        async init() {
            try { this.initSortable(); } catch (e) { console.warn("Sortable init skipped", e); }
            try { this.initKeyboard(); } catch (e) { console.warn("Keyboard init skipped", e); }
            try { this.initMasonry(); } catch (e) { console.warn("Masonry init skipped", e); }

            if (this.authenticated) {
                await this.fetchUserInfo();
                await this.fetchSettings();
                await this.fetchCloudRemotes();
                await this.fetchLog();
                if (this.userRole === 'admin') await this.fetchUsers();

                this.connectSSE();

                setInterval(() => { if (this.vis.logs && this.showSettings === false) this.fetchLog(); }, 12000);
                setInterval(() => { this.fetchCloudRemotes(); }, 300000);
                setInterval(() => {
                    if (this.connStatus === 'sse' && this._lastHeartbeat) {
                        if (Date.now() - this._lastHeartbeat > 15000) this.connectSSE();
                    }
                }, 5000);
            }
        },

        // ── 4. Layout & UI Logic ──
        initMasonry() {
            const observer = new ResizeObserver(entries => {
                for (let entry of entries) {
                    const card = entry.target;
                    if (card.style.display === 'none') continue;
                    const height = card.getBoundingClientRect().height;
                    const rowSpan = Math.ceil((height + 18) / 10);
                    card.style.gridRowEnd = `span ${rowSpan}`;
                }
            });
            this.$nextTick(() => {
                const cards = document.querySelectorAll('.card');
                if (cards.length) cards.forEach(c => observer.observe(c));
            });
        },

        initSortable() {
            if (typeof Sortable === 'undefined') return;
            const grid = document.getElementById('sortable-grid');
            if (!grid) return;

            Sortable.create(grid, {
                animation: 200, handle: '.card-hdr', ghostClass: 'sortable-ghost',
                dragClass: 'sortable-drag', forceFallback: true, fallbackOnBody: true,
                group: 'noba-v9',
                store: {
                    get: s => (localStorage.getItem(s.options.group.name)||'').split('|'),
                            set: s => localStorage.setItem(s.options.group.name, s.toArray().join('|'))
                }
            });
        },

        initKeyboard() {
            document.addEventListener('keydown', (e) => {
                if (e.target.tagName === 'INPUT' || e.target.tagName === 'TEXTAREA') return;
                if (e.key === 's' && !this.showSettings && !this.showModal) this.showSettings = true;
                else if (e.key === 'r' && !this.showSettings && !this.showModal && this.authenticated) this.refreshStats();
                else if (e.key === 'Escape') {
                    this.showSettings = false; this.showModal = false;
                    this.showPassModal = false; this.showRemoveModal = false;
                }
            });
        },

        toggleCollapse(card) {
            this.collapsed[card] = !this.collapsed[card];
            localStorage.setItem('noba-collapsed', JSON.stringify(this.collapsed));
        },

        copyVal(val, e) {
            if (!val || val === '--') return;
            navigator.clipboard.writeText(val).catch(() => {});
            if (e && e.target) {
                const el = e.target;
                el.classList.add('copied');
                setTimeout(() => el.classList.remove('copied'), 1000);
            }
        },

        dismissAlert(msg) {
            this._dismissedAlerts.add(msg);
            this._dismissedAlerts = new Set(this._dismissedAlerts);
        },

        addToast(msg, type='info') {
            const id = Date.now() + Math.random();
            this.toasts.push({id, msg, type});
            setTimeout(() => { this.toasts = this.toasts.filter(t => t.id !== id); }, 3500);
        },

        humanBps(bps) {
            if (!bps || bps <= 0) return '0 B/s';
            const units = ['B/s', 'KB/s', 'MB/s', 'GB/s', 'TB/s'];
            let v = bps, i = 0;
            while (v >= 1024 && i < units.length - 1) { v /= 1024; i++; }
            return v.toFixed(1) + ' ' + units[i];
        },

        humanBytes(bytes) {
            if (!bytes || bytes <= 0) return '—';
            const units = ['B', 'KB', 'MB', 'GB', 'TB', 'PB'];
            let v = bytes, i = 0;
            while (v >= 1024 && i < units.length - 1) { v /= 1024; i++; }
            return v.toFixed(1) + ' ' + units[i];
        },

        // ── 5. Server Communication ──
        _startCountdown(interval=5) {
            clearInterval(this._countdownTimer);
            this.countdown = interval;
            this._countdownTimer = setInterval(() => {
                this.countdown = Math.max(0, this.countdown - 1);
                if (this.countdown === 0) this.countdown = interval;
            }, 1000);
        },

        _stopCountdown() {
            clearInterval(this._countdownTimer);
            this._countdownTimer = null;
        },

        _buildQueryParams() {
            const params = new URLSearchParams({
                services: this.monitoredServices,
                radar:    this.radarIps,
                pihole:   this.piholeUrl,
                plexUrl:  this.plexUrl,
                kumaUrl:  this.kumaUrl,
                bmcMap:   this.bmcMap,
            });
            const token = localStorage.getItem('noba-token');
            if (token) params.append('token', token);
            return params.toString();
        },

        connectSSE() {
            if (!this.authenticated) return;
            if (this._es) { this._es.close(); this._es = null; }
            if (this._poll) { clearInterval(this._poll); this._poll = null; }

            this._stopCountdown();
            this._lastHeartbeat = Date.now();
            this._es = new EventSource(`/api/stream?${this._buildQueryParams()}`);

            this._es.onopen = () => {
                this.connStatus = 'sse';
                this._stopCountdown();
                this._lastHeartbeat = Date.now();
            };

            this._es.onmessage = (e) => {
                try {
                    Object.assign(this, JSON.parse(e.data));
                    this._lastHeartbeat = Date.now();
                } catch {}
            };

            this._es.onerror = () => {
                this._es.close(); this._es = null;
                this.connStatus = 'polling';
                this._startCountdown(5);
                setTimeout(() => {
                    this.refreshStats();
                    this._poll = setInterval(() => { this.refreshStats(); this._startCountdown(5); }, 5000);
                }, 3000);
            };
        },

        async refreshStats() {
            if (!this.authenticated || this.refreshing) return;
            this.refreshing = true;
            try {
                const res = await fetch(`/api/stats?${this._buildQueryParams()}`, {
                    headers: { 'Authorization': 'Bearer ' + localStorage.getItem('noba-token') }
                });
                if (res.ok) {
                    Object.assign(this, await res.json());
                    if (this.connStatus === 'offline') this.connStatus = 'polling';
                } else if (res.status === 401) {
                    this.authenticated = false; this.connStatus = 'offline';
                } else {
                    this.connStatus = 'offline';
                }
            } catch {
                this.connStatus = 'offline';
            } finally {
                this.refreshing = false;
            }
        },

        async fetchSettings() {
            const token = localStorage.getItem('noba-token');
            try {
                const res = await fetch('/api/settings', { headers: { 'Authorization': 'Bearer ' + token } });
                if (res.ok) {
                    const s = await res.json();
                    if (s.piholeUrl != null) this.piholeUrl = s.piholeUrl;
                    if (s.piholeToken != null) this.piholeToken = s.piholeToken;
                    if (s.monitoredServices != null) this.monitoredServices = s.monitoredServices;
                    if (s.radarIps != null) this.radarIps = s.radarIps;
                    if (s.bookmarksStr != null) this.bookmarksStr = s.bookmarksStr;
                    if (s.plexUrl != null) this.plexUrl = s.plexUrl;
                    if (s.plexToken != null) this.plexToken = s.plexToken;
                    if (s.kumaUrl != null) this.kumaUrl = s.kumaUrl;
                    if (s.bmcMap != null) this.bmcMap = s.bmcMap;

                    if (s.truenasUrl != null) this.truenasUrl = s.truenasUrl;
                    if (s.truenasKey != null) this.truenasKey = s.truenasKey;
                    if (s.radarrUrl != null) this.radarrUrl = s.radarrUrl;
                    if (s.radarrKey != null) this.radarrKey = s.radarrKey;
                    if (s.sonarrUrl != null) this.sonarrUrl = s.sonarrUrl;
                    if (s.sonarrKey != null) this.sonarrKey = s.sonarrKey;
                    if (s.qbitUrl != null) this.qbitUrl = s.qbitUrl;
                    if (s.qbitUser != null) this.qbitUser = s.qbitUser;
                    if (s.qbitPass != null) this.qbitPass = s.qbitPass;

                    if (s.backupSources != null) this.backupSources = s.backupSources;
                    if (s.backupDest != null) this.backupDest = s.backupDest;
                    if (s.cloudRemote != null) this.cloudRemote = s.cloudRemote;
                    if (s.downloadsDir != null) this.downloadsDir = s.downloadsDir;

                    if (s.customActions != null) this.customActions = s.customActions;

                    this.saveSettings();
                }
            } catch (e) {}
        },

        async fetchCloudRemotes() {
            if (!this.authenticated) return;
            this.cloudRemotesLoading = true;
            try {
                const res = await fetch('/api/cloud-remotes', { headers: { 'Authorization': 'Bearer ' + localStorage.getItem('noba-token') } });
                if (res.ok) {
                    const d = await res.json();
                    this.rcloneAvailable = d.available ?? true;
                    this.rcloneVersion   = d.version  ?? '';
                    this.cloudRemotes    = d.remotes  ?? (Array.isArray(d) ? d : []);
                    if (this.cloudRemotes.length > 0 && !this.selectedCloudRemote) {
                        const match = this.cloudRemotes.find(r => r.name === this.cloudRemote);
                        this.selectedCloudRemote = match ? match.name : this.cloudRemotes[0].name;
                    }
                }
            } catch (e) {} finally { this.cloudRemotesLoading = false; }
        },

        async saveSettings() {
            localStorage.setItem('noba-theme', this.theme);
            localStorage.setItem('noba-pihole', this.piholeUrl);
            localStorage.setItem('noba-pihole-tok', this.piholeToken);
            localStorage.setItem('noba-bookmarks', this.bookmarksStr);
            localStorage.setItem('noba-services', this.monitoredServices);
            localStorage.setItem('noba-radar', this.radarIps);
            localStorage.setItem('noba-plex-url', this.plexUrl);
            localStorage.setItem('noba-plex-tok', this.plexToken);
            localStorage.setItem('noba-kuma-url', this.kumaUrl);
            localStorage.setItem('noba-bmc-map', this.bmcMap);
            localStorage.setItem('noba-truenas-url', this.truenasUrl);
            localStorage.setItem('noba-truenas-key', this.truenasKey);
            localStorage.setItem('noba-radarr-url', this.radarrUrl);
            localStorage.setItem('noba-radarr-key', this.radarrKey);
            localStorage.setItem('noba-sonarr-url', this.sonarrUrl);
            localStorage.setItem('noba-sonarr-key', this.sonarrKey);
            localStorage.setItem('noba-qbit-url', this.qbitUrl);
            localStorage.setItem('noba-qbit-user', this.qbitUser);
            localStorage.setItem('noba-qbit-pass', this.qbitPass);
            localStorage.setItem('noba-vis', JSON.stringify(this.vis));
            localStorage.setItem('noba-collapsed', JSON.stringify(this.collapsed));

            if (this.authenticated) {
                try {
                    await fetch('/api/settings', {
                        method: 'POST',
                        headers: { 'Content-Type': 'application/json', 'Authorization': 'Bearer ' + localStorage.getItem('noba-token') },
                                body: JSON.stringify({
                                    piholeUrl: this.piholeUrl, piholeToken: this.piholeToken,
                                    monitoredServices: this.monitoredServices, radarIps: this.radarIps,
                                    bookmarksStr: this.bookmarksStr, plexUrl: this.plexUrl,
                                    plexToken: this.plexToken, kumaUrl: this.kumaUrl, bmcMap: this.bmcMap,
                                    truenasUrl: this.truenasUrl, truenasKey: this.truenasKey,
                                    radarrUrl: this.radarrUrl, radarrKey: this.radarrKey,
                                    sonarrUrl: this.sonarrUrl, sonarrKey: this.sonarrKey,
                                    qbitUrl: this.qbitUrl, qbitUser: this.qbitUser, qbitPass: this.qbitPass
                                })
                    });
                } catch (e) {}
            }
        },

        applySettings() {
            this.saveSettings();
            this.showSettings = false;
            if (this.authenticated) this.connectSSE();
            this.addToast('Settings saved', 'success');
        },

        // ── 6. Actions & Controls ──
        async fetchLog() {
            if (!this.authenticated) return;
            this.logLoading = true;
            try {
                const res = await fetch('/api/log-viewer?type=' + this.selectedLog, { headers: { 'Authorization': 'Bearer ' + localStorage.getItem('noba-token') } });
                if (res.ok) {
                    this.logContent = await res.text();
                    this.$nextTick(() => { const el = document.querySelector('.log-pre'); if (el) el.scrollTop = el.scrollHeight; });
                } else if (res.status === 401) this.authenticated = false;
            } catch { this.logContent = 'Failed to fetch log.'; } finally { this.logLoading = false; }
        },

        async svcAction(svc, action) {
            if (!this.authenticated) return;
            try {
                const res = await fetch('/api/service-control', {
                    method: 'POST',
                    headers: { 'Content-Type': 'application/json', 'Authorization': 'Bearer ' + localStorage.getItem('noba-token') },
                                        body: JSON.stringify({ service: svc.name, action, is_user: svc.is_user })
                });
                const d = await res.json();
                this.addToast(d.success ? `${action}: ${svc.name.replace('.service','')}` : `Failed: ${svc.name}`, d.success ? 'success' : 'error');
                setTimeout(() => this.refreshStats(), 1200);
            } catch { this.addToast('Service control error', 'error'); }
        },

        async runScript(script, argStr = '') {
            if (!this.authenticated || this.runningScript) return;
            this.runningScript = true;
            this.modalTitle  = `Running: ${script}`;
            this.modalOutput = `>> [${new Date().toLocaleTimeString()}] Starting action...\n`;
            this.showModal   = true;

            const token = localStorage.getItem('noba-token');
            const poll = setInterval(async () => {
                try {
                    const r = await fetch('/api/action-log', { headers: { 'Authorization': 'Bearer ' + token } });
                    if (r.ok) { this.modalOutput = await r.text(); const el = document.getElementById('console-out'); if (el) el.scrollTop = el.scrollHeight; }
                } catch {}
            }, 800);

            try {
                const res = await fetch('/api/run', {
                    method: 'POST',
                    headers: { 'Content-Type': 'application/json', 'Authorization': 'Bearer ' + token },
                    body: JSON.stringify({ script, args: argStr })
                });
                const result = await res.json();
                this.modalTitle = result.success ? '✓ Completed' : '✗ Failed';
            } catch { this.modalTitle = '✗ Connection Error'; } finally {
                clearInterval(poll);
                try {
                    const r = await fetch('/api/action-log', { headers: { 'Authorization': 'Bearer ' + token } });
                    if (r.ok) { this.modalOutput = await r.text(); const el = document.getElementById('console-out'); if (el) el.scrollTop = el.scrollHeight; }
                } catch {}
                this.runningScript = false; await this.refreshStats();
            }
        },

        // ── 7. Auth & Users ──
        async fetchUserInfo() {
            const token = localStorage.getItem('noba-token');
            try {
                const res = await fetch('/api/me', { headers: { 'Authorization': 'Bearer ' + token } });
                if (res.ok) {
                    const data = await res.json();
                    this.username = data.username;
                    this.userRole = data.role;
                }
            } catch (e) {}
        },

        async doLogin() {
            this.loginLoading = true; this.loginError = '';
            try {
                const res = await fetch('/api/login', {
                    method: 'POST', headers: { 'Content-Type': 'application/json' },
                    body: JSON.stringify({ username: this.loginUsername, password: this.loginPassword })
                });
                const data = await res.json();
                if (res.ok && data.token) {
                    localStorage.setItem('noba-token', data.token);
                    this.authenticated = true;
                    await this.fetchUserInfo();
                    await this.fetchSettings();
                    await this.fetchCloudRemotes();
                    if (this.userRole === 'admin') await this.fetchUsers();
                    this.connectSSE();
                    await this.fetchLog();
                } else { this.loginError = data.error || 'Login failed'; }
            } catch { this.loginError = 'Network error'; } finally { this.loginLoading = false; }
        },

        async logout() {
            const token = localStorage.getItem('noba-token');
            if (token) { try { await fetch('/api/logout?token=' + encodeURIComponent(token), { method: 'POST' }); } catch {} }
            localStorage.removeItem('noba-token');
            this.authenticated = false; this.connStatus = 'offline';
            this._stopCountdown();
            if (this._es) { this._es.close(); this._es = null; }
            if (this._poll) { clearInterval(this._poll); this._poll = null; }
        },

        async fetchUsers() {
            this.usersLoading = true;
            try {
                const res = await fetch('/api/admin/users', {
                    method: 'POST', headers: { 'Content-Type': 'application/json', 'Authorization': 'Bearer ' + localStorage.getItem('noba-token') },
                                        body: JSON.stringify({ action: 'list' })
                });
                if (res.ok) this.userList = await res.json(); else this.addToast('Failed to fetch users', 'error');
            } catch (e) { this.addToast('Error fetching users', 'error'); } finally { this.usersLoading = false; }
        },

        async addUser() {
            if (!this.newUsername || !this.newPassword) { this.addToast('Username and password required', 'error'); return; }
            try {
                const res = await fetch('/api/admin/users', {
                    method: 'POST', headers: { 'Content-Type': 'application/json', 'Authorization': 'Bearer ' + localStorage.getItem('noba-token') },
                                        body: JSON.stringify({ action: 'add', username: this.newUsername, password: this.newPassword, role: this.newRole })
                });
                if (res.ok) {
                    this.addToast(`User ${this.newUsername} added`, 'success');
                    this.newUsername = ''; this.newPassword = ''; this.newRole = 'viewer';
                    this.showAddUserForm = false; await this.fetchUsers();
                } else { const err = await res.json(); this.addToast(err.error || 'Failed to add user', 'error'); }
            } catch (e) { this.addToast('Error adding user', 'error'); }
        },

        openPassModal(username) {
            this.passModalUser = username; this.passModalValue = ''; this.showPassModal = true;
            this.$nextTick(() => { if (this.$refs.passInput) this.$refs.passInput.focus(); });
        },

        async confirmChangePassword() {
            if (!this.passModalValue) return;
            const username = this.passModalUser;
            try {
                const res = await fetch('/api/admin/users', {
                    method: 'POST', headers: { 'Content-Type': 'application/json', 'Authorization': 'Bearer ' + localStorage.getItem('noba-token') },
                                        body: JSON.stringify({ action: 'change_password', username, password: this.passModalValue })
                });
                if (res.ok) this.addToast(`Password changed for ${username}`, 'success');
                else { const err = await res.json(); this.addToast(err.error || 'Failed to change password', 'error'); }
            } catch (e) { this.addToast('Error changing password', 'error'); } finally {
                this.showPassModal = false; this.passModalValue = '';
            }
        },

        confirmRemoveUser(username) {
            this.removeModalUser = username; this.showRemoveModal = true;
        },

        async confirmRemove() {
            const username = this.removeModalUser; this.showRemoveModal = false;
            try {
                const res = await fetch('/api/admin/users', {
                    method: 'POST', headers: { 'Content-Type': 'application/json', 'Authorization': 'Bearer ' + localStorage.getItem('noba-token') },
                                        body: JSON.stringify({ action: 'remove', username })
                });
                if (res.ok) { this.addToast(`User ${username} removed`, 'success'); await this.fetchUsers(); }
                else { const err = await res.json(); this.addToast(err.error || 'Failed to remove user', 'error'); }
            } catch (e) { this.addToast('Error removing user', 'error'); }
        }
    };
}
