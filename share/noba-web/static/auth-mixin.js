/**
 * Auth & user-management mixin for the NOBA dashboard component.
 *
 * Provides login/logout flow, token management, and admin user CRUD.
 * All methods use `this` which resolves to the parent Alpine component
 * instance after spreading.
 *
 * @returns {Object} Alpine component mixin (state + methods)
 */
function authMixin() {
    return {

        // ── Auth state ──────────────────────────────────────────────────────────
        authenticated: !!localStorage.getItem('noba-token'),
        loginUsername: '', loginPassword: '', loginLoading: false, loginError: '',
        connStatus: 'offline',
        userRole: 'viewer', username: '',

        // ── Admin / user management state ────────────────────────────────────────
        userList: [], usersLoading: false,
        showAddUserForm: false, newUsername: '', newPassword: '', newRole: 'viewer',
        showPassModal: false, passModalUser: '', passModalValue: '',
        showRemoveModal: false, removeModalUser: '',

        // ── Token helper ────────────────────────────────────────────────────────

        /**
         * Return the current bearer token from localStorage.
         * @returns {string}
         */
        _token() {
            return localStorage.getItem('noba-token') || '';
        },

        // ── Auth flow ───────────────────────────────────────────────────────────

        /**
         * Fetch the current user's identity from /api/me.
         * Sets `authenticated = false` on 401 (expired / invalid token).
         */
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

        /**
         * Authenticate against /api/login; on success, stores the token and
         * bootstraps the rest of the dashboard (settings, SSE, etc.).
         */
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

        /** Log out: revoke token server-side, clear local state, disconnect SSE. */
        async logout() {
            const token = this._token();
            if (token) {
                try {
                    await fetch('/api/logout', {
                        method: 'POST',
                        headers: { 'Authorization': 'Bearer ' + token },
                    });
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
            if (this._masonryObserver) {
                this._masonryObserver.disconnect();
                this._masonryObserver = null;
            }
            if (this._logTimer)      { clearInterval(this._logTimer);      this._logTimer = null; }
            if (this._cloudTimer)    { clearInterval(this._cloudTimer);    this._cloudTimer = null; }
            if (this._heartbeatTimer){ clearInterval(this._heartbeatTimer);this._heartbeatTimer = null; }
        },

        // ── Admin user management ───────────────────────────────────────────────

        /** Fetch the full user list (admin only). */
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

        /** Create a new user account (admin only). */
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

        /** Open the password-change modal for a given user. */
        openPassModal(username) {
            this.passModalUser  = username;
            this.passModalValue = '';
            this.showPassModal  = true;
            this.$nextTick(() => { if (this.$refs.passInput) this.$refs.passInput.focus(); });
        },

        /** Submit the password change from the modal. */
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

        /** Open the user-removal confirmation modal. */
        confirmRemoveUser(username) {
            this.removeModalUser = username;
            this.showRemoveModal = true;
        },

        /** Execute user removal after confirmation. */
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
    };
}
