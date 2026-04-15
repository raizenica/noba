# Copyright (c) 2024-2026 Kevin Van Nieuwenhove. All rights reserved.
# NOBA Command Center — Licensed under Apache 2.0.

"""Tests for integration instance management API."""
from __future__ import annotations


class TestIntegrationInstanceAPI:
    def test_list_instances_no_auth(self, client):
        r = client.get("/api/integrations/instances")
        assert r.status_code == 401

    def test_list_instances_empty(self, client, admin_headers):
        r = client.get("/api/integrations/instances", headers=admin_headers)
        assert r.status_code == 200
        assert isinstance(r.json(), list)

    def test_create_instance(self, client, admin_headers):
        r = client.post("/api/integrations/instances", json={
            "id": "truenas-main",
            "category": "nas",
            "platform": "truenas",
            "url": "https://truenas.local",
            "auth_config": {"token_env": "TN_TOKEN"},
            "site": "site-a",
            "tags": ["production"],
        }, headers=admin_headers)
        assert r.status_code == 200
        assert r.json()["id"] == "truenas-main"

    def test_get_instance(self, client, admin_headers):
        # Create first
        client.post("/api/integrations/instances", json={
            "id": "plex-main", "category": "media", "platform": "plex",
            "url": "http://plex.local:32400", "auth_config": {},
        }, headers=admin_headers)
        r = client.get("/api/integrations/instances/plex-main", headers=admin_headers)
        assert r.status_code == 200
        assert r.json()["platform"] == "plex"

    def test_get_nonexistent_returns_404(self, client, admin_headers):
        r = client.get("/api/integrations/instances/nonexistent", headers=admin_headers)
        assert r.status_code == 404

    def test_delete_instance(self, client, admin_headers):
        client.post("/api/integrations/instances", json={
            "id": "del-test", "category": "dns", "platform": "pihole",
            "url": "http://pihole.local", "auth_config": {},
        }, headers=admin_headers)
        r = client.delete("/api/integrations/instances/del-test", headers=admin_headers)
        assert r.status_code == 200
        r2 = client.get("/api/integrations/instances/del-test", headers=admin_headers)
        assert r2.status_code == 404

    def test_list_by_category(self, client, admin_headers):
        client.post("/api/integrations/instances", json={
            "id": "nas1", "category": "nas", "platform": "truenas",
            "url": "http://nas1", "auth_config": {},
        }, headers=admin_headers)
        client.post("/api/integrations/instances", json={
            "id": "dns1", "category": "dns", "platform": "pihole",
            "url": "http://dns1", "auth_config": {},
        }, headers=admin_headers)
        r = client.get("/api/integrations/instances?category=nas", headers=admin_headers)
        assert r.status_code == 200
        data = r.json()
        assert all(d["category"] == "nas" for d in data)

    def test_update_instance(self, client, admin_headers):
        client.post("/api/integrations/instances", json={
            "id": "upd-test", "category": "media", "platform": "plex",
            "url": "http://old-url", "auth_config": {},
        }, headers=admin_headers)
        r = client.patch("/api/integrations/instances/upd-test", json={
            "url": "http://new-url",
        }, headers=admin_headers)
        assert r.status_code == 200
        r2 = client.get("/api/integrations/instances/upd-test", headers=admin_headers)
        assert r2.json()["url"] == "http://new-url"

    def test_create_requires_auth(self, client):
        r = client.post("/api/integrations/instances", json={
            "id": "test", "category": "nas", "platform": "truenas",
            "url": "http://test", "auth_config": {},
        })
        assert r.status_code == 401

    def test_test_connection(self, client, admin_headers):
        # Test connection endpoint (will likely fail since URL isn't real,
        # but the endpoint should exist and return a structured response)
        r = client.post("/api/integrations/instances/test-connection", json={
            "platform": "truenas",
            "url": "http://nonexistent.local",
            "auth_config": {},
        }, headers=admin_headers)
        assert r.status_code == 200
        data = r.json()
        assert "success" in data


class TestIntegrationCatalog:
    def test_list_categories(self, client, admin_headers):
        r = client.get("/api/integrations/catalog/categories", headers=admin_headers)
        assert r.status_code == 200
        data = r.json()
        assert isinstance(data, list)
        assert len(data) >= 20

    def test_list_platforms_for_category(self, client, admin_headers):
        r = client.get("/api/integrations/catalog/categories/nas/platforms", headers=admin_headers)
        assert r.status_code == 200
        data = r.json()
        assert isinstance(data, list)
        assert "truenas" in data


class TestIntegrationGroups:
    def test_list_groups(self, client, admin_headers):
        r = client.get("/api/integrations/groups", headers=admin_headers)
        assert r.status_code == 200
        assert isinstance(r.json(), list)

    def test_create_group_member(self, client, admin_headers):
        # Create instance first
        client.post("/api/integrations/instances", json={
            "id": "grp-ph1", "category": "dns", "platform": "pihole",
            "url": "http://ph1", "auth_config": {},
        }, headers=admin_headers)
        r = client.post("/api/integrations/groups/all-pihole/members", json={
            "instance_id": "grp-ph1",
        }, headers=admin_headers)
        assert r.status_code == 200

    def test_list_group_members(self, client, admin_headers):
        r = client.get("/api/integrations/groups/all-pihole/members", headers=admin_headers)
        assert r.status_code == 200
