# Copyright (c) 2024-2026 Kevin Van Nieuwenhove. All rights reserved.
# NOBA Command Center — Licensed under Apache 2.0.

"""Tests for healing API router."""
from __future__ import annotations


class TestHealingLedger:
    """GET /api/healing/ledger -- any authenticated user."""

    def test_no_auth_returns_401(self, client):
        resp = client.get("/api/healing/ledger")
        assert resp.status_code == 401

    def test_viewer_can_access(self, client, viewer_headers):
        resp = client.get("/api/healing/ledger", headers=viewer_headers)
        assert resp.status_code == 200
        assert isinstance(resp.json(), list)

    def test_admin_can_access(self, client, admin_headers):
        resp = client.get("/api/healing/ledger", headers=admin_headers)
        assert resp.status_code == 200
        assert isinstance(resp.json(), list)


class TestHealingTrust:
    """GET /api/healing/trust -- any authenticated user."""

    def test_no_auth_returns_401(self, client):
        resp = client.get("/api/healing/trust")
        assert resp.status_code == 401

    def test_viewer_can_access(self, client, viewer_headers):
        resp = client.get("/api/healing/trust", headers=viewer_headers)
        assert resp.status_code == 200
        assert isinstance(resp.json(), list)

    def test_admin_can_access(self, client, admin_headers):
        resp = client.get("/api/healing/trust", headers=admin_headers)
        assert resp.status_code == 200
        assert isinstance(resp.json(), list)


class TestHealingSuggestions:
    """GET /api/healing/suggestions -- any authenticated user."""

    def test_no_auth_returns_401(self, client):
        resp = client.get("/api/healing/suggestions")
        assert resp.status_code == 401

    def test_viewer_can_access(self, client, viewer_headers):
        resp = client.get("/api/healing/suggestions", headers=viewer_headers)
        assert resp.status_code == 200
        assert isinstance(resp.json(), list)

    def test_admin_can_access(self, client, admin_headers):
        resp = client.get("/api/healing/suggestions", headers=admin_headers)
        assert resp.status_code == 200
        assert isinstance(resp.json(), list)
