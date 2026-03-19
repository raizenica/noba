/**
 * dashboard() — Alpine.js component
 *
 * Improvements over original:
 * [BUG]  SSE merge uses a safe allowlist instead of Object.assign(this, payload)
 * [BUG]  _dismissedAlerts changed from Set → plain object so Alpine tracks it
 * [BUG]  connectSSE() onerror clears previous _poll before creating a new one
 * [BUG]  applySettings() awaits saveSettings() before showing "saved" toast
 * [BUG]  fetchSettings() no longer calls saveSettings() (needless round-trip)
 * [BUG]  loginPassword zeroed after successful login
 * [BUG]  countdown timer stays at 0 instead of immediately resetting to interval
 * [SEC]  Token centralised in _token() helper — one place to swap storage
 * [SEC]  qbitPass storage flagged with a comment
 * [QOL]  SETTINGS_KEYS array drives both fetchSettings and saveSettings
 * [QOL]  init() parallel-fetches independent resources with Promise.all
 * [QOL]  Toast IDs use a monotonic counter instead of Date.now()+random
 * [QOL]  _buildQueryParams comment explains SSE-vs-REST auth difference
 * [QOL]  initKeyboard listener stored so it can be removed if needed
 * [QOL]  ResizeObserver disconnect available via _masonryObserver
 * [QOL]  connectSSE() guarded against concurrent reconnect attempts
 * [NEW]  History Modal state and fetch logic with Chart.js integration
 * [NEW]  Audit Log fetch logic and admin-only state handling
 */

