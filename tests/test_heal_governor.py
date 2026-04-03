# Copyright (c) 2024-2026 Kevin Van Nieuwenhove. All rights reserved.
# NOBA Command Center — Licensed under Apache 2.0.

"""Tests for healing trust governor: promotion, demotion, effective trust."""
from __future__ import annotations

import time
from unittest.mock import patch


def _make_db():
    from server.db.core import Database
    db = Database(":memory:")
    db.init()
    return db


def _insert_outcome(db, rule_id="rule1", action_success=True, verified=False,
                    trust_level="execute", source="alert"):
    """Insert a heal outcome with sensible defaults."""
    db.insert_heal_outcome(
        correlation_key="test", rule_id=rule_id,
        condition="cpu > 90", target="nginx",
        action_type="restart_container",
        action_success=action_success, verified=verified,
        duration_s=1.0, metrics_before={"cpu": 95},
        trust_level=trust_level,
        source=source,
    )


# ---------------------------------------------------------------------------
# effective_trust
# ---------------------------------------------------------------------------

class TestEffectiveTrust:
    def test_no_state_returns_notify(self):
        from server.healing.governor import effective_trust
        db = _make_db()
        assert effective_trust("rule1", "alert", db) == "notify"

    def test_returns_stored_level(self):
        from server.healing.governor import effective_trust
        db = _make_db()
        db.upsert_trust_state("rule1", "approve", "execute")
        assert effective_trust("rule1", "alert", db) == "approve"

    def test_prediction_source_caps_one_below(self):
        from server.healing.governor import effective_trust
        db = _make_db()
        db.upsert_trust_state("rule1", "execute", "execute")
        assert effective_trust("rule1", "prediction", db) == "approve"

    def test_prediction_at_notify_stays_notify(self):
        from server.healing.governor import effective_trust
        db = _make_db()
        db.upsert_trust_state("rule1", "notify", "execute")
        assert effective_trust("rule1", "prediction", db) == "notify"

    def test_anomaly_source_caps_like_prediction(self):
        """anomaly and health_score sources apply the same cap as prediction."""
        from server.healing.governor import effective_trust
        db = _make_db()
        db.upsert_trust_state("rule1", "execute", "execute")
        assert effective_trust("rule1", "anomaly", db) == "approve"
        assert effective_trust("rule1", "health_score", db) == "approve"

    def test_prediction_approve_demotes_to_notify(self):
        """prediction source at approve level demotes to notify."""
        from server.healing.governor import effective_trust
        db = _make_db()
        db.upsert_trust_state("rule1", "approve", "execute")
        assert effective_trust("rule1", "prediction", db) == "notify"

    def test_alert_source_returns_exact_level(self):
        """alert source never caps — returns exact stored level."""
        from server.healing.governor import effective_trust
        db = _make_db()
        for level in ("notify", "approve", "execute"):
            db.upsert_trust_state("rule1", level, "execute")
            assert effective_trust("rule1", "alert", db) == level

    def test_unknown_rule_returns_notify(self):
        """A rule_id with no state in the DB defaults to notify."""
        from server.healing.governor import effective_trust
        db = _make_db()
        assert effective_trust("never_seen_rule", "alert", db) == "notify"

    def test_first_time_rule_different_sources(self):
        """First-time rule returns notify regardless of source."""
        from server.healing.governor import effective_trust
        db = _make_db()
        for src in ("alert", "prediction", "anomaly", "health_score"):
            assert effective_trust("new_rule", src, db) == "notify"


# ---------------------------------------------------------------------------
# Circuit breaker
# ---------------------------------------------------------------------------

