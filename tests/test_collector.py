# Copyright (c) 2024-2026 Kevin Van Nieuwenhove. All rights reserved.
# NOBA Command Center — Licensed under Apache 2.0.

"""Tests for the background stats collector module."""
from __future__ import annotations

import threading
import time
from unittest.mock import MagicMock, patch

import pytest


# ---------------------------------------------------------------------------
# Helpers
# ---------------------------------------------------------------------------

def _minimal_system():
    return {"cpuPercent": 12.5, "memPercent": 40.0, "cpuTemp": "45°C", "gpuTemp": "N/A"}


def _minimal_storage():
    return {"disks": [{"mount": "/", "percent": 55.0}]}


def _minimal_hardware():
    return {"gpuTemp": "N/A"}


def _minimal_network():
    return {"netRxRaw": 1000, "netTxRaw": 2000}


def _noop(*_a, **_kw):
    return {}


# ---------------------------------------------------------------------------
# collect_stats
# ---------------------------------------------------------------------------

class TestCollectStats:
    """Test the main collect_stats() assembly function."""

    @pytest.fixture(autouse=True)
    def _patch_all(self):
        """Patch every external dependency so no real system calls occur."""
        base = "server.collector"
        patches = {
            "collect_system": _minimal_system,
            "collect_hardware": _minimal_hardware,
            "collect_storage": _minimal_storage,
            "collect_network": _minimal_network,
            "get_cpu_percent": lambda: 12.5,
            "get_cpu_history": lambda: [10, 11, 12],
            "collect_disk_io": lambda: {"diskRead": 0, "diskWrite": 0},
            "collect_per_interface_net": lambda: {"perIfNet": {}},
            "read_yaml_settings": lambda: {},
            "build_threshold_alerts": lambda s, fn: [],
            "check_anomalies": lambda db, fn: [],
            "evaluate_alert_rules": lambda s, fn: None,
            "snapshot_top_processes": lambda: None,
        }
        self._patchers = []
        for name, replacement in patches.items():
            p = patch(f"{base}.{name}", side_effect=replacement)
            p.start()
            self._patchers.append(p)

        # Mock db
        mock_db = MagicMock()
        mock_db.insert_metrics = MagicMock()
        mock_db.rollup_to_1m = MagicMock()
        mock_db.rollup_to_1h = MagicMock()
        p_db = patch(f"{base}.db", mock_db)
        p_db.start()
        self._patchers.append(p_db)
        self._mock_db = mock_db

        # Mock plugin_manager
        pm = MagicMock()
        pm.count = 0
        p_pm = patch(f"{base}.plugin_manager", pm)
        p_pm.start()
        self._patchers.append(p_pm)

        yield

        for p in self._patchers:
            p.stop()

    def test_basic_stats_assembly(self):
        """collect_stats returns dict with expected system keys."""
        from server.collector import collect_stats
        result = collect_stats({})
        assert "timestamp" in result
        assert result["cpuPercent"] == 12.5
        assert result["memPercent"] == 40.0
        assert result["cpuHistory"] == [10, 11, 12]
        assert isinstance(result["disks"], list)

    def test_services_from_query_string(self):
        """Services listed in qs are submitted and collected."""
        from server.collector import collect_stats
        with patch("server.collector.get_service_status", return_value=("running", False)):
            result = collect_stats({"services": ["nginx,ssh"]})
        svc_names = [s["name"] for s in result["services"]]
        assert "nginx" in svc_names
        assert "ssh" in svc_names

    def test_radar_ping_results(self):
        """Radar IPs produce ping results in the output."""
        from server.collector import collect_stats
        with patch("server.collector.ping_host", return_value=("1.2.3.4", True, 5.0)):
            result = collect_stats({"radar": ["1.2.3.4"]})
        assert len(result["radar"]) == 1
        assert result["radar"][0]["status"] == "Up"
        assert result["radar"][0]["ms"] == 5.0

    def test_radar_ping_down(self):
        """Radar entries show Down when ping fails."""
        from server.collector import collect_stats
        with patch("server.collector.ping_host", return_value=("10.0.0.1", False, 0)):
            result = collect_stats({"radar": ["10.0.0.1"]})
        assert result["radar"][0]["status"] == "Down"

    def test_net_health_wan_up(self):
        """WAN health is Up when ping succeeds."""
        from server.collector import collect_stats
        with patch("server.collector.read_yaml_settings", return_value={"wanTestIp": "8.8.8.8"}):
            with patch("server.collector.ping_host", return_value=("8.8.8.8", True, 3.0)):
                result = collect_stats({})
        assert result["netHealth"]["wan"] == "Up"
        assert result["netHealth"]["configured"] is True

    def test_net_health_defaults_down(self):
        """Without WAN/LAN IPs, netHealth defaults to Down."""
        from server.collector import collect_stats
        result = collect_stats({})
        assert result["netHealth"]["wan"] == "Down"
        assert result["netHealth"]["lan"] == "Down"
        assert result["netHealth"]["configured"] is False

    def test_integration_pihole(self):
        """Pi-hole integration data is collected when configured."""
        from server.collector import collect_stats
        pihole_data = {"queries": 1000, "blocked": 50}
        with patch("server.collector.read_yaml_settings",
                   return_value={"piholeUrl": "http://pi.hole"}):
            with patch("server.collector.get_pihole", return_value=pihole_data):
                result = collect_stats({})
        assert result["pihole"] == pihole_data

    def test_integration_not_configured_returns_none(self):
        """Unconfigured integrations return None (default)."""
        from server.collector import collect_stats
        result = collect_stats({})
        assert result["pihole"] is None
        assert result["plex"] is None
        assert result["truenas"] is None

    def test_containers_always_collected(self):
        """Containers are always collected regardless of config."""
        from server.collector import collect_stats
        ct_data = [{"name": "nginx", "status": "running"}]
        with patch("server.collector.get_containers", return_value=ct_data):
            result = collect_stats({})
        assert result["containers"] == ct_data

    def test_metrics_persisted_to_db(self):
        """collect_stats calls db.insert_metrics with batch data."""
        from server.collector import collect_stats
        collect_stats({})
        assert self._mock_db.insert_metrics.called
        batch = self._mock_db.insert_metrics.call_args[0][0]
        metric_names = [m[0] for m in batch]
        assert "cpu_percent" in metric_names
        assert "mem_percent" in metric_names

    def test_cpu_temp_persisted(self):
        """CPU temp is added to the metric batch when available."""
        from server.collector import collect_stats
        collect_stats({})
        batch = self._mock_db.insert_metrics.call_args[0][0]
        metric_names = [m[0] for m in batch]
        assert "cpu_temp" in metric_names

    def test_history_insert_error_handled(self):
        """If db.insert_metrics raises, it's caught gracefully."""
        from server.collector import collect_stats
        self._mock_db.insert_metrics.side_effect = RuntimeError("DB locked")
        # Should not raise
        result = collect_stats({})
        assert "timestamp" in result

    def test_service_error_returns_error_status(self):
        """If get_service_status raises, service status is 'error'."""
        from server.collector import collect_stats
        with patch("server.collector.get_service_status", side_effect=RuntimeError("boom")):
            result = collect_stats({"services": ["broken_svc"]})
        assert result["services"][0]["status"] == "error"

    def test_alerts_populated(self):
        """Alerts key is always a list."""
        from server.collector import collect_stats
        result = collect_stats({})
        assert isinstance(result["alerts"], list)

    def test_agents_key_present(self):
        """Agent data is always included in results."""
        from server.collector import collect_stats
        result = collect_stats({})
        assert "agents" in result

    def test_vpn_always_collected(self):
        """VPN status is always collected."""
        from server.collector import collect_stats
        with patch("server.collector.get_vpn_status", return_value={"wg0": "up"}):
            result = collect_stats({})
        assert result["vpn"] == {"wg0": "up"}

    def test_docker_update_cycle_skips(self):
        """Docker update check only runs every 5th cycle."""
        import server.collector as mod
        from server.collector import collect_stats
        with mod._docker_update_lock:
            mod._docker_update_cycle = 0
        with patch("server.collector.check_docker_updates", return_value=[{"update": True}]) as mock_du:
            # Cycles 1-4 should not trigger docker update check
            for _ in range(4):
                result = collect_stats({})
                assert result["dockerUpdates"] == []
            # 5th cycle triggers it
            result = collect_stats({})
            assert mock_du.called


