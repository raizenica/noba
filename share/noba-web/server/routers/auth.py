"""Noba – Authentication, user management, and profile endpoints."""
from __future__ import annotations

import logging
import secrets
import time

from fastapi import APIRouter, Depends, HTTPException, Request
from fastapi.responses import RedirectResponse

from ..auth import (
    check_password_strength, load_legacy_user, pbkdf2_hash,
    rate_limiter, token_store, users, valid_username, verify_password,
)
from ..config import VALID_ROLES
from ..deps import _client_ip, _get_auth, _read_body, _require_admin, db
from ..yaml_config import read_yaml_settings

logger = logging.getLogger("noba")

# One-time OIDC exchange codes: {code: (noba_token, expiry_time)}
_oidc_codes: dict[str, tuple[str, float]] = {}
_oidc_codes_lock = __import__("threading").Lock()

router = APIRouter()


# ── /api/login ────────────────────────────────────────────────────────────────
@router.post("/api/login")
async def api_login(request: Request):
    ip = _client_ip(request)
    if rate_limiter.is_locked(ip):
        raise HTTPException(429, "Too many failed attempts. Try again shortly.")
    body     = await _read_body(request)
    username = body.get("username", "")
    password = body.get("password", "")

    # User DB check (preferred -- has up-to-date passwords and roles)
    user_data = users.get(username)
    if user_data and verify_password(user_data[0], password):
        rate_limiter.reset(ip)
        # Round 6: 2FA check
        if users.has_totp(username):
            totp_code = body.get("totp_code", "")
            if not totp_code:
                return {"requires_2fa": True, "username": username}
            from ..auth import verify_totp
            totp_secret = users.get_totp_secret(username)
            if not verify_totp(totp_secret, totp_code):
                raise HTTPException(401, "Invalid 2FA code")
        # Check if 2FA is required but not set up
        cfg_settings = read_yaml_settings()
        if cfg_settings.get("require2fa") and not users.has_totp(username):
            rate_limiter.reset(ip)
            token = token_store.generate(username, user_data[1])
            return {"token": token, "requires_2fa_setup": True}
        token = token_store.generate(username, user_data[1])
        db.audit_log("login", username, "success", ip)
        return {"token": token}

    # LDAP fallback
    if not user_data:
        from ..auth import authenticate_ldap
        ldap_user, ldap_role = authenticate_ldap(username, password, read_yaml_settings)
        if ldap_user:
            rate_limiter.reset(ip)
            token = token_store.generate(ldap_user, ldap_role)
            db.audit_log("login", ldap_user, "success (LDAP)", ip)
            return {"token": token}

    # Legacy auth.conf fallback (only when user not in DB)
    if not user_data:
        legacy = load_legacy_user()
        if legacy and username == legacy[0] and verify_password(legacy[1], password):
            rate_limiter.reset(ip)
            token = token_store.generate(username, "admin")
            db.audit_log("login", username, "success (legacy)", ip)
            return {"token": token}

    locked = rate_limiter.record_failure(ip)
    logger.warning("Failed login for '%s' from %s", username, ip)
    db.audit_log("login_failed", username or "unknown", f"Failed from {ip}", ip)
    raise HTTPException(401, "Too many failed attempts." if locked else "Invalid credentials")


# ── /api/logout ───────────────────────────────────────────────────────────────
@router.post("/api/logout")
async def api_logout(request: Request):
    ip   = _client_ip(request)
    auth = request.headers.get("Authorization", "")
    tok  = auth[7:] if auth.startswith("Bearer ") else ""
    if tok:
        uname, _ = token_store.validate(tok)
        if uname:
            db.audit_log("logout", uname, "", ip)
        token_store.revoke(tok)
    return {"status": "ok"}


# ── TOTP 2FA routes ──────────────────────────────────────────────────────────
@router.post("/api/auth/totp/setup")
async def api_totp_setup(request: Request, auth=Depends(_get_auth)):
    from ..auth import generate_totp_secret
    username, _ = auth
    secret = generate_totp_secret()
    return {"secret": secret, "provisioning_uri": f"otpauth://totp/NOBA:{username}?secret={secret}&issuer=NOBA"}


