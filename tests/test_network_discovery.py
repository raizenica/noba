# Copyright (c) 2024-2026 Kevin Van Nieuwenhove. All rights reserved.
# NOBA Command Center — Licensed under Apache 2.0.

"""Tests for the network auto-discovery feature -- DB CRUD."""
from __future__ import annotations

import os
import tempfile

from server.db.core import Database


def _make_db():
    """Create a fresh temp DB for each test."""
    fd, path = tempfile.mkstemp(suffix=".db", prefix="noba_test_")
    os.close(fd)
    return Database(path=path), path


def _cleanup(path):
    for ext in ("", "-wal", "-shm"):
        try:
            os.unlink(path + ext)
        except OSError:
            pass


class TestNetworkDeviceUpsert:
    def setup_method(self):
        self.db, self.tmp = _make_db()

    def teardown_method(self):
        _cleanup(self.tmp)

    def test_insert_new_device(self):
        dev_id = self.db.upsert_network_device(
            ip="192.168.1.10",
            mac="aa:bb:cc:dd:ee:ff",
            hostname="router",
            open_ports=[22, 80, 443],
            discovered_by="agent-1",
        )
        assert dev_id is not None
        assert dev_id > 0

    def test_upsert_updates_existing(self):
        id1 = self.db.upsert_network_device(
            ip="192.168.1.10", mac="aa:bb:cc:dd:ee:ff",
            hostname="router", open_ports=[22],
        )
        id2 = self.db.upsert_network_device(
            ip="192.168.1.10", mac="aa:bb:cc:dd:ee:ff",
            hostname="router-updated", open_ports=[22, 80, 443],
        )
        assert id1 == id2
        devices = self.db.list_network_devices()
        assert len(devices) == 1
        assert devices[0]["hostname"] == "router-updated"
        assert 443 in devices[0]["open_ports"]

    def test_different_mac_creates_new_device(self):
        self.db.upsert_network_device(
            ip="192.168.1.10", mac="aa:bb:cc:dd:ee:ff",
        )
        self.db.upsert_network_device(
            ip="192.168.1.10", mac="11:22:33:44:55:66",
        )
        devices = self.db.list_network_devices()
        assert len(devices) == 2

    def test_upsert_preserves_hostname_on_null(self):
        """When hostname is None on update, the existing value is kept."""
        self.db.upsert_network_device(
            ip="10.0.0.1", mac="aa:bb:cc:dd:ee:ff",
            hostname="myhost",
        )
        self.db.upsert_network_device(
            ip="10.0.0.1", mac="aa:bb:cc:dd:ee:ff",
            hostname=None, open_ports=[80],
        )
        devices = self.db.list_network_devices()
        assert devices[0]["hostname"] == "myhost"
        assert 80 in devices[0]["open_ports"]


class TestNetworkDeviceList:
    def setup_method(self):
        self.db, self.tmp = _make_db()

    def teardown_method(self):
        _cleanup(self.tmp)

    def test_list_empty(self):
        devices = self.db.list_network_devices()
        assert devices == []

    def test_list_multiple(self):
        self.db.upsert_network_device(ip="192.168.1.1", mac="aa:bb:cc:dd:ee:01")
        self.db.upsert_network_device(ip="192.168.1.2", mac="aa:bb:cc:dd:ee:02")
        self.db.upsert_network_device(ip="192.168.1.3", mac="aa:bb:cc:dd:ee:03")
        devices = self.db.list_network_devices()
        assert len(devices) == 3

    def test_list_returns_correct_fields(self):
        self.db.upsert_network_device(
            ip="10.0.0.5", mac="de:ad:be:ef:00:01",
            hostname="switch", vendor="Cisco",
            open_ports=[22, 443], discovered_by="agent-a",
        )
        devices = self.db.list_network_devices()
        d = devices[0]
        assert d["ip"] == "10.0.0.5"
        assert d["mac"] == "de:ad:be:ef:00:01"
        assert d["hostname"] == "switch"
        assert d["vendor"] == "Cisco"
        assert d["open_ports"] == [22, 443]
        assert d["discovered_by"] == "agent-a"
        assert d["first_seen"] > 0
        assert d["last_seen"] >= d["first_seen"]
        assert d["id"] > 0


class TestNetworkDeviceGet:
    def setup_method(self):
        self.db, self.tmp = _make_db()

    def teardown_method(self):
        _cleanup(self.tmp)

    def test_get_existing(self):
        dev_id = self.db.upsert_network_device(
            ip="192.168.1.50", mac="ff:ee:dd:cc:bb:aa",
            hostname="nas",
        )
        device = self.db.get_network_device(dev_id)
        assert device is not None
        assert device["ip"] == "192.168.1.50"
        assert device["hostname"] == "nas"

    def test_get_nonexistent(self):
        device = self.db.get_network_device(9999)
        assert device is None


class TestNetworkDeviceDelete:
    def setup_method(self):
        self.db, self.tmp = _make_db()

    def teardown_method(self):
        _cleanup(self.tmp)

    def test_delete_existing(self):
        dev_id = self.db.upsert_network_device(
            ip="192.168.1.100", mac="aa:bb:cc:dd:ee:ff",
        )
        ok = self.db.delete_network_device(dev_id)
        assert ok is True
        assert self.db.list_network_devices() == []

    def test_delete_nonexistent(self):
        ok = self.db.delete_network_device(9999)
        assert ok is False

    def test_delete_does_not_affect_others(self):
        id1 = self.db.upsert_network_device(ip="10.0.0.1", mac="01:01:01:01:01:01")
        self.db.upsert_network_device(ip="10.0.0.2", mac="02:02:02:02:02:02")
        self.db.delete_network_device(id1)
        devices = self.db.list_network_devices()
        assert len(devices) == 1
        assert devices[0]["ip"] == "10.0.0.2"


class TestNetworkDeviceOpenPorts:
    def setup_method(self):
        self.db, self.tmp = _make_db()

    def teardown_method(self):
        _cleanup(self.tmp)

    def test_empty_ports(self):
        self.db.upsert_network_device(ip="10.0.0.1", mac="aa:bb:cc:dd:ee:ff")
        devices = self.db.list_network_devices()
        assert devices[0]["open_ports"] == []

    def test_ports_stored_sorted(self):
        self.db.upsert_network_device(
            ip="10.0.0.1", mac="aa:bb:cc:dd:ee:ff",
            open_ports=[8080, 22, 443, 80],
        )
        devices = self.db.list_network_devices()
        assert devices[0]["open_ports"] == [22, 80, 443, 8080]
