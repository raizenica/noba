"""TDD tests for expanded action registry in remediation.py."""
from __future__ import annotations

VALID_RISK_LEVELS = {"low", "medium", "high"}
REQUIRED_FIELDS = {"risk", "params", "description", "timeout_s"}
SPOT_CHECKS = {
    "service_reload": "low",
    "process_kill": "low",
    "container_pause": "low",
    "journal_vacuum": "low",
    "container_recreate": "medium",
    "cert_renew": "medium",
    "vpn_reconnect": "medium",
    "host_reboot": "high",
    "vm_restart": "high",
    "snapshot_rollback": "high",
}
FALLBACK_CHAIN_KEYS = {
    "service_restart",
    "service_reload",
    "process_kill",
    "network_interface_restart",
    "disk_cleanup",
}


class TestActionTypesDefined:
    def test_all_action_types_have_required_fields(self):
        from server.remediation import ACTION_TYPES
        for name, defn in ACTION_TYPES.items():
            missing = REQUIRED_FIELDS - defn.keys()
            assert not missing, f"Action '{name}' missing fields: {missing}"

    def test_all_action_types_have_valid_risk_level(self):
        from server.remediation import ACTION_TYPES
        for name, defn in ACTION_TYPES.items():
            assert defn["risk"] in VALID_RISK_LEVELS, (
                f"Action '{name}' has invalid risk: {defn['risk']!r}"
            )

    def test_minimum_40_action_types(self):
        from server.remediation import ACTION_TYPES
        assert len(ACTION_TYPES) >= 40, (
            f"Expected at least 40 action types, got {len(ACTION_TYPES)}"
        )

    def test_timeout_s_is_positive_int(self):
        from server.remediation import ACTION_TYPES
        for name, defn in ACTION_TYPES.items():
            t = defn["timeout_s"]
            assert isinstance(t, int) and t > 0, (
                f"Action '{name}' timeout_s must be a positive int, got {t!r}"
            )


class TestSpotChecks:
    def test_spot_check_risk_levels(self):
        from server.remediation import ACTION_TYPES
        for action_name, expected_risk in SPOT_CHECKS.items():
            assert action_name in ACTION_TYPES, (
                f"Expected action '{action_name}' to exist in ACTION_TYPES"
            )
            actual_risk = ACTION_TYPES[action_name]["risk"]
            assert actual_risk == expected_risk, (
                f"Action '{action_name}': expected risk={expected_risk!r}, "
                f"got {actual_risk!r}"
            )

    def test_service_reload_params(self):
        from server.remediation import ACTION_TYPES
        defn = ACTION_TYPES["service_reload"]
        assert "service" in defn["params"]

    def test_process_kill_params(self):
        from server.remediation import ACTION_TYPES
        defn = ACTION_TYPES["process_kill"]
        assert "pid" in defn["params"]

    def test_container_pause_params(self):
        from server.remediation import ACTION_TYPES
        defn = ACTION_TYPES["container_pause"]
        assert "container" in defn["params"]

    def test_host_reboot_params(self):
        from server.remediation import ACTION_TYPES
        defn = ACTION_TYPES["host_reboot"]
        assert "hostname" in defn["params"]

    def test_vm_restart_params(self):
        from server.remediation import ACTION_TYPES
        defn = ACTION_TYPES["vm_restart"]
        assert "vm_id" in defn["params"]
        assert "platform" in defn["params"]

    def test_snapshot_rollback_params(self):
        from server.remediation import ACTION_TYPES
        defn = ACTION_TYPES["snapshot_rollback"]
        assert "target" in defn["params"]
        assert "snapshot" in defn["params"]

    def test_cert_renew_params(self):
        from server.remediation import ACTION_TYPES
        defn = ACTION_TYPES["cert_renew"]
        assert "domain" in defn["params"]

    def test_vpn_reconnect_params(self):
        from server.remediation import ACTION_TYPES
        defn = ACTION_TYPES["vpn_reconnect"]
        assert "interface" in defn["params"]

    def test_journal_vacuum_params(self):
        from server.remediation import ACTION_TYPES
        defn = ACTION_TYPES["journal_vacuum"]
        assert "max_size" in defn["params"]

    def test_container_recreate_params(self):
        from server.remediation import ACTION_TYPES
        defn = ACTION_TYPES["container_recreate"]
        assert "container" in defn["params"]