@router.post("/api/auth/totp/enable")
async def api_totp_enable(request: Request, auth=Depends(_get_auth)):
    from ..auth import verify_totp
    username, _ = auth
    body = await _read_body(request)
    secret = body.get("secret", "")
    code = body.get("code", "")
    if not verify_totp(secret, code):
        raise HTTPException(400, "Invalid TOTP code")
    users.set_totp_secret(username, secret)
    db.audit_log("totp_enable", username, "Enabled 2FA", _client_ip(request))
    return {"status": "ok"}


@router.post("/api/auth/totp/disable")
async def api_totp_disable(request: Request, auth=Depends(_require_admin)):
    username, _ = auth
    body = await _read_body(request)
    target = body.get("username", username)
    users.set_totp_secret(target, None)
    db.audit_log("totp_disable", username, f"Disabled 2FA for {target}", _client_ip(request))
    return {"status": "ok"}


# ── Social / OIDC provider presets ────────────────────────────────────────────
_PROVIDER_PRESETS = {
    "google": {
        "authorize_url": "https://accounts.google.com/o/oauth2/v2/auth",
        "token_url": "https://oauth2.googleapis.com/token",
        "userinfo_url": "https://openidconnect.googleapis.com/v1/userinfo",
        "scope": "openid email profile",
        "name": "Google",
    },
    "facebook": {
        "authorize_url": "https://www.facebook.com/v19.0/dialog/oauth",
        "token_url": "https://graph.facebook.com/v19.0/oauth/access_token",
        "userinfo_url": "https://graph.facebook.com/me?fields=id,name,email",
        "scope": "email public_profile",
        "name": "Facebook",
    },
    "github": {
        "authorize_url": "https://github.com/login/oauth/authorize",
        "token_url": "https://github.com/login/oauth/access_token",
        "userinfo_url": "https://api.github.com/user",
        "scope": "read:user user:email",
        "name": "GitHub",
    },
    "microsoft": {
        "authorize_url": "https://login.microsoftonline.com/common/oauth2/v2.0/authorize",
        "token_url": "https://login.microsoftonline.com/common/oauth2/v2.0/token",
        "userinfo_url": "https://graph.microsoft.com/v1.0/me",
        "scope": "openid email profile User.Read",
        "name": "Microsoft",
    },
}


def _resolve_provider(cfg: dict, provider_key: str = "") -> dict | None:
    """Resolve provider config from preset name or generic OIDC settings.

    Supports both:
    - Named presets: provider_key="google" with socialProviders.google.clientId/clientSecret
    - Generic OIDC: oidcProviderUrl + oidcClientId + oidcClientSecret
    """
    # Check named social provider
    if provider_key and provider_key in _PROVIDER_PRESETS:
        social = cfg.get("socialProviders", {}).get(provider_key, {})
        client_id = social.get("clientId", "")
        client_secret = social.get("clientSecret", "")
        if client_id:
            preset = _PROVIDER_PRESETS[provider_key]
            return {
                "authorize_url": preset["authorize_url"],
                "token_url": preset["token_url"],
                "userinfo_url": preset["userinfo_url"],
                "scope": preset["scope"],
                "client_id": client_id,
                "client_secret": client_secret,
                "name": preset["name"],
            }
        return None

    # Fall back to generic OIDC
    provider_url = cfg.get("oidcProviderUrl", "")
    client_id = cfg.get("oidcClientId", "")
    client_secret = cfg.get("oidcClientSecret", "")
    if provider_url and client_id:
        return {
            "authorize_url": f"{provider_url.rstrip('/')}/authorize",
            "token_url": f"{provider_url.rstrip('/')}/token",
            "userinfo_url": f"{provider_url.rstrip('/')}/userinfo",
            "scope": "openid email profile",
            "client_id": client_id,
            "client_secret": client_secret,
            "name": "OIDC",
        }
    return None


@router.get("/api/auth/providers")
def api_auth_providers():
    """List available authentication providers (for login page buttons)."""
    cfg = read_yaml_settings()
    providers = []
    # Check each social preset
    for key in _PROVIDER_PRESETS:
        social = cfg.get("socialProviders", {}).get(key, {})
        if social.get("clientId"):
            providers.append({
                "id": key,
                "name": _PROVIDER_PRESETS[key]["name"],
                "url": f"/api/auth/social/{key}/login",
            })
    # Check generic OIDC
    if cfg.get("oidcProviderUrl") and cfg.get("oidcClientId"):
        providers.append({
            "id": "oidc",
            "name": cfg.get("oidcProviderName", "SSO"),
            "url": "/api/auth/oidc/login",
        })
    return providers