class TestCircuitBreaker:
    def test_three_failures_demotes(self):
        from server.healing.governor import check_circuit_breaker
        db = _make_db()
        db.upsert_trust_state("rule1", "execute", "execute")
        for _ in range(3):
            _insert_outcome(db, verified=False)
        tripped = check_circuit_breaker("rule1", db)
        assert tripped is True
        state = db.get_trust_state("rule1")
        assert state["current_level"] == "notify"

    def test_two_failures_does_not_trip(self):
        """Below threshold, circuit breaker does not trip."""
        from server.healing.governor import check_circuit_breaker
        db = _make_db()
        db.upsert_trust_state("rule1", "execute", "execute")
        for _ in range(2):
            _insert_outcome(db, verified=False)
        tripped = check_circuit_breaker("rule1", db)
        assert tripped is False
        state = db.get_trust_state("rule1")
        assert state["current_level"] == "execute"

    def test_no_state_does_not_trip(self):
        """Rule with no trust state does not trip."""
        from server.healing.governor import check_circuit_breaker
        db = _make_db()
        for _ in range(3):
            _insert_outcome(db, verified=False)
        tripped = check_circuit_breaker("rule1", db)
        assert tripped is False

    def test_already_at_notify_does_not_trip(self):
        """If already at notify, circuit breaker returns False (no further demotion)."""
        from server.healing.governor import check_circuit_breaker
        db = _make_db()
        db.upsert_trust_state("rule1", "notify", "execute")
        for _ in range(3):
            _insert_outcome(db, verified=False)
        tripped = check_circuit_breaker("rule1", db)
        assert tripped is False

    def test_verified_outcomes_dont_trip(self):
        """Verified (successful) outcomes should not count as failures."""
        from server.healing.governor import check_circuit_breaker
        db = _make_db()
        db.upsert_trust_state("rule1", "execute", "execute")
        for _ in range(3):
            _insert_outcome(db, verified=True)
        tripped = check_circuit_breaker("rule1", db)
        assert tripped is False

    def test_old_failures_outside_window_dont_trip(self):
        """Failures outside the 1-hour window should not count."""
        from server.healing.governor import check_circuit_breaker, CIRCUIT_BREAKER_WINDOW_S
        db = _make_db()
        db.upsert_trust_state("rule1", "execute", "execute")
        for _ in range(3):
            _insert_outcome(db, verified=False)
        # Simulate all outcomes being older than the window by shifting time forward
        with patch("server.healing.governor.time") as mock_time:
            mock_time.time.return_value = time.time() + CIRCUIT_BREAKER_WINDOW_S + 100
            tripped = check_circuit_breaker("rule1", db)
        assert tripped is False

    def test_ceiling_preserved_after_demotion(self):
        """After circuit breaker trips, the ceiling is preserved."""
        from server.healing.governor import check_circuit_breaker
        db = _make_db()
        db.upsert_trust_state("rule1", "execute", "execute")
        for _ in range(3):
            _insert_outcome(db, verified=False)
        check_circuit_breaker("rule1", db)
        state = db.get_trust_state("rule1")
        assert state["current_level"] == "notify"
        assert state["ceiling"] == "execute"


# ---------------------------------------------------------------------------
# Trust promotion (evaluate_promotions)
# ---------------------------------------------------------------------------

