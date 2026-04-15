# Copyright (c) 2024-2026 Kevin Van Nieuwenhove. All rights reserved.
# NOBA Command Center — Licensed under Apache 2.0.

"""Tests for healing.watchdog: component health monitoring."""
from __future__ import annotations

import time


class TestComponentWatchdog:
    def _make_watchdog(self):
        from server.healing.watchdog import ComponentWatchdog
        return ComponentWatchdog()

    def test_register_component(self):
        wd = self._make_watchdog()
        wd.register("collector", interval=5, tolerance=3)
        assert "collector" in wd.list_components()

    def test_heartbeat_marks_healthy(self):
        wd = self._make_watchdog()
        wd.register("collector", interval=5, tolerance=3)
        wd.heartbeat("collector")
        status = wd.get_status("collector")
        assert status["healthy"] is True

    def test_missed_heartbeats_marks_unhealthy(self):
        wd = self._make_watchdog()
        wd.register("collector", interval=1, tolerance=2)
        # Simulate stale heartbeat
        wd._components["collector"]["last_heartbeat"] = time.time() - 10
        wd.check_all()
        status = wd.get_status("collector")
        assert status["healthy"] is False

    def test_recovery_callback_called(self):
        wd = self._make_watchdog()
        recovered = []
        wd.register("scheduler", interval=1, tolerance=2,
                    on_failure=lambda name: recovered.append(name))
        wd._components["scheduler"]["last_heartbeat"] = time.time() - 10
        wd.check_all()
        assert "scheduler" in recovered

    def test_recovery_not_called_when_healthy(self):
        wd = self._make_watchdog()
        recovered = []
        wd.register("api", interval=5, tolerance=3,
                    on_failure=lambda name: recovered.append(name))
        wd.heartbeat("api")
        wd.check_all()
        assert len(recovered) == 0

    def test_degraded_mode_on_multiple_failures(self):
        wd = self._make_watchdog()
        wd.register("collector", interval=1, tolerance=1)
        wd.register("scheduler", interval=1, tolerance=1)
        wd.register("healing", interval=1, tolerance=1)
        now = time.time()
        for comp in ["collector", "scheduler", "healing"]:
            wd._components[comp]["last_heartbeat"] = now - 100
        wd.check_all()
        assert wd.is_degraded()

    def test_not_degraded_with_one_failure(self):
        wd = self._make_watchdog()
        wd.register("collector", interval=1, tolerance=1)
        wd.register("scheduler", interval=1, tolerance=1)
        wd.register("healing", interval=1, tolerance=1)
        wd.heartbeat("collector")
        wd.heartbeat("scheduler")
        wd._components["healing"]["last_heartbeat"] = time.time() - 100
        wd.check_all()
        assert not wd.is_degraded()

    def test_get_health_summary(self):
        wd = self._make_watchdog()
        wd.register("collector", interval=5, tolerance=3)
        wd.register("scheduler", interval=60, tolerance=2)
        wd.heartbeat("collector")
        wd.heartbeat("scheduler")
        summary = wd.get_health_summary()
        assert "collector" in summary
        assert "scheduler" in summary
        assert summary["collector"]["healthy"] is True
        assert "degraded" in summary

    def test_unregistered_component_returns_none(self):
        wd = self._make_watchdog()
        assert wd.get_status("nonexistent") is None