# ── Social login routes (Google, Facebook, GitHub, Microsoft) ────────────────
@router.get("/api/auth/social/{provider}/login")
async def api_social_login(provider: str, request: Request):
    """Redirect to social provider for authentication."""
    cfg = read_yaml_settings()
    prov = _resolve_provider(cfg, provider)
    if not prov:
        raise HTTPException(400, f"Provider '{provider}' not configured")
    import urllib.parse
    redirect_uri = str(request.url_for("api_social_callback", provider=provider))
    params = {
        "client_id": prov["client_id"],
        "response_type": "code",
        "scope": prov["scope"],
        "redirect_uri": redirect_uri,
    }
    # Google requires access_type for refresh tokens
    if provider == "google":
        params["access_type"] = "offline"
        params["prompt"] = "select_account"
    return RedirectResponse(f"{prov['authorize_url']}?{urllib.parse.urlencode(params)}")


@router.get("/api/auth/social/{provider}/callback")
async def api_social_callback(provider: str, request: Request):
    """Handle social provider callback — exchange code, create session."""
    cfg = read_yaml_settings()
    prov = _resolve_provider(cfg, provider)
    if not prov:
        raise HTTPException(400, f"Provider '{provider}' not configured")
    code = request.query_params.get("code", "")
    if not code:
        raise HTTPException(400, "Missing authorization code")
    redirect_uri = str(request.url_for("api_social_callback", provider=provider))
    import httpx as _httpx
    try:
        # Exchange code for token
        headers = {"Accept": "application/json"}
        r = _httpx.post(prov["token_url"], data={
            "grant_type": "authorization_code",
            "code": code,
            "redirect_uri": redirect_uri,
            "client_id": prov["client_id"],
            "client_secret": prov["client_secret"],
        }, headers=headers, timeout=10)
        r.raise_for_status()
        token_data = r.json()
        access_token = token_data.get("access_token", "")
        # Get user info
        userinfo = _httpx.get(
            prov["userinfo_url"],
            headers={"Authorization": f"Bearer {access_token}"},
            timeout=5,
        ).json()
        # Extract email — different providers use different fields
        email = (
            userinfo.get("email")
            or userinfo.get("mail")
            or userinfo.get("preferred_username")
            or userinfo.get("login")  # GitHub uses 'login'
            or ""
        )
        if not email:
            # GitHub: email may be private, need separate API call
            if provider == "github":
                emails_resp = _httpx.get(
                    "https://api.github.com/user/emails",
                    headers={"Authorization": f"Bearer {access_token}"},
                    timeout=5,
                ).json()
                for e in emails_resp:
                    if e.get("primary") and e.get("verified"):
                        email = e["email"]
                        break
        if not email:
            raise HTTPException(400, "Could not determine email from provider")
        # Create or find user
        if not users.exists(email):
            users.add(email, "!oidc:disabled", "viewer")
            logger.info("Social login: created user %s via %s", email, provider)
        user_role = users.role(email)
        noba_token = token_store.generate(email, user_role)
        db.audit_log("social_login", email, f"{prov['name']} login", _client_ip(request))
        # Issue one-time code
        oidc_code = secrets.token_urlsafe(32)
        with _oidc_codes_lock:
            now = time.time()
            expired = [k for k, (_, exp) in _oidc_codes.items() if now > exp]
            for k in expired:
                del _oidc_codes[k]
            _oidc_codes[oidc_code] = (noba_token, now + 60)
        return RedirectResponse(f"/#oidc_code={oidc_code}")
    except HTTPException:
        raise
    except Exception as e:
        logger.error("Social callback error (%s): %s", provider, e)
        raise HTTPException(502, f"{prov['name']} authentication failed")


# ── Account linking — connect social provider to existing NOBA account ───────
# Stored as JSON in a linked_providers field on the user record.
# {provider: {email: "...", linked_at: timestamp}}
_linked_providers: dict[str, dict] = {}  # username -> {provider: {email, linked_at}}
_linked_lock = __import__("threading").Lock()


