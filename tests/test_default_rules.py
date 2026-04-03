# Copyright (c) 2024-2026 Kevin Van Nieuwenhove. All rights reserved.
# NOBA Command Center — Licensed under Apache 2.0.

"""Tests for healing.default_rules: default escalation chains."""
from __future__ import annotations


class TestDefaultChains:
    def test_cpu_critical_chain_exists(self):
        from server.healing.default_rules import get_chain_for_scenario
        chain = get_chain_for_scenario("cpu_critical")
        assert chain is not None
        assert len(chain["escalation_chain"]) >= 2

    def test_service_failed_chain_exists(self):
        from server.healing.default_rules import get_chain_for_scenario
        chain = get_chain_for_scenario("service_failed")
        assert chain is not None
        assert chain["escalation_chain"][0]["action"] == "service_reset_failed"

    def test_disk_critical_chain_exists(self):
        from server.healing.default_rules import get_chain_for_scenario
        chain = get_chain_for_scenario("disk_critical")
        assert chain is not None
        assert len(chain["escalation_chain"]) >= 3

    def test_container_down_chain_exists(self):
        from server.healing.default_rules import get_chain_for_scenario
        chain = get_chain_for_scenario("container_down")
        assert chain is not None
        assert chain["escalation_chain"][0]["action"] == "restart_container"

    def test_memory_critical_chain_exists(self):
        from server.healing.default_rules import get_chain_for_scenario
        chain = get_chain_for_scenario("memory_critical")
        assert chain is not None

    def test_unknown_scenario_returns_none(self):
        from server.healing.default_rules import get_chain_for_scenario
        assert get_chain_for_scenario("nonexistent") is None

    def test_all_default_autonomy_is_notify(self):
        """Default rules start at notify trust — must earn promotion."""
        from server.healing.default_rules import DEFAULT_CHAINS
        for name, chain in DEFAULT_CHAINS.items():
            assert chain["default_autonomy"] == "notify", (
                f"{name} should default to notify, got {chain['default_autonomy']}"
            )


class TestRuleIdMatching:
    def test_cpu_crit_matches(self):
        from server.healing.default_rules import get_chain_for_rule_id
        chain = get_chain_for_rule_id("cpu_crit")
        assert chain is not None
        assert chain[0]["action"] == "process_kill"

    def test_svc_nginx_matches_service_failed(self):
        from server.healing.default_rules import get_chain_for_rule_id
        chain = get_chain_for_rule_id("svc_nginx")
        assert chain is not None
        assert chain[0]["action"] == "service_reset_failed"

    def test_disk_crit_root_matches(self):
        from server.healing.default_rules import get_chain_for_rule_id
        chain = get_chain_for_rule_id("disk_crit_/")
        assert chain is not None
        assert chain[0]["action"] == "temp_cleanup"

    def test_container_matches(self):
        from server.healing.default_rules import get_chain_for_rule_id
        chain = get_chain_for_rule_id("container_frigate")
        assert chain is not None
        assert chain[0]["action"] == "restart_container"

    def test_mem_crit_matches(self):
        from server.healing.default_rules import get_chain_for_rule_id
        chain = get_chain_for_rule_id("mem_crit")
        assert chain is not None

    def test_dns_matches(self):
        from server.healing.default_rules import get_chain_for_rule_id
        chain = get_chain_for_rule_id("dns_pihole_down")
        assert chain is not None

    def test_vpn_matches(self):
        from server.healing.default_rules import get_chain_for_rule_id
        chain = get_chain_for_rule_id("vpn_tailscale_disconnected")
        assert chain is not None

    def test_unknown_rule_returns_none(self):
        from server.healing.default_rules import get_chain_for_rule_id
        assert get_chain_for_rule_id("random_unrelated_rule") is None
