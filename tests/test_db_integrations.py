# Copyright (c) 2024-2026 Kevin Van Nieuwenhove. All rights reserved.
# NOBA Command Center — Licensed under Apache 2.0.

"""Tests for db.integrations: integration_instances, groups, capabilities."""
from __future__ import annotations

import sqlite3
import threading

import pytest


@pytest.fixture()
def db():
    conn = sqlite3.connect(":memory:")
    conn.row_factory = sqlite3.Row
    lock = threading.Lock()
    from server.db.integrations import create_tables
    create_tables(conn)
    return conn, lock


class TestIntegrationInstances:
    def test_insert_and_get(self, db):
        from server.db.integrations import insert_instance, get_instance
        conn, lock = db
        insert_instance(conn, lock, id="truenas-main", category="nas",
                       platform="truenas", url="https://truenas.local",
                       auth_config='{"token_env":"TN_TOKEN"}', site="site-a",
                       tags='["production"]')
        inst = get_instance(conn, lock, "truenas-main")
        assert inst is not None
        assert inst["platform"] == "truenas"
        assert inst["site"] == "site-a"

    def test_list_by_category(self, db):
        from server.db.integrations import insert_instance, list_instances
        conn, lock = db
        insert_instance(conn, lock, id="tn1", category="nas", platform="truenas",
                       url="https://tn1", auth_config='{}')
        insert_instance(conn, lock, id="syn1", category="nas", platform="synology",
                       url="https://syn1", auth_config='{}')
        insert_instance(conn, lock, id="pve1", category="hypervisor", platform="proxmox",
                       url="https://pve1", auth_config='{}')
        nas = list_instances(conn, lock, category="nas")
        assert len(nas) == 2
        all_inst = list_instances(conn, lock)
        assert len(all_inst) == 3

    def test_list_by_site(self, db):
        from server.db.integrations import insert_instance, list_instances
        conn, lock = db
        insert_instance(conn, lock, id="tn1", category="nas", platform="truenas",
                       url="https://tn1", auth_config='{}', site="site-a")
        insert_instance(conn, lock, id="tn2", category="nas", platform="truenas",
                       url="https://tn2", auth_config='{}', site="site-b")
        result = list_instances(conn, lock, site="site-a")
        assert len(result) == 1
        assert result[0]["id"] == "tn1"

    def test_update_health_status(self, db):
        from server.db.integrations import insert_instance, update_health, get_instance
        conn, lock = db
        insert_instance(conn, lock, id="tn1", category="nas", platform="truenas",
                       url="https://tn1", auth_config='{}')
        update_health(conn, lock, "tn1", "online")
        inst = get_instance(conn, lock, "tn1")
        assert inst["health_status"] == "online"

    def test_delete_instance(self, db):
        from server.db.integrations import insert_instance, delete_instance, get_instance
        conn, lock = db
        insert_instance(conn, lock, id="tn1", category="nas", platform="truenas",
                       url="https://tn1", auth_config='{}')
        delete_instance(conn, lock, "tn1")
        assert get_instance(conn, lock, "tn1") is None


class TestIntegrationGroups:
    def test_add_to_group_and_list(self, db):
        from server.db.integrations import insert_instance, add_to_group, list_group
        conn, lock = db
        insert_instance(conn, lock, id="ph1", category="dns", platform="pihole",
                       url="http://ph1", auth_config='{}')
        insert_instance(conn, lock, id="ph2", category="dns", platform="pihole",
                       url="http://ph2", auth_config='{}')
        add_to_group(conn, lock, "all-pihole", "ph1")
        add_to_group(conn, lock, "all-pihole", "ph2")
        members = list_group(conn, lock, "all-pihole")
        assert len(members) == 2

    def test_remove_from_group(self, db):
        from server.db.integrations import insert_instance, add_to_group, remove_from_group, list_group
        conn, lock = db
        insert_instance(conn, lock, id="ph1", category="dns", platform="pihole",
                       url="http://ph1", auth_config='{}')
        add_to_group(conn, lock, "all-pihole", "ph1")
        remove_from_group(conn, lock, "all-pihole", "ph1")
        members = list_group(conn, lock, "all-pihole")
        assert len(members) == 0

    def test_list_all_groups(self, db):
        from server.db.integrations import insert_instance, add_to_group, list_groups
        conn, lock = db
        insert_instance(conn, lock, id="ph1", category="dns", platform="pihole",
                       url="http://ph1", auth_config='{}')
        insert_instance(conn, lock, id="tn1", category="nas", platform="truenas",
                       url="http://tn1", auth_config='{}')
        add_to_group(conn, lock, "all-pihole", "ph1")
        add_to_group(conn, lock, "all-nas", "tn1")
        groups = list_groups(conn, lock)
        assert set(groups) == {"all-pihole", "all-nas"}


class TestCapabilityManifests:
    def test_upsert_and_get(self, db):
        from server.db.integrations import upsert_manifest, get_manifest
        conn, lock = db
        upsert_manifest(conn, lock, hostname="host1",
                       manifest='{"os":"linux","capabilities":{}}')
        m = get_manifest(conn, lock, "host1")
        assert m is not None
        assert '"os"' in m["manifest"]

    def test_upsert_updates_existing(self, db):
        from server.db.integrations import upsert_manifest, get_manifest
        conn, lock = db
        upsert_manifest(conn, lock, hostname="host1", manifest='{"v":1}')
        upsert_manifest(conn, lock, hostname="host1", manifest='{"v":2}')
        m = get_manifest(conn, lock, "host1")
        assert '"v": 2' in m["manifest"] or '"v":2' in m["manifest"]

    def test_mark_degraded(self, db):
        from server.db.integrations import upsert_manifest, mark_capability_degraded, get_manifest
        conn, lock = db
        upsert_manifest(conn, lock, hostname="host1", manifest='{}')
        mark_capability_degraded(conn, lock, "host1", "docker")
        m = get_manifest(conn, lock, "host1")
        assert "docker" in m["degraded_capabilities"]