@router.get("/api/auth/social/{provider}/link")
async def api_social_link(provider: str, request: Request):
    """Initiate account linking — redirect to provider, come back to link callback."""
    cfg = read_yaml_settings()
    prov = _resolve_provider(cfg, provider)
    if not prov:
        raise HTTPException(400, f"Provider '{provider}' not configured")
    import urllib.parse
    redirect_uri = str(request.url_for("api_social_link_callback", provider=provider))
    # Pass the NOBA token as state so we know who's linking
    token = request.query_params.get("token", "")
    if not token:
        raise HTTPException(400, "Missing token — must be logged in to link accounts")
    params = {
        "client_id": prov["client_id"],
        "response_type": "code",
        "scope": prov["scope"],
        "redirect_uri": redirect_uri,
        "state": token,  # NOBA auth token as state
    }
    return RedirectResponse(f"{prov['authorize_url']}?{urllib.parse.urlencode(params)}")


@router.get("/api/auth/social/{provider}/link/callback")
async def api_social_link_callback(provider: str, request: Request):
    """Handle link callback — associate provider email with existing NOBA user."""
    cfg = read_yaml_settings()
    prov = _resolve_provider(cfg, provider)
    if not prov:
        raise HTTPException(400, f"Provider '{provider}' not configured")
    code = request.query_params.get("code", "")
    state = request.query_params.get("state", "")  # NOBA auth token
    if not code or not state:
        raise HTTPException(400, "Missing code or state")
    # Verify the NOBA token to find who's linking
    noba_user = token_store.validate(state)
    if not noba_user:
        raise HTTPException(401, "Invalid or expired token — please log in again")
    noba_username = noba_user[0]
    redirect_uri = str(request.url_for("api_social_link_callback", provider=provider))
    import httpx as _httpx
    try:
        r = _httpx.post(prov["token_url"], data={
            "grant_type": "authorization_code",
            "code": code,
            "redirect_uri": redirect_uri,
            "client_id": prov["client_id"],
            "client_secret": prov["client_secret"],
        }, headers={"Accept": "application/json"}, timeout=10)
        r.raise_for_status()
        token_data = r.json()
        access_token = token_data.get("access_token", "")
        userinfo = _httpx.get(
            prov["userinfo_url"],
            headers={"Authorization": f"Bearer {access_token}"},
            timeout=5,
        ).json()
        provider_email = (
            userinfo.get("email") or userinfo.get("mail")
            or userinfo.get("login") or ""
        )
        if not provider_email:
            raise HTTPException(400, "Could not get email from provider")
        # Store the link
        with _linked_lock:
            if noba_username not in _linked_providers:
                _linked_providers[noba_username] = {}
            _linked_providers[noba_username][provider] = {
                "email": provider_email,
                "linked_at": time.time(),
                "name": prov["name"],
            }
        db.audit_log("social_link", noba_username,
                     f"Linked {prov['name']} ({provider_email})", _client_ip(request))
        logger.info("User %s linked %s account (%s)", noba_username, provider, provider_email)
        return RedirectResponse("/#/settings/auth?linked=true")
    except HTTPException:
        raise
    except Exception as e:
        logger.error("Social link error (%s): %s", provider, e)
        raise HTTPException(502, f"Failed to link {prov['name']} account")


@router.get("/api/auth/linked-providers")
def api_linked_providers(auth=Depends(_get_auth)):
    """List providers linked to the current user's account."""
    username, _ = auth
    with _linked_lock:
        linked = _linked_providers.get(username, {})
    return {
        provider: {"email": info["email"], "name": info["name"], "linked_at": info["linked_at"]}
        for provider, info in linked.items()
    }


@router.delete("/api/auth/linked-providers/{provider}")
def api_unlink_provider(provider: str, auth=Depends(_get_auth)):
    """Unlink a social provider from the current account."""
    username, _ = auth
    with _linked_lock:
        linked = _linked_providers.get(username, {})
        if provider not in linked:
            raise HTTPException(404, f"Provider '{provider}' not linked")
        del linked[provider]
    db.audit_log("social_unlink", username, f"Unlinked {provider}", "")
    return {"status": "unlinked", "provider": provider}


# ── Generic OIDC routes (backward compatible) ────────────────────────────────
@router.get("/api/auth/oidc/login")
async def api_oidc_login(request: Request):
    """Redirect to OIDC provider for authentication."""
    cfg = read_yaml_settings()
    prov = _resolve_provider(cfg)
    if not prov:
        raise HTTPException(400, "OIDC not configured")
    import urllib.parse
    redirect_uri = str(request.url_for("api_oidc_callback"))
    params = urllib.parse.urlencode({
        "client_id": prov["client_id"],
        "response_type": "code",
        "scope": prov["scope"],
        "redirect_uri": redirect_uri,
    })
    return RedirectResponse(f"{prov['authorize_url']}?{params}")