# ---------------------------------------------------------------------------
# BackgroundCollector
# ---------------------------------------------------------------------------

class TestBackgroundCollector:
    """Test the BackgroundCollector class."""

    def test_update_and_get_qs(self):
        """update_qs stores query string, get returns latest."""
        from server.collector import BackgroundCollector
        bc = BackgroundCollector(interval=10)
        assert bc.get() == {}
        bc.update_qs({"services": ["nginx"]})
        # qs is stored internally; get() still returns empty until loop runs
        assert bc.get() == {}

    def test_get_returns_latest(self):
        """After setting _latest directly, get returns it."""
        from server.collector import BackgroundCollector
        bc = BackgroundCollector(interval=10)
        bc._latest = {"cpuPercent": 50}
        assert bc.get() == {"cpuPercent": 50}

    def test_start_launches_thread(self):
        """start() launches a daemon thread."""
        from server.collector import BackgroundCollector, _shutdown_flag
        _shutdown_flag.set()  # prevent infinite loop
        bc = BackgroundCollector(interval=1)
        bc.start()
        time.sleep(0.1)
        _shutdown_flag.clear()  # reset for other tests


# ---------------------------------------------------------------------------
# get_shutdown_flag
# ---------------------------------------------------------------------------

class TestShutdownFlag:
    def test_returns_event(self):
        from server.collector import get_shutdown_flag
        flag = get_shutdown_flag()
        assert isinstance(flag, threading.Event)

    def test_flag_is_module_level(self):
        from server.collector import get_shutdown_flag, _shutdown_flag
        assert get_shutdown_flag() is _shutdown_flag