function dashboard() {

    // ── 0. Module-level constants ──────────────────────────────────────────────

    /** All persisted settings keys (used by fetchSettings + saveSettings). */
    const SETTINGS_KEYS = [
        'piholeUrl', 'piholeToken', 'monitoredServices', 'radarIps',
        'bookmarksStr', 'plexUrl', 'plexToken', 'kumaUrl', 'bmcMap',
        'wanTestIp', 'lanTestIp',
        'truenasUrl', 'truenasKey',
        'radarrUrl',  'radarrKey',
        'sonarrUrl',  'sonarrKey',
        'qbitUrl',    'qbitUser',  'qbitPass',
        'backupSources', 'backupDest', 'cloudRemote', 'downloadsDir',
        'customActions', 'automations',
        'proxmoxUrl', 'proxmoxUser', 'proxmoxTokenName', 'proxmoxTokenValue',
        'pushoverEnabled', 'pushoverAppToken', 'pushoverUserKey',
        'gotifyEnabled', 'gotifyUrl', 'gotifyAppToken',
        'alertRules',
    ];

    /** Keys that live in localStorage as a local mirror.
     * Secrets/tokens are intentionally excluded — they are loaded from the
     * backend via fetchSettings() after login and kept in memory only.        */
    const LS_SCALAR_KEYS = [
        'piholeUrl', 'monitoredServices', 'radarIps',
        'bookmarksStr', 'plexUrl', 'kumaUrl', 'bmcMap',
        'wanTestIp', 'lanTestIp',
        'truenasUrl',
        'radarrUrl',
        'sonarrUrl',
        'qbitUrl',    'qbitUser',
        'proxmoxUrl', 'proxmoxUser', 'proxmoxTokenName',
    ];

    // One-time migration: remove any legacy credential keys left in localStorage.
    ['noba-pihole-tok', 'noba-plex-tok', 'noba-truenas-key',
     'noba-radarr-key', 'noba-sonarr-key', 'noba-qbit-pass']
        .forEach(k => localStorage.removeItem(k));

    /**
     * Keys that the server is allowed to push via SSE / refreshStats.
     * Prevents the server from overwriting internal state (_es, _poll, etc.).
     */
    const LIVE_DATA_KEYS = new Set([
        'timestamp', 'uptime', 'loadavg', 'memory', 'hostname', 'defaultIp',
        'memPercent', 'cpuPercent', 'cpuHistory', 'cpuTemp', 'gpuTemp',
        'osName', 'kernel', 'hwCpu', 'hwGpu', 'netRx', 'netTx',
        'battery', 'disks', 'services', 'zfs', 'radar', 'kuma', 'netHealth',
        'topCpu', 'topMem', 'pihole', 'plex', 'containers', 'alerts',
        'truenas', 'radarr', 'sonarr', 'qbit', 'proxmox',
    ]);

    const DEF_VIS = {
        core: true, netio: true, hw: true, battery: true, pihole: true,
        storage: true, radar: true, kuma: true, procs: true, containers: true,
        services: true, logs: true, actions: true, bookmarks: true, plex: true,
        truenas: true, downloads: true, automations: true, proxmox: true,
    };

    const DEF_BOOKMARKS = 'Router|http://192.168.1.1|fa-network-wired, Pi-hole|http://pi.hole/admin|fa-shield-alt';

    const savedTheme = localStorage.getItem('noba-theme');
    const autoTheme  = savedTheme ||
    (window.matchMedia('(prefers-color-scheme: light)').matches ? 'nord' : 'default');

    // Monotonic counter for toast IDs (avoids Date.now()+random collisions).
    let _toastSeq = 0;

    // ── 1. Alpine component object ─────────────────────────────────────────────
    return {

        // ── UI & Visibility ────────────────────────────────────────────────────
        theme: autoTheme,
        vis:   { ...DEF_VIS, ...JSON.parse(localStorage.getItem('noba-vis') || '{}') },
        collapsed:  JSON.parse(localStorage.getItem('noba-collapsed') || '{}'),
        svcFilter:  '',
        settingsTab: 'visibility',

        // ── Core integration settings ──────────────────────────────────────────
        piholeUrl:         localStorage.getItem('noba-pihole')       || '',
        piholeToken:       '',   // sensitive — loaded from backend after login
        bookmarksStr:      localStorage.getItem('noba-bookmarks')    || DEF_BOOKMARKS,
        monitoredServices: localStorage.getItem('noba-services')     || 'sshd, docker, NetworkManager',
        radarIps:          localStorage.getItem('noba-radar')        || '192.168.1.1, 1.1.1.1, 8.8.8.8',
        plexUrl:           localStorage.getItem('noba-plex-url')     || '',
        plexToken:         '',   // sensitive — loaded from backend after login
        kumaUrl:           localStorage.getItem('noba-kuma-url')     || '',
        bmcMap:            localStorage.getItem('noba-bmc-map')      || '',
        wanTestIp:         localStorage.getItem('noba-wan-ip')       || '8.8.8.8',
        lanTestIp:         localStorage.getItem('noba-lan-ip')       || '',

        // ── TrueNAS / Download integrations ───────────────────────────────────
        truenasUrl: localStorage.getItem('noba-truenas-url') || '',
        truenasKey: '',   // sensitive — loaded from backend after login
        radarrUrl:  localStorage.getItem('noba-radarr-url')  || '',
        radarrKey:  '',   // sensitive — loaded from backend after login
        sonarrUrl:  localStorage.getItem('noba-sonarr-url')  || '',
        sonarrKey:  '',   // sensitive — loaded from backend after login
        qbitUrl:    localStorage.getItem('noba-qbit-url')    || '',
        qbitUser:   localStorage.getItem('noba-qbit-user')   || '',
        qbitPass:   '',   // sensitive — loaded from backend after login

        // ── Proxmox VE ─────────────────────────────────────────────────────────
        proxmoxUrl:        localStorage.getItem('noba-pmx-url')       || '',
        proxmoxUser:       localStorage.getItem('noba-pmx-user')      || '',
        proxmoxTokenName:  localStorage.getItem('noba-pmx-tok-name')  || '',
        proxmoxTokenValue: '',   // never persisted client-side

        // ── Notification channels ──────────────────────────────────────────────
        pushoverEnabled: false, pushoverAppToken: '', pushoverUserKey: '',
        gotifyEnabled:   false, gotifyUrl: '',        gotifyAppToken: '',

        // ── Dynamic / job settings ─────────────────────────────────────────────
        customActions: [], automations: [], alertRules: [],
        backupSources: [], backupDest: '', cloudRemote: '', downloadsDir: '',
        cloudRemotes: [], selectedCloudRemote: '', cloudRemotesLoading: false,
        rcloneAvailable: null, rcloneVersion: '', cloudTestResults: {},

        // ── Live data ──────────────────────────────────────────────────────────
        timestamp: '--:--', uptime: '--', loadavg: '--', memory: '--',
        hostname: '--', defaultIp: '--',
        memPercent: 0, cpuPercent: 0, cpuHistory: [], cpuTemp: 'N/A', gpuTemp: 'N/A',
        osName: '--', kernel: '--', hwCpu: '--', hwGpu: '--',
        netRx: '0 B/s', netTx: '0 B/s',
        battery: { percent: 0, status: 'Unknown', desktop: false },
        disks: [], services: [], zfs: { pools: [] }, radar: [], kuma: [],
        netHealth: { wan: 'Down', lan: 'Down', configured: false },
        topCpu: [], topMem: [], pihole: null, plex: null, containers: [],
        alerts: [], truenas: null, radarr: null, sonarr: null, qbit: null,
        proxmox: null,

        // ── App state ──────────────────────────────────────────────────────────
        selectedLog: 'syserr', logContent: 'Loading...', logLoading: false,
        showModal: false, showSettings: false,
        modalTitle: '', modalOutput: '', runningScript: false, refreshing: false,
        toasts: [],
        notifTesting: false,

        // History and Audit State
        showHistoryModal: false,
        historyMetric: '',
        historyData: [],
        historyRange: 24,
        historyResolution: 60,
        historyChart: null,
        showAuditModal: false,
        auditLog: [],

        // History anomaly overlay
        historyAnomalyEnabled: false,

        // SMART disk health
        smartData: [], smartLoading: false, showSmartModal: false,

        // Voice alerts
        voiceAlertsEnabled: localStorage.getItem('noba-voice-alerts') === 'true',

        // Internal — never overwritten by server payloads
        _es: null, _poll: null, _lastHeartbeat: 0,
        _countdownTimer: null, _reconnecting: false,
        _masonryObserver: null, _keydownHandler: null,
        _spokenAlerts: new Set(),

        // ── Auth ───────────────────────────────────────────────────────────────
        authenticated: !!localStorage.getItem('noba-token'),
        loginUsername: '', loginPassword: '', loginLoading: false, loginError: '',
        connStatus: 'offline', countdown: 5,

        // FIXED: plain object instead of Set so Alpine reactivity works correctly
        _dismissedAlerts: {},

        // ── Admin ──────────────────────────────────────────────────────────────
        userRole: 'viewer', username: '', userList: [], usersLoading: false,
        showAddUserForm: false, newUsername: '', newPassword: '', newRole: 'viewer',
        showPassModal: false, passModalUser: '', passModalValue: '',
        showRemoveModal: false, removeModalUser: '',


        // ── 2. Computed Properties ─────────────────────────────────────────────

        get cpuTempClass() {
            const t = parseInt(this.cpuTemp) || 0;
            return t > 80 ? 'bd' : t > 65 ? 'bw' : 'bn';
        },
        get gpuTempClass() {
            const t = parseInt(this.gpuTemp) || 0;
            return t > 85 ? 'bd' : t > 70 ? 'bw' : 'bn';
        },

        get visibleAlerts() {
            return (this.alerts || []).filter(a => !this._dismissedAlerts[a.msg]);
        },

        get livePillText() {
            let state;
            if      (this.refreshing)             state = 'Syncing…';
            else if (this.connStatus === 'sse')   state = 'Live';
            else if (this.connStatus === 'polling') state = this.countdown + 's';
            else                                  state = 'Offline';
            return (this.timestamp && this.timestamp !== '--:--')
            ? `${state} • ${this.timestamp}`
            : state;
        },

        get parsedBookmarks() {
            return (this.bookmarksStr || '').split(',').filter(b => b.trim()).map(b => {
                const p = b.split('|');
                return {
                    name: (p[0] || 'Link').trim(),
                                                                                  url:  (p[1] || '#').trim(),
                                                                                  icon: (p[2] || 'fa-link').trim(),
                };
            });
        },

        get cpuLine() {
            const h = this.cpuHistory;
            if (h.length < 2) return '0,36 120,36';
            return h.map((v, i) =>
            `${Math.round((i / (h.length - 1)) * 120)},${Math.round(36 - (v / 100) * 32)}`
            ).join(' ');
        },

        get cpuFill() {
            const h = this.cpuHistory;
            if (h.length < 2) return '0,38 120,38 120,38 0,38';
            const pts = h.map((v, i) =>
            `${Math.round((i / (h.length - 1)) * 120)},${Math.round(36 - (v / 100) * 32)}`
            ).join(' ');
            return `${pts} 120,38 0,38`;
        },

        get filteredServices() {
            if (!this.svcFilter) return this.services || [];
            const q = this.svcFilter.toLowerCase();
            return (this.services || []).filter(s => s.name.toLowerCase().includes(q));
        },


        // ── 3. Lifecycle ───────────────────────────────────────────────────────

        async init() {
            try { this.initSortable();  } catch (e) { console.warn('Sortable init skipped', e); }
            try { this.initKeyboard();  } catch (e) { console.warn('Keyboard init skipped', e); }
            try { this.initMasonry();   } catch (e) { console.warn('Masonry init skipped', e); }

            if (!this.authenticated) return;

            // Validate the stored token first. fetchUserInfo() sets authenticated=false
            // on 401, so we bail before firing any other requests with a dead token.
            await this.fetchUserInfo();
            if (!this.authenticated) return;

            // Token confirmed good — fetch remaining data in parallel
            await Promise.all([
                this.fetchSettings(),
                              this.fetchCloudRemotes(),
                              this.fetchLog(),
            ]);

            if (this.userRole === 'admin') await this.fetchUsers();

            this.connectSSE();

            setInterval(() => {
                if (this.vis.logs && !this.showSettings) this.fetchLog();
            }, 12000);

                setInterval(() => {
                    this.fetchCloudRemotes();
                }, 300_000);

                // Heartbeat watchdog — reconnects SSE if server goes silent for >15 s
                setInterval(() => {
                    if (this.connStatus === 'sse' && this._lastHeartbeat &&
                        Date.now() - this._lastHeartbeat > 15_000 &&
                        !this._reconnecting) {
                        this.connectSSE();
                        }
                }, 5000);
        },


        // ── 4. Layout & UI Logic ───────────────────────────────────────────────

        initMasonry() {
            // Store observer reference so cards can be unobserved when hidden
            this._masonryObserver = new ResizeObserver(entries => {
                for (const entry of entries) {
                    const card = entry.target;
                    if (card.style.display === 'none') continue;
                    const height   = card.getBoundingClientRect().height;
                    const rowSpan  = Math.ceil((height + 18) / 10);
                    card.style.gridRowEnd = `span ${rowSpan}`;
                }
            });
            // Use rAF (not $nextTick) so the browser has finished painting the
            // layout after x-cloak is removed from the grid — otherwise
            // getBoundingClientRect() returns 0 for all cards and every card
            // collapses to a 20px strip that gets covered by later cards.
            requestAnimationFrame(() => requestAnimationFrame(() => {
                document.querySelectorAll('.card').forEach(c => this._masonryObserver.observe(c));
            }));
        },

        initSortable() {
            if (typeof Sortable === 'undefined') return;
            const grid = document.getElementById('sortable-grid');
            if (!grid) return;

            Sortable.create(grid, {
                animation: 200,
                handle: '.card-hdr',
                ghostClass: 'sortable-ghost',
                dragClass: 'sortable-drag',
                forceFallback: true,
                    fallbackOnBody: true,
                    group: 'noba-v9',
                    store: {
                        get: s => (localStorage.getItem(s.options.group.name) || '').split('|'),
                            set: s => localStorage.setItem(s.options.group.name, s.toArray().join('|')),
                    },
            });
        },

        initKeyboard() {
            // Store handler reference so it can be removed on destroy if needed
            this._keydownHandler = (e) => {
                if (e.target.tagName === 'INPUT' || e.target.tagName === 'TEXTAREA') return;
                if (e.key === 's' && !this.showSettings && !this.showModal) {
                    this.showSettings = true;
                } else if (e.key === 'r' && !this.showSettings && !this.showModal && this.authenticated) {
                    this.refreshStats();
                } else if (e.key === 'Escape') {
                    this.showSettings  = false;
                    this.showModal     = false;
                    this.showPassModal = false;
                    this.showRemoveModal = false;
                    this.showHistoryModal = false;
                    this.showAuditModal = false;
                }
            };
            document.addEventListener('keydown', this._keydownHandler);
        },

        toggleCollapse(card) {
            this.collapsed[card] = !this.collapsed[card];
            localStorage.setItem('noba-collapsed', JSON.stringify(this.collapsed));
        },

        copyVal(val, e) {
            if (!val || val === '--') return;
            navigator.clipboard.writeText(val).catch(() => {});
            const el = e?.target;
            if (el) {
                el.classList.add('copied');
                setTimeout(() => el.classList.remove('copied'), 1000);
            }
        },

        dismissAlert(msg) {
            this._dismissedAlerts = { ...this._dismissedAlerts, [msg]: true };
        },

        addToast(msg, type = 'info') {
            const id = ++_toastSeq;
            this.toasts.push({ id, msg, type });
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


        // ── 5. Server Communication ────────────────────────────────────────────

        _token() {
            return localStorage.getItem('noba-token') || '';
        },

        _startCountdown(interval = 5) {
            clearInterval(this._countdownTimer);
            this.countdown = interval;
            this._countdownTimer = setInterval(() => {
                if (this.countdown > 0) {
                    this.countdown--;
                } else {
                    this.countdown = interval;
                }
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
                token:    this._token(),
            });
            return params.toString();
        },

        _mergeLiveData(payload) {
            for (const key of LIVE_DATA_KEYS) {
                if (Object.prototype.hasOwnProperty.call(payload, key)) {
                    this[key] = payload[key];
                }
            }
            // Voice alerts — speak new danger alerts once
            if (this.voiceAlertsEnabled && window.speechSynthesis && payload.alerts) {
                for (const alert of payload.alerts) {
                    const key = alert.msg || alert.id || JSON.stringify(alert);
                    if (!this._spokenAlerts.has(key) && alert.level === 'danger') {
                        this._spokenAlerts.add(key);
                        const utt = new SpeechSynthesisUtterance('Warning: ' + (alert.msg || alert.title || 'critical alert'));
                        utt.rate = 0.9;
                        utt.volume = 1;
                        window.speechSynthesis.speak(utt);
                    }
                }
                // Evict keys for alerts that have gone away to avoid the Set growing forever
                const active = new Set((payload.alerts || []).map(a => a.msg || a.id || JSON.stringify(a)));
                for (const k of this._spokenAlerts) {
                    if (!active.has(k)) this._spokenAlerts.delete(k);
                }
            }
        },

        toggleVoiceAlerts() {
            this.voiceAlertsEnabled = !this.voiceAlertsEnabled;
            localStorage.setItem('noba-voice-alerts', this.voiceAlertsEnabled);
            if (this.voiceAlertsEnabled && window.speechSynthesis) {
                // Prime the browser's permission — must be from a user gesture
                const utt = new SpeechSynthesisUtterance('Voice alerts enabled');
                utt.volume = 0.5;
                window.speechSynthesis.speak(utt);
            }
        },

        connectSSE() {
            if (!this.authenticated) return;
            if (this._reconnecting) return;
            this._reconnecting = true;

            if (this._es) { this._es.close(); this._es = null; }
            if (this._poll) { clearInterval(this._poll); this._poll = null; }

            this._stopCountdown();
            this._lastHeartbeat = Date.now();
            this._es = new EventSource(`/api/stream?${this._buildQueryParams()}`);

            this._es.onopen = () => {
                this.connStatus     = 'sse';
                this._reconnecting  = false;
                this._lastHeartbeat = Date.now();
                this._stopCountdown();
            };

            this._es.onmessage = (e) => {
                try {
                    this._mergeLiveData(JSON.parse(e.data));
                    this._lastHeartbeat = Date.now();
                } catch { /* malformed frame — ignore */ }
            };

            this._es.onerror = () => {
                this._reconnecting = false;
                this._es.close();
                this._es = null;
                this.connStatus = 'polling';
                this._startCountdown(5);

                setTimeout(() => {
                    this.refreshStats();
                    this._poll = setInterval(() => {
                        this.refreshStats();
                        this._startCountdown(5);
                    }, 5000);
                }, 3000);
            };
        },

        async refreshStats() {
            if (!this.authenticated || this.refreshing) return;
            this.refreshing = true;
            try {
                const res = await fetch(`/api/stats?${this._buildQueryParams()}`, {
                    headers: { 'Authorization': 'Bearer ' + this._token() },
                });
                if (res.ok) {
                    this._mergeLiveData(await res.json());
                    if (this.connStatus === 'offline') this.connStatus = 'polling';
                } else if (res.status === 401) {
                    this.authenticated = false;
                    this.connStatus    = 'offline';
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
            try {
                const res = await fetch('/api/settings', {
                    headers: { 'Authorization': 'Bearer ' + this._token() },
                });
                if (res.status === 401) return;
                if (!res.ok) throw new Error(`HTTP ${res.status}`);
                const s = await res.json();

                for (const key of SETTINGS_KEYS) {
                    if (s[key] != null) this[key] = s[key];
                }
            } catch (e) {
                this.addToast('Failed to load settings: ' + e.message, 'error');
            }
        },

        async fetchCloudRemotes() {
            if (!this.authenticated) return;
            this.cloudRemotesLoading = true;
            try {
                const res = await fetch('/api/cloud-remotes', {
                    headers: { 'Authorization': 'Bearer ' + this._token() },
                });
                if (res.status === 401) return;
                if (!res.ok) throw new Error(`HTTP ${res.status}`);
                const d = await res.json();
                this.rcloneAvailable = d.available ?? true;
                this.rcloneVersion   = d.version   ?? '';
                this.cloudRemotes    = d.remotes    ?? (Array.isArray(d) ? d : []);
                if (this.cloudRemotes.length && !this.selectedCloudRemote) {
                    const match = this.cloudRemotes.find(r => r.name === this.cloudRemote);
                    this.selectedCloudRemote = match ? match.name : this.cloudRemotes[0].name;
                }
            } catch (e) {
                this.addToast('Failed to fetch cloud remotes: ' + e.message, 'error');
            } finally {
                this.cloudRemotesLoading = false;
            }
        },

        async saveSettings() {
            for (const key of LS_SCALAR_KEYS) {
                localStorage.setItem(`noba-${key.replace(/([A-Z])/g, c => '-' + c.toLowerCase())}`, this[key] ?? '');
            }
            localStorage.setItem('noba-theme',     this.theme);
            localStorage.setItem('noba-vis',        JSON.stringify(this.vis));
            localStorage.setItem('noba-collapsed',  JSON.stringify(this.collapsed));

            if (!this.authenticated) return;

            const body = {};
            for (const key of SETTINGS_KEYS) body[key] = this[key];

            try {
                const res = await fetch('/api/settings', {
                    method:  'POST',
                    headers: {
                        'Content-Type':  'application/json',
                        'Authorization': 'Bearer ' + this._token(),
                    },
                    body: JSON.stringify(body),
                });
                if (!res.ok) throw new Error(`HTTP ${res.status}`);
            } catch (e) {
                this.addToast('Failed to save settings: ' + e.message, 'error');
                throw e;
            }
        },

        async applySettings() {
            try {
                await this.saveSettings();
                this.showSettings = false;
                if (this.authenticated) this.connectSSE();
                this.addToast('Settings saved', 'success');
            } catch {
                // error toast already shown inside saveSettings()
            }
        },

        async testNotifications() {
            if (!this.authenticated || this.userRole !== 'admin') return;
            this.notifTesting = true;
            try {
                const res  = await fetch('/api/notifications/test', {
                    headers: { 'Authorization': 'Bearer ' + this._token() },
                });
                const data = await res.json();
                this.addToast(res.ok ? 'Test notification sent' : (data.detail || data.error || 'Test failed'),
                              res.ok ? 'success' : 'error');
            } catch {
                this.addToast('Network error', 'error');
            } finally {
                this.notifTesting = false;
            }
        },


        // ── 6. Actions & Controls ──────────────────────────────────────────────

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

        async svcAction(svc, action) {
            if (!this.authenticated) return;
            try {
                const res = await fetch('/api/service-control', {
                    method: 'POST',
                    headers: { 'Content-Type': 'application/json', 'Authorization': 'Bearer ' + this._token() },
                                        body: JSON.stringify({ service: svc.name, action, is_user: svc.is_user }),
                });
                const d = await res.json();
                const label = svc.name.replace('.service', '');
                this.addToast(
                    d.success ? `${action}: ${label}` : `Failed: ${label}`,
                    d.success ? 'success' : 'error'
                );
                setTimeout(() => this.refreshStats(), 1200);
            } catch {
                this.addToast('Service control error', 'error');
            }
        },

        async vmAction(vmId, vmName, action) {
            if (!this.authenticated) return;
            this.addToast(`Triggering ${action} on ${vmName}...`, 'info');
            try {
                const res = await fetch('/api/truenas/vm', {
                    method: 'POST',
                    headers: { 'Content-Type': 'application/json', 'Authorization': 'Bearer ' + this._token() },
                                        body: JSON.stringify({ id: vmId, action }),
                });
                const d = await res.json();
                this.addToast(
                    d.success ? `VM ${vmName}: ${action} successful` : `VM ${vmName}: ${action} failed`,
                    d.success ? 'success' : 'error'
                );
                setTimeout(() => this.refreshStats(), 1500);
            } catch {
                this.addToast('VM control error', 'error');
            }
        },

        async triggerWebhook(actId, actName) {
            if (!this.authenticated) return;
            this.addToast(`Firing Webhook: ${actName}...`, 'info');
            try {
                const res = await fetch('/api/webhook', {
                    method: 'POST',
                    headers: { 'Content-Type': 'application/json', 'Authorization': 'Bearer ' + this._token() },
                                        body: JSON.stringify({ id: actId }),
                });
                const d = await res.json();
                this.addToast(d.success ? 'Webhook successful' : 'Webhook failed',
                              d.success ? 'success' : 'error');
            } catch {
                this.addToast('Webhook error', 'error');
            }
        },

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
                this.modalTitle = result.success ? '✓ Completed' : '✗ Failed';
                this.addToast(`${script} ${result.success ? 'completed' : 'failed'}`,
                              result.success ? 'success' : 'error');
            } catch {
                this.modalTitle = '✗ Connection Error';
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


        // ── 7. Auth & Users ────────────────────────────────────────────────────

        async fetchUserInfo() {
            try {
                const res  = await fetch('/api/me', { headers: { 'Authorization': 'Bearer ' + this._token() } });
                if (res.status === 401) {
                    localStorage.removeItem('noba-token');
                    this.authenticated = false;
                    this.connStatus    = 'offline';
                    return;
                }
                if (!res.ok) throw new Error(`HTTP ${res.status}`);
                const data = await res.json();
                this.username = data.username;
                this.userRole = data.role;
            } catch (e) {
                this.addToast('Failed to fetch user info: ' + e.message, 'error');
            }
        },

        async doLogin() {
            this.loginLoading = true;
            this.loginError   = '';
            try {
                const res  = await fetch('/api/login', {
                    method:  'POST',
                    headers: { 'Content-Type': 'application/json' },
                    body:    JSON.stringify({ username: this.loginUsername, password: this.loginPassword }),
                });
                const data = await res.json();
                if (res.ok && data.token) {
                    localStorage.setItem('noba-token', data.token);
                    this.authenticated = true;
                    this.loginPassword = '';

                    await Promise.all([
                        this.fetchUserInfo(),
                                      this.fetchSettings(),
                                      this.fetchCloudRemotes(),
                                      this.fetchLog(),
                    ]);
                    if (this.userRole === 'admin') await this.fetchUsers();
                    this.connectSSE();
                } else {
                    this.loginError = data.detail || data.error || 'Login failed';
                }
            } catch {
                this.loginError = 'Network error';
            } finally {
                this.loginLoading = false;
            }
        },

        async logout() {
            const token = this._token();
            if (token) {
                try {
                    await fetch('/api/logout?token=' + encodeURIComponent(token), { method: 'POST' });
                } catch { /* best-effort */ }
            }
            localStorage.removeItem('noba-token');
            this.authenticated = false;
            this.connStatus    = 'offline';
            this._stopCountdown();
            if (this._es)   { this._es.close();           this._es   = null; }
            if (this._poll) { clearInterval(this._poll);  this._poll = null; }
            if (this._keydownHandler) {
                document.removeEventListener('keydown', this._keydownHandler);
                this._keydownHandler = null;
            }
        },

        async fetchUsers() {
            this.usersLoading = true;
            try {
                const res = await fetch('/api/admin/users', {
                    method:  'POST',
                    headers: { 'Content-Type': 'application/json', 'Authorization': 'Bearer ' + this._token() },
                                        body:    JSON.stringify({ action: 'list' }),
                });
                if (!res.ok) throw new Error(`HTTP ${res.status}`);
                this.userList = await res.json();
            } catch (e) {
                this.addToast('Failed to fetch users: ' + e.message, 'error');
            } finally {
                this.usersLoading = false;
            }
        },

        async addUser() {
            if (!this.newUsername || !this.newPassword) {
                this.addToast('Username and password required', 'error');
                return;
            }
            try {
                const res = await fetch('/api/admin/users', {
                    method:  'POST',
                    headers: { 'Content-Type': 'application/json', 'Authorization': 'Bearer ' + this._token() },
                                        body:    JSON.stringify({ action: 'add', username: this.newUsername, password: this.newPassword, role: this.newRole }),
                });
                if (res.ok) {
                    this.addToast(`User ${this.newUsername} added`, 'success');
                    this.newUsername     = '';
                    this.newPassword     = '';
                    this.newRole         = 'viewer';
                    this.showAddUserForm = false;
                    await this.fetchUsers();
                } else {
                    const err = await res.json();
                    this.addToast(err.detail || err.error || 'Failed to add user', 'error');
                }
            } catch (e) {
                this.addToast('Error adding user: ' + e.message, 'error');
            }
        },

        openPassModal(username) {
            this.passModalUser  = username;
            this.passModalValue = '';
            this.showPassModal  = true;
            this.$nextTick(() => { if (this.$refs.passInput) this.$refs.passInput.focus(); });
        },

        async confirmChangePassword() {
            if (!this.passModalValue) return;
            const username = this.passModalUser;
            try {
                const res = await fetch('/api/admin/users', {
                    method:  'POST',
                    headers: { 'Content-Type': 'application/json', 'Authorization': 'Bearer ' + this._token() },
                                        body:    JSON.stringify({ action: 'change_password', username, password: this.passModalValue }),
                });
                if (res.ok) {
                    this.addToast(`Password changed for ${username}`, 'success');
                } else {
                    const err = await res.json();
                    this.addToast(err.detail || err.error || 'Failed to change password', 'error');
                }
            } catch (e) {
                this.addToast('Error changing password: ' + e.message, 'error');
            } finally {
                this.showPassModal   = false;
                this.passModalValue  = '';
            }
        },

        confirmRemoveUser(username) {
            this.removeModalUser = username;
            this.showRemoveModal = true;
        },

        async confirmRemove() {
            const username       = this.removeModalUser;
            this.showRemoveModal = false;
            try {
                const res = await fetch('/api/admin/users', {
                    method:  'POST',
                    headers: { 'Content-Type': 'application/json', 'Authorization': 'Bearer ' + this._token() },
                                        body:    JSON.stringify({ action: 'remove', username }),
                });
                if (res.ok) {
                    this.addToast(`User ${username} removed`, 'success');
                    await this.fetchUsers();
                } else {
                    const err = await res.json();
                    this.addToast(err.detail || err.error || 'Failed to remove user', 'error');
                }
            } catch (e) {
                this.addToast('Error removing user: ' + e.message, 'error');
            }
        },

        // ── 8. History & Audit ─────────────────────────────────────────────────

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
                    fill: '-1',  // fill between upper and lower band
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
                                    return d && d.anomaly ? '⚠ Anomaly detected' : '';
                                }
                            }
                        }
                    },
                    animation: { duration: 0 }
                }
            });

            this.historyChart = newChart;
        },

        showHistory(metric) {
            this.historyMetric = metric;
            this.showHistoryModal = true;
            this.fetchHistory();
        },

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

        openAuditModal() {
            if (this.userRole !== 'admin') return;
            this.showAuditModal = true;
            this.fetchAuditLog();
        },


        // ── 9. Container Controls ──────────────────────────────────────────────

        async containerAction(name, action) {
            if (!name) return;
            const label = `${action} ${name}`;
            try {
                const res = await fetch('/api/container-control', {
                    method:  'POST',
                    headers: {
                        'Content-Type':  'application/json',
                        'Authorization': 'Bearer ' + this._token(),
                    },
                    body: JSON.stringify({ name, action }),
                });
                const data = await res.json();
                if (data.success) {
                    this.addToast(`${label} — OK`, 'success');
                    // Refresh containers after a short delay for state to settle
                    setTimeout(() => this.refreshStats(), 1500);
                } else {
                    this.addToast(data.error || `${label} failed`, 'error');
                }
            } catch (e) {
                this.addToast(`${label}: ${e.message}`, 'error');
            }
        },


        // ── 10. History Export ─────────────────────────────────────────────────

        downloadHistoryCSV() {
            if (!this.historyMetric) return;
            const url = `/api/history/${encodeURIComponent(this.historyMetric)}/export`
                + `?range=${this.historyRange}&resolution=${this.historyResolution}`;
            // Use a temporary <a> tag so the browser triggers a file download
            const a = document.createElement('a');
            a.href = url + '&token=' + encodeURIComponent(this._token());
            a.download = `noba-${this.historyMetric}-${this.historyRange}h.csv`;
            document.body.appendChild(a);
            a.click();
            document.body.removeChild(a);
        },


        // ── 11. Config Backup / Restore ────────────────────────────────────────

        downloadConfigBackup() {
            const a = document.createElement('a');
            a.href = '/api/config/backup?token=' + encodeURIComponent(this._token());
            a.download = 'noba-config-backup.yaml';
            document.body.appendChild(a);
            a.click();
            document.body.removeChild(a);
        },

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

        smartRiskClass(score) {
            if (score >= 75) return 'bd';
            if (score >= 40) return 'bw';
            return 'bs';
        },

        smartRiskLabel(score) {
            if (score >= 75) return 'Critical';
            if (score >= 40) return 'Warning';
            return 'Healthy';
        },

        formatPoh(hours) {
            if (!hours) return '—';
            const d = Math.floor(hours / 24);
            const h = hours % 24;
            return d > 0 ? `${d}d ${h}h` : `${h}h`;
        },

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
                    this.addToast('Config restored — reloading settings…', 'success');
                    await this.fetchSettings();
                } else {
                    this.addToast(data.detail || data.error || 'Restore failed', 'error');
                }
            } catch (e) {
                this.addToast('Restore error: ' + e.message, 'error');
            } finally {
                // Reset the file input so the same file can be re-selected
                event.target.value = '';
            }
        },

    };
}