@router.get("/api/auth/oidc/callback")
async def api_oidc_callback(request: Request):
    """Handle OIDC callback -- exchange code for token, create session."""
    cfg = read_yaml_settings()
    prov = _resolve_provider(cfg)
    if not prov:
        raise HTTPException(400, "OIDC not configured")
    code = request.query_params.get("code", "")
    if not code:
        raise HTTPException(400, "Missing authorization code")
    redirect_uri = str(request.url_for("api_oidc_callback"))
    import httpx as _httpx
    try:
        r = _httpx.post(prov["token_url"], data={
            "grant_type": "authorization_code",
            "code": code,
            "redirect_uri": redirect_uri,
            "client_id": prov["client_id"],
            "client_secret": prov["client_secret"],
        }, timeout=10)
        r.raise_for_status()
        token_data = r.json()
        access_token = token_data.get("access_token", "")
        userinfo = _httpx.get(
            prov["userinfo_url"],
            headers={"Authorization": f"Bearer {access_token}"},
            timeout=5,
        ).json()
        email = userinfo.get("email", userinfo.get("preferred_username", ""))
        if not email:
            raise HTTPException(400, "Could not determine user identity from OIDC")
        if not users.exists(email):
            users.add(email, "!oidc:disabled", "viewer")
        user_role = users.role(email)
        noba_token = token_store.generate(email, user_role)
        db.audit_log("oidc_login", email, "OIDC login", _client_ip(request))
        oidc_code = secrets.token_urlsafe(32)
        with _oidc_codes_lock:
            now = time.time()
            expired = [k for k, (_, exp) in _oidc_codes.items() if now > exp]
            for k in expired:
                del _oidc_codes[k]
            _oidc_codes[oidc_code] = (noba_token, now + 60)
        return RedirectResponse(f"/#oidc_code={oidc_code}")
    except HTTPException:
        raise
    except Exception as e:
        logger.error("OIDC callback error: %s", e)
        raise HTTPException(502, "OIDC authentication failed")


@router.post("/api/auth/oidc/exchange")
async def api_oidc_exchange(request: Request):
    """Exchange a one-time OIDC code for a NOBA auth token."""
    body = await _read_body(request)
    code = body.get("code", "")
    if not code:
        raise HTTPException(400, "Missing code")
    with _oidc_codes_lock:
        entry = _oidc_codes.pop(code, None)
    if not entry:
        raise HTTPException(401, "Invalid or expired code")
    noba_token, expiry = entry
    if time.time() > expiry:
        raise HTTPException(401, "Code expired")
    return {"token": noba_token}


# ── /api/profile ──────────────────────────────────────────────────────────────
@router.get("/api/profile")
def api_profile(auth=Depends(_get_auth)):
    """Get current user's profile with activity summary."""
    username, role = auth
    from ..auth import get_permissions, users as _users  # noqa: PLC0415
    has_2fa = _users.has_totp(username)
    logins = db.get_audit(limit=10, username_filter=username, action_filter="login")
    failed = db.get_audit(limit=5, username_filter=username, action_filter="login_failed")
    actions = db.get_audit(limit=20, username_filter=username)
    return {
        "username": username,
        "role": role,
        "permissions": get_permissions(role),
        "has_2fa": has_2fa,
        "recent_logins": logins,
        "failed_logins": failed,
        "recent_actions": actions[:20],
    }


@router.post("/api/profile/password")
async def api_profile_password(request: Request, auth=Depends(_get_auth)):
    """Change own password (any authenticated user)."""
    username, _ = auth
    body = await _read_body(request)
    current = body.get("current", "")
    new_pw = body.get("new", "")
    user_data = users.get(username)
    if not user_data or not verify_password(user_data[0], current):
        raise HTTPException(401, "Current password is incorrect")
    pw_err = check_password_strength(new_pw)
    if pw_err:
        raise HTTPException(400, pw_err)
    if not users.update_password(username, pbkdf2_hash(new_pw)):
        raise HTTPException(500, "Failed to update password")
    db.audit_log("password_change_self", username, "Changed own password", _client_ip(request))
    return {"status": "ok"}


