# Copyright (c) 2024-2026 Kevin Van Nieuwenhove. All rights reserved.
# NOBA Command Center — Licensed under Apache 2.0.

"""Tests for GET /api/auth/capabilities and POST /api/auth/exchange."""
from __future__ import annotations

import time


def test_capabilities_returns_local(client):
    r = client.get("/api/auth/capabilities")
    assert r.status_code == 200
    data = r.json()
    assert "methods" in data
    types = [m["type"] for m in data["methods"]]
    assert "local" in types


def test_capabilities_local_has_display_name(client):
    r = client.get("/api/auth/capabilities")
    data = r.json()
    local = next(m for m in data["methods"] if m["type"] == "local")
    assert "display_name" in local
    assert local["display_name"]


def test_exchange_rejects_missing_code(client):
    r = client.post("/api/auth/exchange", json={})
    assert r.status_code == 400


def test_exchange_rejects_invalid_code(client):
    r = client.post("/api/auth/exchange", json={"code": "notarealcode"})
    assert r.status_code == 401


def test_exchange_redeems_valid_code(client):
    from server.routers.auth import (
        _saml_exchange_codes,
        _saml_exchange_codes_lock,
    )
    code = "testvalidcode_task3"
    with _saml_exchange_codes_lock:
        _saml_exchange_codes[code] = ("mytoken123", time.time() + 30)
    r = client.post("/api/auth/exchange", json={"code": code})
    assert r.status_code == 200
    assert r.json()["token"] == "mytoken123"


def test_exchange_code_single_use(client):
    from server.routers.auth import (
        _saml_exchange_codes,
        _saml_exchange_codes_lock,
    )
    code = "testsingleuse_task3"
    with _saml_exchange_codes_lock:
        _saml_exchange_codes[code] = ("tok", time.time() + 30)
    client.post("/api/auth/exchange", json={"code": code})
    r2 = client.post("/api/auth/exchange", json={"code": code})
    assert r2.status_code == 401


def test_exchange_rejects_expired_code(client):
    from server.routers.auth import (
        _saml_exchange_codes,
        _saml_exchange_codes_lock,
    )
    code = "testexpired_task3"
    with _saml_exchange_codes_lock:
        _saml_exchange_codes[code] = ("sometoken", time.time() - 1)
    r = client.post("/api/auth/exchange", json={"code": code})
    assert r.status_code == 401
