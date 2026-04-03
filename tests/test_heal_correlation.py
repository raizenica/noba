# Copyright (c) 2024-2026 Kevin Van Nieuwenhove. All rights reserved.
# NOBA Command Center — Licensed under Apache 2.0.

"""Tests for healing correlation: immediate-on-first with absorption."""
from __future__ import annotations

import time


class TestCorrelation:
    def _make_event(self, target="nginx", rule_id="r1", source="alert"):
        from server.healing.models import HealEvent
        return HealEvent(
            source=source, rule_id=rule_id, condition="cpu > 90",
            target=target, severity="warning",
            timestamp=time.time(), metrics={"cpu": 95},
        )

    def _correlator(self, window=60):
        from server.healing.correlation import HealCorrelator
        return HealCorrelator(absorption_window=window)

    def test_first_event_emits_request(self):
        c = self._correlator()
        result = c.correlate(self._make_event())
        assert result is not None
        assert result.primary_target == "nginx"
        assert len(result.events) == 1

    def test_second_event_same_target_absorbed(self):
        c = self._correlator()
        c.correlate(self._make_event())
        result = c.correlate(self._make_event())
        assert result is None

    def test_different_target_not_absorbed(self):
        c = self._correlator()
        c.correlate(self._make_event(target="nginx"))
        result = c.correlate(self._make_event(target="postgres"))
        assert result is not None
        assert result.primary_target == "postgres"

    def test_expired_window_allows_new_request(self):
        c = self._correlator(window=0)  # 0s window = immediate expiry
        c.correlate(self._make_event())
        time.sleep(0.01)
        result = c.correlate(self._make_event())
        assert result is not None

    def test_highest_severity_wins(self):
        c = self._correlator()
        e = self._make_event()
        e.severity = "critical"
        result = c.correlate(e)
        assert result.severity == "critical"

    def test_thread_safety(self):
        import threading
        c = self._correlator()
        results = []

        def worker(i):
            r = c.correlate(self._make_event(target=f"svc-{i}"))
            results.append(r)

        threads = [threading.Thread(target=worker, args=(i,)) for i in range(10)]
        for t in threads:
            t.start()
        for t in threads:
            t.join()
        # Each unique target should get its own request
        non_none = [r for r in results if r is not None]
        assert len(non_none) == 10
