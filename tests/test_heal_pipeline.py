# Copyright (c) 2024-2026 Kevin Van Nieuwenhove. All rights reserved.
# NOBA Command Center — Licensed under Apache 2.0.

"""Integration tests for the full healing pipeline."""
from __future__ import annotations

import threading
import time
from unittest.mock import patch


class TestHandleHealEvent:
    def _db(self):
        from server.db.core import Database
        db = Database(":memory:")
        db.init()
        return db

    def _event(self, target="nginx", source="alert"):
        from server.healing.models import HealEvent
        return HealEvent(
            source=source, rule_id="cpu_high",
            condition="cpu_percent > 90", target=target,
            severity="warning", timestamp=time.time(),
            metrics={"cpu_percent": 95},
        )

    @patch("server.healing.executor._get_fresh_metrics")
    @patch("server.remediation.execute_action")
    def test_full_pipeline_execute(self, mock_exec, mock_metrics):
        mock_exec.return_value = {"success": True, "output": "OK", "duration_s": 1.0}
        mock_metrics.return_value = {"cpu_percent": 40}

        db = self._db()
        db.upsert_trust_state("cpu_high", "execute", "execute")

        chain = [{"action": "restart_container", "params": {"container": "nginx"}, "verify_timeout": 30}]
        rules_cfg = {"cpu_high": {"escalation_chain": chain}}

        from server.healing import create_pipeline

        done = threading.Event()
        outcomes = []

        def on_outcome(outcome):
            outcomes.append(outcome)
            done.set()

        pipeline = create_pipeline(db, rules_cfg, settle_times={"restart_container": 0.01})
        pipeline.on_outcome = on_outcome
        pipeline.handle_heal_event(self._event())
        done.wait(timeout=5)

        assert len(outcomes) == 1
        assert outcomes[0].verified is True
        # Check ledger was written
        rows = db.get_heal_outcomes()
        assert len(rows) >= 1

    def test_notify_path_records_ledger(self):
        db = self._db()
        db.upsert_trust_state("cpu_high", "notify", "execute")

        chain = [{"action": "restart_container", "params": {"container": "nginx"}}]
        rules_cfg = {"cpu_high": {"escalation_chain": chain}}

        from server.healing import create_pipeline
        pipeline = create_pipeline(db, rules_cfg)

        with patch("server.healing.dispatch_notifications"):
            pipeline.handle_heal_event(self._event())

        rows = db.get_heal_outcomes()
        assert len(rows) == 1
        assert rows[0]["action_success"] is None  # notify = no action
        assert rows[0]["trust_level"] == "notify"

    def test_correlation_absorbs_duplicate(self):
        db = self._db()
        db.upsert_trust_state("cpu_high", "notify", "execute")

        chain = [{"action": "restart_container", "params": {"container": "nginx"}}]
        rules_cfg = {"cpu_high": {"escalation_chain": chain}}

        from server.healing import create_pipeline
        pipeline = create_pipeline(db, rules_cfg)

        with patch("server.healing.dispatch_notifications"):
            pipeline.handle_heal_event(self._event())
            pipeline.handle_heal_event(self._event())  # same target, absorbed

        rows = db.get_heal_outcomes()
        assert len(rows) == 1  # only one recorded