@router.get("/api/profile/sessions")
def api_profile_sessions(auth=Depends(_get_auth)):
    """Get active sessions for the current user."""
    username, _ = auth
    all_sessions = token_store.list_sessions()
    return [s for s in all_sessions if s.get("username") == username]


# ── /api/user/preferences (Feature 10: Multi-user Dashboard Views) ───────────
@router.get("/api/user/preferences")
def api_user_preferences_get(auth=Depends(_get_auth)):
    """Get current user's dashboard preferences."""
    username, _ = auth
    result = db.get_user_preferences(username)
    if not result:
        return {"preferences": {}, "synced": False}
    return {"preferences": result["preferences"], "updated_at": result["updated_at"], "synced": True}


@router.put("/api/user/preferences")
async def api_user_preferences_put(request: Request, auth=Depends(_get_auth)):
    """Save current user's dashboard preferences."""
    username, _ = auth
    body = await _read_body(request)
    prefs = body.get("preferences")
    if prefs is None or not isinstance(prefs, dict):
        raise HTTPException(400, "Missing or invalid 'preferences' object")
    # Limit preferences size to prevent abuse (64 KB should be plenty)
    import json as _json
    if len(_json.dumps(prefs)) > 65536:
        raise HTTPException(413, "Preferences too large")
    ok = db.save_user_preferences(username, prefs)
    if not ok:
        raise HTTPException(500, "Failed to save preferences")
    return {"status": "ok"}


@router.delete("/api/user/preferences")
def api_user_preferences_delete(auth=Depends(_get_auth)):
    """Reset current user's preferences to defaults."""
    username, _ = auth
    db.delete_user_preferences(username)
    return {"status": "ok"}


# ── /api/admin/users ──────────────────────────────────────────────────────────
@router.get("/api/admin/users")
def api_users_get(auth=Depends(_require_admin)):
    return users.list_users()


@router.post("/api/admin/users")
async def api_users_post(request: Request, auth=Depends(_require_admin)):
    username, _ = auth
    ip   = _client_ip(request)
    body = await _read_body(request)
    action = body.get("action")

    if action == "add":
        new_u  = body.get("username", "").strip()
        pw     = body.get("password", "")
        role   = body.get("role", VALID_ROLES[0])
        if not new_u or not pw:
            raise HTTPException(400, "Missing username or password")
        if not valid_username(new_u) or role not in VALID_ROLES:
            raise HTTPException(400, "Invalid username or role")
        pw_err = check_password_strength(pw)
        if pw_err:
            raise HTTPException(400, pw_err)
        if users.exists(new_u):
            raise HTTPException(409, "User already exists")
        users.add(new_u, pbkdf2_hash(pw), role)
        db.audit_log("user_add", username, f"Added {new_u} with role {role}", ip)
        return {"status": "ok"}

    if action == "remove":
        target = body.get("username", "").strip()
        if not users.remove(target):
            raise HTTPException(404, "User not found")
        db.audit_log("user_remove", username, f"Removed {target}", ip)
        return {"status": "ok"}

    if action == "change_password":
        target = body.get("username", "").strip()
        pw     = body.get("password", "")
        pw_err = check_password_strength(pw)
        if pw_err:
            raise HTTPException(400, pw_err)
        if not users.update_password(target, pbkdf2_hash(pw)):
            raise HTTPException(404, "User not found")
        db.audit_log("user_password_change", username, f"Changed password for {target}", ip)
        return {"status": "ok"}

    if action == "list":
        return users.list_users()

    raise HTTPException(400, "Invalid action")


# ── /api/admin/sessions ──────────────────────────────────────────────────────
@router.get("/api/admin/sessions")
def api_sessions_list(auth=Depends(_require_admin)):
    return token_store.list_sessions()


@router.post("/api/admin/sessions/revoke")
async def api_sessions_revoke(request: Request, auth=Depends(_require_admin)):
    username, _ = auth
    body = await _read_body(request)
    prefix = body.get("prefix", "").replace("\u2026", "")
    if not prefix or len(prefix) < 8:
        raise HTTPException(400, "Invalid token prefix")
    ok = token_store.revoke_by_prefix(prefix)
    if ok:
        db.audit_log("session_revoke", username, f"Revoked session {prefix}\u2026", _client_ip(request))
    return {"success": ok}


