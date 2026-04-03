# Copyright (c) 2024-2026 Kevin Van Nieuwenhove. All rights reserved.
# NOBA Command Center — Licensed under Apache 2.0.

"""Tests for healing.chaos: controlled fault injection framework."""
from __future__ import annotations



class TestChaosScenario:
    def test_scenario_from_dict(self):
        from server.healing.chaos import ChaosScenario
        s = ChaosScenario.from_dict({
            "name": "test_crash",
            "description": "Test container crash recovery",
            "inject": {"action": "stop_container", "target": "frigate"},
            "expect": [
                {"check": "heal_triggered", "value": True},
                {"check": "action_taken", "value": "restart_container"},
            ],
        })
        assert s.name == "test_crash"
        assert s.inject["action"] == "stop_container"
        assert len(s.expectations) == 2

    def test_scenario_fields(self):
        from server.healing.chaos import ChaosScenario
        s = ChaosScenario.from_dict({
            "name": "test",
            "description": "desc",
            "inject": {"action": "stop_container", "target": "plex"},
            "expect": [],
        })
        assert s.name == "test"
        assert s.description == "desc"


class TestChaosRunner:
    def test_list_scenarios(self):
        from server.healing.chaos import ChaosRunner
        runner = ChaosRunner()
        scenarios = runner.list_scenarios()
        assert isinstance(scenarios, list)
        assert len(scenarios) >= 5  # spec defines 12 built-in scenarios

    def test_scenario_names_unique(self):
        from server.healing.chaos import ChaosRunner
        runner = ChaosRunner()
        names = [s["name"] for s in runner.list_scenarios()]
        assert len(names) == len(set(names))

    def test_dry_run_returns_result(self):
        from server.healing.chaos import ChaosRunner
        runner = ChaosRunner()
        scenarios = runner.list_scenarios()
        if scenarios:
            result = runner.run_scenario(scenarios[0]["name"], dry_run=True)
            assert isinstance(result, dict)
            assert "name" in result
            assert "status" in result
            assert result["dry_run"] is True

    def test_unknown_scenario_returns_error(self):
        from server.healing.chaos import ChaosRunner
        runner = ChaosRunner()
        result = runner.run_scenario("nonexistent_scenario", dry_run=True)
        assert result["status"] == "error"
        assert "not found" in result.get("message", "").lower()

    def test_built_in_scenarios_have_descriptions(self):
        from server.healing.chaos import ChaosRunner
        runner = ChaosRunner()
        for s in runner.list_scenarios():
            assert s.get("description"), f"Scenario {s['name']} missing description"


class TestChaosExpectation:
    def test_check_passes(self):
        from server.healing.chaos import check_expectation
        result = check_expectation(
            {"check": "heal_triggered", "value": True},
            actual={"heal_triggered": True},
        )
        assert result["passed"] is True

    def test_check_fails(self):
        from server.healing.chaos import check_expectation
        result = check_expectation(
            {"check": "heal_triggered", "value": True},
            actual={"heal_triggered": False},
        )
        assert result["passed"] is False

    def test_check_missing_key(self):
        from server.healing.chaos import check_expectation
        result = check_expectation(
            {"check": "nonexistent", "value": True},
            actual={},
        )
        assert result["passed"] is False
