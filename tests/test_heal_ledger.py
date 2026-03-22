"""Tests for the healing pipeline DB layer — ledger, trust_state, suggestions."""
from __future__ import annotations


def _db():
    from server.db.core import Database
    db = Database(":memory:")
    db.init()
    return db


class TestHealLedger:
    def test_insert_and_get_outcomes(self):
        db = _db()
        rid = db.insert_heal_outcome(
            correlation_key="corr-1",
            rule_id="rule-cpu",
            condition="cpu_high",
            target="host-a",
            action_type="restart_service",
            action_params={"service": "nginx"},
            escalation_step=0,
            action_success=True,
            verified=True,
            duration_s=12.5,
            metrics_before={"cpu": 95},
            metrics_after={"cpu": 40},
            trust_level="execute",
            source="scheduler",
            approval_id=None,
        )
        assert isinstance(rid, int) and rid > 0
        rows = db.get_heal_outcomes()
        assert len(rows) == 1
        r = rows[0]
        assert r["rule_id"] == "rule-cpu"
        assert r["condition"] == "cpu_high"
        assert r["target"] == "host-a"
        assert r["action_type"] == "restart_service"
        assert r["escalation_step"] == 0
        assert r["verified"] == 1
        assert r["duration_s"] == 12.5

    def test_get_outcomes_filter_by_rule_id(self):
        db = _db()
        db.insert_heal_outcome(rule_id="rule-a", condition="c1", action_type="t1",
                               action_success=True, verified=True)
        db.insert_heal_outcome(rule_id="rule-b", condition="c2", action_type="t2",
                               action_success=True, verified=True)
        rows = db.get_heal_outcomes(rule_id="rule-a")
        assert all(r["rule_id"] == "rule-a" for r in rows)
        assert len(rows) == 1

    def test_get_outcomes_filter_by_target(self):
        db = _db()
        db.insert_heal_outcome(rule_id="r1", condition="c", action_type="t",
                               target="host-x", action_success=True, verified=True)
        db.insert_heal_outcome(rule_id="r1", condition="c", action_type="t",
                               target="host-y", action_success=True, verified=True)
        rows = db.get_heal_outcomes(target="host-x")
        assert len(rows) == 1
        assert rows[0]["target"] == "host-x"

    def test_success_rate_75_percent(self):
        """3 verified successes + 1 unverified (action_success set) = 75%."""
        db = _db()
        for _ in range(3):
            db.insert_heal_outcome(
                condition="cpu_high", action_type="restart_service",
                action_success=True, verified=True,
            )
        # 4th: action_success is set but not verified
        db.insert_heal_outcome(
            condition="cpu_high", action_type="restart_service",
            action_success=False, verified=False,
        )
        rate = db.get_heal_success_rate("restart_service", "cpu_high")
        assert rate == 75.0

    def test_success_rate_no_data_returns_zero(self):
        db = _db()
        rate = db.get_heal_success_rate("nonexistent", "nonexistent_condition")
        assert rate == 0.0

    def test_mean_time_to_resolve(self):
        db = _db()
        for d in [10.0, 20.0, 30.0]:
            db.insert_heal_outcome(
                condition="disk_full", action_type="cleanup",
                verified=True, duration_s=d,
            )
        mttr = db.get_mean_time_to_resolve("disk_full")
        assert mttr == 20.0

    def test_mean_time_to_resolve_no_data(self):
        db = _db()
        assert db.get_mean_time_to_resolve("no_such_condition") is None

    def test_escalation_frequency(self):
        db = _db()
        db.insert_heal_outcome(rule_id="rule-1", condition="c", action_type="t",
                               escalation_step=0)
        db.insert_heal_outcome(rule_id="rule-1", condition="c", action_type="t",
                               escalation_step=0)
        db.insert_heal_outcome(rule_id="rule-1", condition="c", action_type="t",
                               escalation_step=1)
        freq = db.get_escalation_frequency("rule-1")
        assert freq[0] == 2
        assert freq[1] == 1