class TestFallbackChains:
    def test_fallback_chains_dict_exists(self):
        from server.remediation import FALLBACK_CHAINS
        assert isinstance(FALLBACK_CHAINS, dict), "FALLBACK_CHAINS must be a dict"

    def test_required_chains_present(self):
        from server.remediation import FALLBACK_CHAINS
        for key in FALLBACK_CHAIN_KEYS:
            assert key in FALLBACK_CHAINS, (
                f"Expected FALLBACK_CHAINS to contain key: {key!r}"
            )

    def test_each_chain_has_at_least_two_handlers(self):
        from server.remediation import FALLBACK_CHAINS
        for key in FALLBACK_CHAIN_KEYS:
            chain = FALLBACK_CHAINS[key]
            assert len(chain) >= 2, (
                f"Chain '{key}' must have at least 2 handlers, got {len(chain)}"
            )

    def test_chain_handlers_have_requires_and_cmd(self):
        from server.remediation import FALLBACK_CHAINS
        for chain_name, handlers in FALLBACK_CHAINS.items():
            for i, handler in enumerate(handlers):
                assert "requires" in handler, (
                    f"Chain '{chain_name}' handler[{i}] missing 'requires' key"
                )
                assert "cmd" in handler, (
                    f"Chain '{chain_name}' handler[{i}] missing 'cmd' key"
                )

    def test_service_restart_chain_has_systemctl(self):
        from server.remediation import FALLBACK_CHAINS
        chain = FALLBACK_CHAINS["service_restart"]
        requires_vals = [h["requires"] for h in chain]
        assert "systemctl" in requires_vals

    def test_service_reload_chain_has_systemctl(self):
        from server.remediation import FALLBACK_CHAINS
        chain = FALLBACK_CHAINS["service_reload"]
        requires_vals = [h["requires"] for h in chain]
        assert "systemctl" in requires_vals

    def test_process_kill_chain_has_kill(self):
        from server.remediation import FALLBACK_CHAINS
        chain = FALLBACK_CHAINS["process_kill"]
        requires_vals = [h["requires"] for h in chain]
        assert "kill" in requires_vals

    def test_network_interface_restart_chain_has_ip(self):
        from server.remediation import FALLBACK_CHAINS
        chain = FALLBACK_CHAINS["network_interface_restart"]
        requires_vals = [h["requires"] for h in chain]
        assert "ip" in requires_vals

    def test_disk_cleanup_chain_has_fstrim(self):
        from server.remediation import FALLBACK_CHAINS
        chain = FALLBACK_CHAINS["disk_cleanup"]
        requires_vals = [h["requires"] for h in chain]
        assert "fstrim" in requires_vals


class TestReversibilityRegistry:
    def test_all_action_types_have_reversible_field(self):
        from server.remediation import ACTION_TYPES
        for name, defn in ACTION_TYPES.items():
            assert "reversible" in defn, (
                f"Action '{name}' missing 'reversible' field"
            )
            assert isinstance(defn["reversible"], bool), (
                f"Action '{name}' 'reversible' must be bool, got {type(defn['reversible'])}"
            )

    def test_reversible_true_requires_reverse_action(self):
        from server.remediation import ACTION_TYPES
        for name, defn in ACTION_TYPES.items():
            if defn["reversible"]:
                assert "reverse_action" in defn, (
                    f"Action '{name}' is reversible but missing 'reverse_action'"
                )
                assert defn["reverse_action"], (
                    f"Action '{name}' has empty 'reverse_action'"
                )

    def test_scale_container_is_reversible(self):
        from server.remediation import ACTION_TYPES
        defn = ACTION_TYPES["scale_container"]
        assert defn["reversible"] is True
        assert defn["reverse_action"] == "scale_container"

    def test_failover_dns_is_reversible(self):
        from server.remediation import ACTION_TYPES
        defn = ACTION_TYPES["failover_dns"]
        assert defn["reversible"] is True
        assert defn["reverse_action"] == "failover_dns"

    def test_container_pause_is_reversible(self):
        from server.remediation import ACTION_TYPES
        defn = ACTION_TYPES["container_pause"]
        assert defn["reversible"] is True

    def test_vm_migrate_is_reversible(self):
        from server.remediation import ACTION_TYPES
        defn = ACTION_TYPES["vm_migrate"]
        assert defn["reversible"] is True

    def test_firewall_rule_add_is_reversible(self):
        from server.remediation import ACTION_TYPES
        defn = ACTION_TYPES["firewall_rule_add"]
        assert defn["reversible"] is True
        assert defn["reverse_action"] == "firewall_rule_remove"

    def test_host_reboot_is_not_reversible(self):
        from server.remediation import ACTION_TYPES
        defn = ACTION_TYPES["host_reboot"]
        assert defn["reversible"] is False

    def test_restart_container_is_not_reversible(self):
        from server.remediation import ACTION_TYPES
        defn = ACTION_TYPES["restart_container"]
        assert defn["reversible"] is False

    def test_settle_s_field_exists_and_is_non_negative(self):
        from server.remediation import ACTION_TYPES
        for name, defn in ACTION_TYPES.items():
            assert "settle_s" in defn, f"Action '{name}' missing 'settle_s' field"
            assert isinstance(defn["settle_s"], int) and defn["settle_s"] >= 0, (
                f"Action '{name}' settle_s must be a non-negative int"
            )