# ── /api/admin/api-keys ──────────────────────────────────────────────────────
@router.get("/api/admin/api-keys")
def api_keys_list(auth=Depends(_require_admin)):
    return db.list_api_keys()


@router.post("/api/admin/api-keys")
async def api_keys_create(request: Request, auth=Depends(_require_admin)):
    import hashlib
    username, _ = auth
    body = await _read_body(request)
    name = body.get("name", "").strip()
    role = body.get("role", "viewer")
    if not name:
        raise HTTPException(400, "Name is required")
    if role not in VALID_ROLES:
        raise HTTPException(400, "Invalid role")
    raw_key = secrets.token_urlsafe(32)
    key_hash = hashlib.sha256(raw_key.encode()).hexdigest()
    key_id = secrets.token_hex(6)
    expires_days = body.get("expires_days")
    expires_at = int(time.time()) + int(expires_days) * 86400 if expires_days else None
    db.insert_api_key(key_id, name, key_hash, role, expires_at)
    db.audit_log("api_key_create", username, f"Created key '{name}'", _client_ip(request))
    return {"id": key_id, "key": raw_key, "name": name, "role": role}


@router.delete("/api/admin/api-keys/{key_id}")
def api_keys_delete(key_id: str, request: Request, auth=Depends(_require_admin)):
    username, _ = auth
    if not db.delete_api_key(key_id):
        raise HTTPException(404, "Key not found")
    db.audit_log("api_key_delete", username, f"Deleted key {key_id}", _client_ip(request))
    return {"status": "ok"}


# ── /api/admin/ssh-keys ──────────────────────────────────────────────────────
@router.get("/api/admin/ssh-keys")
def api_ssh_keys_list(auth=Depends(_require_admin)):
    """List authorized SSH keys."""
    import pathlib
    ak_path = pathlib.Path.home() / ".ssh" / "authorized_keys"
    if not ak_path.exists():
        return []
    keys = []
    for i, line in enumerate(ak_path.read_text().splitlines()):
        line = line.strip()
        if not line or line.startswith("#"):
            continue
        parts = line.split(None, 2)
        keys.append({
            "id": i,
            "type": parts[0] if parts else "",
            "comment": parts[2] if len(parts) > 2 else "",
            "fingerprint": parts[1][:20] + "..." if len(parts) > 1 else "",
        })
    return keys


@router.post("/api/admin/ssh-keys")
async def api_ssh_keys_add(request: Request, auth=Depends(_require_admin)):
    """Add a new SSH authorized key."""
    import pathlib
    username, _ = auth
    body = await _read_body(request)
    key = body.get("key", "").strip()
    if not key or not key.startswith(("ssh-", "ecdsa-", "sk-")):
        raise HTTPException(400, "Invalid SSH public key")
    ak_path = pathlib.Path.home() / ".ssh" / "authorized_keys"
    ak_path.parent.mkdir(mode=0o700, exist_ok=True)
    with open(ak_path, "a") as f:
        f.write(key + "\n")
    ak_path.chmod(0o600)
    db.audit_log("ssh_key_add", username, f"Added SSH key: {key[:30]}...", _client_ip(request))
    return {"status": "ok"}


@router.delete("/api/admin/ssh-keys/{key_id}")
def api_ssh_keys_delete(key_id: int, request: Request, auth=Depends(_require_admin)):
    """Remove an SSH authorized key by line index."""
    import pathlib
    username, _ = auth
    ak_path = pathlib.Path.home() / ".ssh" / "authorized_keys"
    if not ak_path.exists():
        raise HTTPException(404, "No authorized_keys file")
    lines = ak_path.read_text().splitlines()
    real_idx = 0
    new_lines = []
    removed = False
    for line in lines:
        stripped = line.strip()
        if not stripped or stripped.startswith("#"):
            new_lines.append(line)
            continue
        if real_idx == key_id:
            removed = True
            real_idx += 1
            continue
        new_lines.append(line)
        real_idx += 1
    if not removed:
        raise HTTPException(404, "Key not found")
    ak_path.write_text("\n".join(new_lines) + "\n")
    db.audit_log("ssh_key_remove", username, f"Removed SSH key index {key_id}", _client_ip(request))
    return {"status": "ok"}
