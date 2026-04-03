# Copyright (c) 2024-2026 Kevin Van Nieuwenhove. All rights reserved.
# NOBA Command Center — Licensed under Apache 2.0.

"""Tests for conservative trust cap on prediction/anomaly events."""
from __future__ import annotations

from unittest.mock import MagicMock


class TestPredictiveTrustCap:
    def test_prediction_source_capped_below_execute(self):
        from server.healing.governor import effective_trust
        db = MagicMock()
        db.get_trust_state = MagicMock(return_value={"current_level": "execute", "ceiling": "execute"})
        trust = effective_trust("test-rule", "prediction", db)
        # Should be capped to "approve" (one below execute)
        assert trust == "approve"

    def test_anomaly_source_capped(self):
        from server.healing.governor import effective_trust
        db = MagicMock()
        db.get_trust_state = MagicMock(return_value={"current_level": "execute", "ceiling": "execute"})
        trust = effective_trust("test-rule", "anomaly", db)
        assert trust == "approve"

    def test_prediction_from_notify_stays_notify(self):
        from server.healing.governor import effective_trust
        db = MagicMock()
        db.get_trust_state = MagicMock(return_value={"current_level": "notify", "ceiling": "execute"})
        trust = effective_trust("test-rule", "prediction", db)
        assert trust == "notify"  # can't go below notify

    def test_alert_source_not_capped(self):
        from server.healing.governor import effective_trust
        db = MagicMock()
        db.get_trust_state = MagicMock(return_value={"current_level": "execute", "ceiling": "execute"})
        trust = effective_trust("test-rule", "alert", db)
        assert trust == "execute"  # normal alerts keep full trust

    def test_health_score_source_capped(self):
        from server.healing.governor import effective_trust
        db = MagicMock()
        db.get_trust_state = MagicMock(return_value={"current_level": "execute", "ceiling": "execute"})
        trust = effective_trust("test-rule", "health_score", db)
        assert trust == "approve"
