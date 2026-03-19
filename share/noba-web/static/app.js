/**
 * dashboard() — Alpine.js component
 *
 * Split into mixins for maintainability:
 *   - auth-mixin.js    → login/logout, token management, admin user CRUD
 *   - actions-mixin.js → service/VM/container controls, scripts, history,
 *                         audit, SMART, config backup/restore, confirmations
 *   - app.js (this)    → constants, settings, live data, SSE, UI/layout
 *
 * All mixin objects are spread into the returned component, so `this`
 * resolves identically across all files.
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
        'adguardUrl', 'adguardUser', 'adguardPass',
        'jellyfinUrl', 'jellyfinKey',
        'hassUrl', 'hassToken',
        'unifiUrl', 'unifiUser', 'unifiPass', 'unifiSite',
        'speedtestUrl',
        'pushoverEnabled', 'pushoverAppToken', 'pushoverUserKey',
        'gotifyEnabled', 'gotifyUrl', 'gotifyAppToken',
        'alertRules',
    ];

    /** Keys that live in localStorage as a local mirror.
     * Secrets/tokens are intentionally excluded — they are loaded from the
     * backend via fetchSettings() after login and kept in memory only.        */
    /** Map of data property → localStorage key for non-sensitive settings. */
    const LS_KEY_MAP = {
        piholeUrl:        'noba-pihole',
        monitoredServices:'noba-services',
        radarIps:         'noba-radar',
        bookmarksStr:     'noba-bookmarks',
        plexUrl:          'noba-plex-url',
        kumaUrl:          'noba-kuma-url',
        bmcMap:           'noba-bmc-map',
        wanTestIp:        'noba-wan-ip',
        lanTestIp:        'noba-lan-ip',
        truenasUrl:       'noba-truenas-url',
        radarrUrl:        'noba-radarr-url',
        sonarrUrl:        'noba-sonarr-url',
        qbitUrl:          'noba-qbit-url',
        qbitUser:         'noba-qbit-user',
        proxmoxUrl:       'noba-pmx-url',
        proxmoxUser:      'noba-pmx-user',
        proxmoxTokenName: 'noba-pmx-tok-name',
        adguardUrl:    'noba-adguard-url',
        adguardUser:   'noba-adguard-user',
        jellyfinUrl:   'noba-jellyfin-url',
        hassUrl:       'noba-hass-url',
        unifiUrl:      'noba-unifi-url',
        unifiUser:     'noba-unifi-user',
        unifiSite:     'noba-unifi-site',
        speedtestUrl:  'noba-speedtest-url',
    };

    // One-time migration: remove any legacy credential keys left in localStorage.
    try {
        ['noba-pihole-tok', 'noba-plex-tok', 'noba-truenas-key',
         'noba-radarr-key', 'noba-sonarr-key', 'noba-qbit-pass']
            .forEach(k => localStorage.removeItem(k));
    } catch (_) { /* localStorage unavailable */ }

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
        'truenas', 'radarr', 'sonarr', 'qbit', 'proxmox', 'plugins',
        'adguard', 'jellyfin', 'hass', 'unifi', 'speedtest',
        'diskIo', 'netInterfaces', 'topIo',
    ]);

    const DEF_VIS = {
        core: true, netio: true, hw: true, battery: true, pihole: true,
        storage: true, radar: true, kuma: true, procs: true, containers: true,
        services: true, logs: true, actions: true, bookmarks: true, plex: true,
        truenas: true, downloads: true, automations: true, proxmox: true,
        adguard: true, jellyfin: true, hass: true, unifi: true, speedtest: true, diskIo: true,
    };

    const DEF_BOOKMARKS = 'Router|http://192.168.1.1|fa-network-wired, Pi-hole|http://pi.hole/admin|fa-shield-alt';

    const savedTheme = localStorage.getItem('noba-theme');
    const autoTheme  = savedTheme ||
    (window.matchMedia('(prefers-color-scheme: light)').matches ? 'nord' : 'default');

    // Monotonic counter for toast IDs (avoids Date.now()+random collisions).
    let _toastSeq = 0;

    /** Parse JSON from localStorage, returning {} on corrupted data. */
    function _safeParse(raw) {
        try { return raw ? JSON.parse(raw) : {}; }
        catch { return {}; }
    }

    // ── 1. Alpine component object ─────────────────────────────────────────────
    return {

        // ── Spread mixins ────────────────────────────────────────────────────
        ...authMixin(),
        ...actionsMixin(),

        // ── UI & Visibility ────────────────────────────────────────────────────
        theme: autoTheme,
        vis:   { ...DEF_VIS, ..._safeParse(localStorage.getItem('noba-vis')) },
        collapsed:  _safeParse(localStorage.getItem('noba-collapsed')),
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

        // ── New integrations ──────────────────────────────────────────────────
        adguardUrl:   localStorage.getItem('noba-adguard-url')   || '',
        adguardUser:  localStorage.getItem('noba-adguard-user')  || '',
        adguardPass:  '',
        jellyfinUrl:  localStorage.getItem('noba-jellyfin-url')  || '',
        jellyfinKey:  '',
        hassUrl:      localStorage.getItem('noba-hass-url')      || '',
        hassToken:    '',
        unifiUrl:     localStorage.getItem('noba-unifi-url')     || '',
        unifiUser:    localStorage.getItem('noba-unifi-user')    || '',
        unifiPass:    '',
        unifiSite:    localStorage.getItem('noba-unifi-site')    || 'default',
        speedtestUrl: localStorage.getItem('noba-speedtest-url') || '',

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
        proxmox: null, plugins: [],
        adguard: null, jellyfin: null, hass: null, unifi: null, speedtest: null,
        diskIo: [], netInterfaces: [], topIo: [],

        // ── App state ──────────────────────────────────────────────────────────
        showSettings: false, refreshing: false,
        showShortcutsModal: false,
        showSessionsModal: false,
        sessionList: [],
        toasts: [],
        notifTesting: false,
        countdown: 5,

        // Voice alerts
        voiceAlertsEnabled: localStorage.getItem('noba-voice-alerts') === 'true',

        // Internal — never overwritten by server payloads
        _es: null, _poll: null, _lastHeartbeat: 0,
        _countdownTimer: null, _reconnecting: false,
        _masonryObserver: null, _keydownHandler: null,
        _logTimer: null, _cloudTimer: null, _heartbeatTimer: null,
        _spokenAlerts: new Set(),

        // FIXED: plain object instead of Set so Alpine reactivity works correctly
        _dismissedAlerts: {},


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
            if      (this.refreshing)             state = 'Syncing\u2026';
            else if (this.connStatus === 'sse')   state = 'Live';
            else if (this.connStatus === 'polling') state = this.countdown + 's';
            else                                  state = 'Offline';
            return (this.timestamp && this.timestamp !== '--:--')
            ? `${state} \u2022 ${this.timestamp}`
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
            try { this.initTouch();     } catch (e) { console.warn('Touch init skipped', e); }

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

            if (this._logTimer) clearInterval(this._logTimer);
            this._logTimer = setInterval(() => {
                if (this.vis.logs && !this.showSettings) this.fetchLog();
            }, 12000);

            if (this._cloudTimer) clearInterval(this._cloudTimer);
            this._cloudTimer = setInterval(() => {
                this.fetchCloudRemotes();
            }, 300_000);

            // Heartbeat watchdog — reconnects SSE if server goes silent for >15 s
            if (this._heartbeatTimer) clearInterval(this._heartbeatTimer);
            this._heartbeatTimer = setInterval(() => {
                if (this.connStatus === 'sse' && this._lastHeartbeat &&
                    Date.now() - this._lastHeartbeat > 15_000 &&
                    !this._reconnecting) {
                    this.connectSSE();
                }
            }, 5000);

            // Auto theme switch
            window.matchMedia('(prefers-color-scheme: light)').addEventListener('change', (e) => {
                if (this.theme === 'auto') {
                    document.documentElement.setAttribute('data-theme', e.matches ? 'nord' : 'default');
                }
            });
        },


        // ── 4. Layout & UI Logic ───────────────────────────────────────────────

        initMasonry() {
            this._masonryObserver = new ResizeObserver(entries => {
                for (const entry of entries) {
                    const card = entry.target;
                    if (card.style.display === 'none') continue;
                    const height   = card.getBoundingClientRect().height;
                    const rowSpan  = Math.ceil((height + 18) / 10);
                    card.style.gridRowEnd = `span ${rowSpan}`;
                }
            });
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
            if (this._keydownHandler) {
                document.removeEventListener('keydown', this._keydownHandler);
            }
            this._keydownHandler = (e) => {
                if (e.target.tagName === 'INPUT' || e.target.tagName === 'TEXTAREA') return;
                if (e.key === '?' && !e.ctrlKey && !e.altKey) {
                    e.preventDefault();
                    this.showShortcutsModal = !this.showShortcutsModal;
                    return;
                }
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
                    this.showShortcutsModal = false;
                    this.showSessionsModal = false;
                }
            };
            document.addEventListener('keydown', this._keydownHandler);
        },

        initTouch() {
            let startY = 0, startX = 0, pulling = false;
            const grid = document.getElementById('sortable-grid');
            if (!grid) return;

            // Pull-to-refresh
            grid.addEventListener('touchstart', (e) => {
                if (grid.scrollTop === 0 && e.touches.length === 1) {
                    startY = e.touches[0].clientY;
                    pulling = true;
                }
            }, { passive: true });
            grid.addEventListener('touchmove', (e) => {
                if (!pulling) return;
                const dy = e.touches[0].clientY - startY;
                if (dy > 80 && !this.refreshing) {
                    pulling = false;
                    this.refreshStats();
                    this.addToast('Refreshing...', 'info');
                }
            }, { passive: true });
            grid.addEventListener('touchend', () => { pulling = false; }, { passive: true });

            // Swipe-to-dismiss alerts
            document.addEventListener('touchstart', (e) => {
                const alert = e.target.closest('.alert-banner');
                if (!alert) return;
                startX = e.touches[0].clientX;
                alert._swiping = true;
            }, { passive: true });
            document.addEventListener('touchmove', (e) => {
                const alert = e.target.closest('.alert-banner');
                if (!alert || !alert._swiping) return;
                const dx = e.touches[0].clientX - startX;
                alert.style.transform = `translateX(${dx}px)`;
                alert.style.opacity = Math.max(0, 1 - Math.abs(dx) / 200);
            }, { passive: true });
            document.addEventListener('touchend', (e) => {
                const alert = e.target.closest('.alert-banner');
                if (!alert || !alert._swiping) return;
                alert._swiping = false;
                const dx = parseInt(alert.style.transform?.match(/-?\d+/)?.[0] || '0');
                if (Math.abs(dx) > 100) {
                    const msg = alert.dataset.msg;
                    if (msg) this.dismissAlert(msg);
                } else {
                    alert.style.transform = '';
                    alert.style.opacity = '';
                }
            }, { passive: true });
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

        /** Format bytes-per-second as human-readable string. */
        humanBps(bps) {
            if (!bps || bps <= 0) return '0 B/s';
            const units = ['B/s', 'KB/s', 'MB/s', 'GB/s', 'TB/s'];
            let v = bps, i = 0;
            while (v >= 1024 && i < units.length - 1) { v /= 1024; i++; }
            return v.toFixed(1) + ' ' + units[i];
        },

        /** Format byte count as human-readable string. */
        humanBytes(bytes) {
            if (!bytes || bytes <= 0) return '\u2014';
            const units = ['B', 'KB', 'MB', 'GB', 'TB', 'PB'];
            let v = bytes, i = 0;
            while (v >= 1024 && i < units.length - 1) { v /= 1024; i++; }
            return v.toFixed(1) + ' ' + units[i];
        },


        // ── 5. Server Communication ────────────────────────────────────────────

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
                const utt = new SpeechSynthesisUtterance('Voice alerts enabled');
                utt.volume = 0.5;
                window.speechSynthesis.speak(utt);
            }
        },

        /** Connect to SSE stream with automatic polling fallback. */
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
                this._lastHeartbeat = Date.now();
                try {
                    this._mergeLiveData(JSON.parse(e.data));
                } catch { /* malformed frame — ignore */ }
            };

            this._es.onerror = () => {
                this._reconnecting = false;
                if (this._es) { this._es.close(); this._es = null; }
                if (this._poll) return;   // already fell back to polling
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

        /** Fetch stats via REST (polling fallback). */
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

        /** Load all settings from the backend. */
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

        /** Fetch available rclone cloud remotes. */
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

        /** Persist settings to localStorage and backend. */
        async saveSettings() {
            for (const [prop, lsKey] of Object.entries(LS_KEY_MAP)) {
                localStorage.setItem(lsKey, this[prop] ?? '');
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

        /** Save settings and reconnect SSE. */
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

        /** Send a test notification (admin only). */
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

    };
}
