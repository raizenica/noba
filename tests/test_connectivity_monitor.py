# Copyright (c) 2024-2026 Kevin Van Nieuwenhove. All rights reserved.
# NOBA Command Center — Licensed under Apache 2.0.

"""Tests for healing.connectivity_monitor: site reachability tracking."""
from __future__ import annotations


class TestConnectivityMonitor:
    def _make_monitor(self):
        from server.healing.connectivity_monitor import ConnectivityMonitor
        return ConnectivityMonitor()

    def test_site_starts_as_ok(self):
        mon = self._make_monitor()
        assert not mon.is_suspect("site-a")

    def test_mark_suspect(self):
        mon = self._make_monitor()
        mon.mark_suspect("site-a", reason="agent unreachable")
        assert mon.is_suspect("site-a")

    def test_clear_suspect(self):
        mon = self._make_monitor()
        mon.mark_suspect("site-a", reason="test")
        mon.clear_suspect("site-a")
        assert not mon.is_suspect("site-a")

    def test_get_suspect_sites(self):
        mon = self._make_monitor()
        mon.mark_suspect("site-a", reason="test")
        mon.mark_suspect("site-b", reason="test")
        suspects = mon.get_suspect_sites()
        assert "site-a" in suspects
        assert "site-b" in suspects

    def test_suspect_info_has_reason_and_timestamp(self):
        mon = self._make_monitor()
        mon.mark_suspect("site-a", reason="ISP down")
        info = mon.get_suspect_info("site-a")
        assert info is not None
        assert info["reason"] == "ISP down"
        assert "since" in info

    def test_should_suppress_healing_for_suspect_site(self):
        mon = self._make_monitor()
        mon.mark_suspect("site-a", reason="test")
        assert mon.should_suppress_healing("site-a")
        assert not mon.should_suppress_healing("site-b")

    def test_agent_reconnect_clears_suspect(self):
        mon = self._make_monitor()
        mon.mark_suspect("site-a", reason="test")
        mon.on_agent_reconnect("site-a")
        assert not mon.is_suspect("site-a")

    def test_clear_nonexistent_is_noop(self):
        mon = self._make_monitor()
        mon.clear_suspect("site-z")  # should not raise
        assert not mon.is_suspect("site-z")

    def test_double_mark_updates_reason(self):
        mon = self._make_monitor()
        mon.mark_suspect("site-a", reason="first")
        mon.mark_suspect("site-a", reason="second")
        info = mon.get_suspect_info("site-a")
        assert info["reason"] == "second"