class TestTrustState:
    def test_upsert_and_get(self):
        db = _db()
        db.upsert_trust_state("rule-x", "notify", "execute")
        state = db.get_trust_state("rule-x")
        assert state is not None
        assert state["rule_id"] == "rule-x"
        assert state["current_level"] == "notify"
        assert state["ceiling"] == "execute"
        assert state["promotion_count"] == 0
        assert state["demotion_count"] == 0

    def test_get_nonexistent_returns_none(self):
        db = _db()
        assert db.get_trust_state("no-such-rule") is None

    def test_update_promotion(self):
        db = _db()
        db.upsert_trust_state("rule-y", "notify", "execute")
        db.upsert_trust_state("rule-y", "approve", "execute")
        state = db.get_trust_state("rule-y")
        assert state["current_level"] == "approve"
        assert state["promotion_count"] == 1
        assert state["demotion_count"] == 0
        assert state["promoted_at"] is not None

    def test_update_demotion(self):
        db = _db()
        db.upsert_trust_state("rule-z", "execute", "execute")
        db.upsert_trust_state("rule-z", "notify", "execute")
        state = db.get_trust_state("rule-z")
        assert state["current_level"] == "notify"
        assert state["demotion_count"] == 1
        assert state["promotion_count"] == 0
        assert state["demoted_at"] is not None

    def test_list_trust_states(self):
        db = _db()
        db.upsert_trust_state("rule-1", "notify", "execute")
        db.upsert_trust_state("rule-2", "suggest", "execute")
        states = db.list_trust_states()
        rule_ids = [s["rule_id"] for s in states]
        assert "rule-1" in rule_ids
        assert "rule-2" in rule_ids

    def test_no_count_change_same_level(self):
        db = _db()
        db.upsert_trust_state("rule-same", "notify", "execute")
        db.upsert_trust_state("rule-same", "notify", "execute")
        state = db.get_trust_state("rule-same")
        assert state["promotion_count"] == 0
        assert state["demotion_count"] == 0


class TestHealSuggestions:
    def test_insert_and_list(self):
        db = _db()
        sid = db.insert_heal_suggestion(
            category="high_escalation",
            severity="warning",
            message="Rule rule-1 escalated 5 times this week.",
            rule_id="rule-1",
            suggested_action="lower_threshold",
            evidence={"count": 5},
        )
        assert isinstance(sid, int) and sid > 0
        suggestions = db.list_heal_suggestions()
        assert len(suggestions) == 1
        s = suggestions[0]
        assert s["category"] == "high_escalation"
        assert s["rule_id"] == "rule-1"
        assert s["dismissed"] == 0

    def test_dismiss(self):
        db = _db()
        sid = db.insert_heal_suggestion(
            category="low_success_rate",
            severity="critical",
            message="Success rate below 50%.",
            rule_id="rule-2",
        )
        db.dismiss_heal_suggestion(sid)
        # default list excludes dismissed
        active = db.list_heal_suggestions()
        assert not any(s["id"] == sid for s in active)
        # include_dismissed shows it
        all_s = db.list_heal_suggestions(include_dismissed=True)
        found = next((s for s in all_s if s["id"] == sid), None)
        assert found is not None
        assert found["dismissed"] == 1

    def test_upsert_deduplication(self):
        """Same category+rule_id should replace rather than insert a duplicate."""
        db = _db()
        db.insert_heal_suggestion(
            category="high_escalation",
            severity="warning",
            message="First message.",
            rule_id="rule-3",
        )
        db.insert_heal_suggestion(
            category="high_escalation",
            severity="critical",
            message="Updated message.",
            rule_id="rule-3",
        )
        suggestions = db.list_heal_suggestions(include_dismissed=True)
        matching = [s for s in suggestions
                    if s["category"] == "high_escalation" and s["rule_id"] == "rule-3"]
        # Only one row should exist (replaced)
        assert len(matching) == 1
        assert matching[0]["severity"] == "critical"
        assert matching[0]["message"] == "Updated message."

    def test_list_excludes_dismissed_by_default(self):
        db = _db()
        s1 = db.insert_heal_suggestion(
            category="cat_a", severity="info", message="Keep.", rule_id="rule-keep"
        )
        s2 = db.insert_heal_suggestion(
            category="cat_b", severity="info", message="Dismiss.", rule_id="rule-dismiss"
        )
        db.dismiss_heal_suggestion(s2)
        active = db.list_heal_suggestions()
        ids = [s["id"] for s in active]
        assert s1 in ids
        assert s2 not in ids