class TestTrustPromotion:
    def test_no_states_returns_empty(self):
        from server.healing.governor import evaluate_promotions
        db = _make_db()
        result = evaluate_promotions(db)
        assert result == []

    def test_already_at_ceiling_skipped(self):
        """Rule at ceiling should not be suggested for promotion."""
        from server.healing.governor import evaluate_promotions
        db = _make_db()
        db.upsert_trust_state("rule1", "execute", "execute")
        result = evaluate_promotions(db)
        assert result == []

    def test_too_recent_skipped(self):
        """Rule changed too recently should not be promoted."""
        from server.healing.governor import evaluate_promotions
        db = _make_db()
        db.upsert_trust_state("rule1", "notify", "execute")
        # Insert enough outcomes
        for _ in range(15):
            _insert_outcome(db, trust_level="notify", verified=True)
        # The state was just created, so it's too recent
        result = evaluate_promotions(db)
        assert result == []

    def test_notify_to_approve_promotion(self):
        """Rule at notify with enough outcomes and age gets promotion suggestion."""
        from server.healing.governor import evaluate_promotions
        db = _make_db()
        db.upsert_trust_state("rule1", "notify", "execute")
        # Insert enough outcomes at notify level
        for _ in range(15):
            _insert_outcome(db, trust_level="notify", verified=True)
        # Patch time to simulate being 8 days in the future
        with patch("server.healing.governor.time") as mock_time:
            mock_time.time.return_value = time.time() + 8 * 86400
            result = evaluate_promotions(db)
        assert len(result) == 1
        assert result[0]["rule_id"] == "rule1"
        assert result[0]["suggested_action"]["promote_to"] == "approve"
        assert result[0]["category"] == "trust_promotion"

    def test_approve_to_execute_needs_high_success_rate(self):
        """approve->execute promotion requires >= 85% verified success rate."""
        from server.healing.governor import evaluate_promotions
        db = _make_db()
        db.upsert_trust_state("rule1", "approve", "execute")
        # Insert outcomes: 9 verified, 1 not verified (90% rate)
        for _ in range(9):
            _insert_outcome(db, trust_level="approve", verified=True)
        _insert_outcome(db, trust_level="approve", verified=False)
        with patch("server.healing.governor.time") as mock_time:
            mock_time.time.return_value = time.time() + 8 * 86400
            result = evaluate_promotions(db)
        assert len(result) == 1
        assert result[0]["suggested_action"]["promote_to"] == "execute"

    def test_approve_to_execute_low_rate_blocked(self):
        """approve->execute blocked when verified rate is below 85%."""
        from server.healing.governor import evaluate_promotions
        db = _make_db()
        db.upsert_trust_state("rule1", "approve", "execute")
        # Insert outcomes: 5 verified, 5 not (50% rate)
        for _ in range(5):
            _insert_outcome(db, trust_level="approve", verified=True)
        for _ in range(5):
            _insert_outcome(db, trust_level="approve", verified=False)
        with patch("server.healing.governor.time") as mock_time:
            mock_time.time.return_value = time.time() + 8 * 86400
            result = evaluate_promotions(db)
        assert result == []

    def test_not_enough_outcomes_skipped(self):
        """Rule without enough outcomes is not promoted."""
        from server.healing.governor import evaluate_promotions
        db = _make_db()
        db.upsert_trust_state("rule1", "notify", "execute")
        # Only 3 outcomes (need 10)
        for _ in range(3):
            _insert_outcome(db, trust_level="notify", verified=True)
        with patch("server.healing.governor.time") as mock_time:
            mock_time.time.return_value = time.time() + 8 * 86400
            result = evaluate_promotions(db)
        assert result == []


# ---------------------------------------------------------------------------
# Rate limiting / level ordering
# ---------------------------------------------------------------------------

class TestLevelOrdering:
    def test_all_levels_ordered(self):
        """_ALL_LEVELS and _LEVEL_ORDER are consistent."""
        from server.healing.governor import _ALL_LEVELS, _LEVEL_ORDER
        assert len(_ALL_LEVELS) == len(_LEVEL_ORDER)
        for i, lvl in enumerate(_ALL_LEVELS):
            assert _LEVEL_ORDER[lvl] == i

    def test_level_below_mapping(self):
        """_LEVEL_BELOW maps each level to the one below it."""
        from server.healing.governor import _LEVEL_BELOW
        assert _LEVEL_BELOW["execute"] == "approve"
        assert _LEVEL_BELOW["approve"] == "notify"
        assert _LEVEL_BELOW["notify"] == "dry_run"
        assert _LEVEL_BELOW["observation"] == "observation"


# ---------------------------------------------------------------------------
# Trust demotion edge cases
# ---------------------------------------------------------------------------

class TestTrustDemotion:
    def test_demotion_from_approve(self):
        """Circuit breaker at approve level demotes to notify."""
        from server.healing.governor import check_circuit_breaker
        db = _make_db()
        db.upsert_trust_state("rule1", "approve", "execute")
        for _ in range(3):
            _insert_outcome(db, trust_level="approve", verified=False)
        tripped = check_circuit_breaker("rule1", db)
        assert tripped is True
        state = db.get_trust_state("rule1")
        assert state["current_level"] == "notify"

    def test_multiple_rules_independent(self):
        """Circuit breaker on one rule does not affect another."""
        from server.healing.governor import check_circuit_breaker
        db = _make_db()
        db.upsert_trust_state("ruleA", "execute", "execute")
        db.upsert_trust_state("ruleB", "execute", "execute")
        for _ in range(3):
            _insert_outcome(db, rule_id="ruleA", verified=False)
        assert check_circuit_breaker("ruleA", db) is True
        assert check_circuit_breaker("ruleB", db) is False
        assert db.get_trust_state("ruleB")["current_level"] == "execute"
