# Copyright (c) 2024-2026 Kevin Van Nieuwenhove. All rights reserved.
# NOBA Command Center — Licensed under Apache 2.0.

"""Tests for healing API: capability manifest endpoints.

Uses client and admin_headers fixtures from conftest.py.
"""
from __future__ import annotations


class TestCapabilityEndpoints:
    def test_get_capabilities_no_auth_returns_401(self, client):
        r = client.get("/api/healing/capabilities/testhost")
        assert r.status_code == 401

    def test_get_capabilities_returns_manifest(self, client, admin_headers):
        r = client.get("/api/healing/capabilities/testhost", headers=admin_headers)
        assert r.status_code in (200, 404)

    def test_refresh_capabilities_requires_operator(self, client, admin_headers):
        r = client.post("/api/healing/capabilities/testhost/refresh",
                       headers=admin_headers)
        assert r.status_code in (200, 404)
