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


# ── OIDC routes ──────────────────────────────────────────────────────────────
@router.get("/api/auth/oidc/login")
async def api_oidc_login(request: Request):
    """Redirect to OIDC provider for authentication."""
    cfg = read_yaml_settings()
    provider = cfg.get("oidcProviderUrl", "")
    client_id = cfg.get("oidcClientId", "")
    if not provider or not client_id:
        raise HTTPException(400, "OIDC not configured")
    import urllib.parse
    redirect_uri = str(request.url_for("api_oidc_callback"))
    params = urllib.parse.urlencode({
        "client_id": client_id,
        "response_type": "code",
        "scope": "openid email profile",
        "redirect_uri": redirect_uri,
    })
    return RedirectResponse(f"{provider.rstrip('/')}/authorize?{params}")


@router.get("/api/auth/oidc/callback")
async def api_oidc_callback(request: Request):
    """Handle OIDC callback -- exchange code for token, create session."""
    cfg = read_yaml_settings()
    provider = cfg.get("oidcProviderUrl", "")
    client_id = cfg.get("oidcClientId", "")
    client_secret = cfg.get("oidcClientSecret", "")
    code = request.query_params.get("code", "")
    if not code:
        raise HTTPException(400, "Missing authorization code")
    redirect_uri = str(request.url_for("api_oidc_callback"))
    # Exchange code for token
    import httpx as _httpx
    try:
        r = _httpx.post(f"{provider.rstrip('/')}/token", data={
            "grant_type": "authorization_code",
            "code": code,
            "redirect_uri": redirect_uri,
            "client_id": client_id,
            "client_secret": client_secret,
        }, timeout=10)
        r.raise_for_status()
        token_data = r.json()
        # Get user info
        access_token = token_data.get("access_token", "")
        userinfo = _httpx.get(
            f"{provider.rstrip('/')}/userinfo",
            headers={"Authorization": f"Bearer {access_token}"},
            timeout=5,
        ).json()
        email = userinfo.get("email", userinfo.get("preferred_username", ""))
        if not email:
            raise HTTPException(400, "Could not determine user identity from OIDC")
        # Create or find user, issue NOBA token
        if not users.exists(email):
            users.add(email, "oidc:external", "viewer")
        noba_token = token_store.generate(email, "viewer")
        db.audit_log("oidc_login", email, "OIDC login", _client_ip(request))
        # Redirect to frontend with token in fragment (not logged by servers)
        return RedirectResponse(f"/#token={noba_token}")
    except HTTPException:
        raise
    except Exception as e:
        logger.error("OIDC callback error: %s", e)
        raise HTTPException(502, "OIDC authentication failed")


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
