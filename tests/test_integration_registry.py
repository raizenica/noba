# Copyright (c) 2024-2026 Kevin Van Nieuwenhove. All rights reserved.
# NOBA Command Center — Licensed under Apache 2.0.

"""Tests for the universal integration registry."""
from __future__ import annotations


class TestGetIntegrationHandler:
    def test_known_operation_and_platform(self):
        from server.healing.integration_registry import get_integration_handler
        handler = get_integration_handler("nas_scrub", "truenas")
        assert handler is not None
        assert isinstance(handler, dict)
        assert "method" in handler

    def test_unknown_platform_returns_none(self):
        from server.healing.integration_registry import get_integration_handler
        result = get_integration_handler("nas_scrub", "nonexistent_platform")
        assert result is None

    def test_unknown_operation_returns_none(self):
        from server.healing.integration_registry import get_integration_handler
        result = get_integration_handler("nonexistent_operation", "truenas")
        assert result is None

    def test_handler_has_required_fields(self):
        from server.healing.integration_registry import get_integration_handler
        handler = get_integration_handler("nas_scrub", "truenas")
        assert "method" in handler


class TestListOperations:
    def test_nas_category_includes_scrub_and_repair(self):
        from server.healing.integration_registry import list_operations
        ops = list_operations("nas")
        assert "nas_scrub" in ops
        assert "nas_pool_repair" in ops

    def test_unknown_category_returns_empty(self):
        from server.healing.integration_registry import list_operations
        result = list_operations("nonexistent_category")
        assert result == []

    def test_returns_list(self):
        from server.healing.integration_registry import list_operations
        result = list_operations("nas")
        assert isinstance(result, list)


class TestListPlatforms:
    def test_nas_scrub_has_truenas(self):
        from server.healing.integration_registry import list_platforms
        platforms = list_platforms("nas_scrub")
        assert "truenas" in platforms

    def test_nas_scrub_has_2_or_more_platforms(self):
        from server.healing.integration_registry import list_platforms
        platforms = list_platforms("nas_scrub")
        assert len(platforms) >= 2

    def test_unknown_operation_returns_empty(self):
        from server.healing.integration_registry import list_platforms
        result = list_platforms("nonexistent_op")
        assert result == []


class TestListCategories:
    def test_returns_20_or_more_categories(self):
        from server.healing.integration_registry import list_categories
        cats = list_categories()
        assert len(cats) >= 20

    def test_includes_required_categories(self):
        from server.healing.integration_registry import list_categories
        cats = list_categories()
        required = ["nas", "hypervisor", "dns", "media"]
        for cat in required:
            assert cat in cats, f"Missing category: {cat}"

    def test_returns_list(self):
        from server.healing.integration_registry import list_categories
        result = list_categories()
        assert isinstance(result, list)


class TestRegisterHandler:
    def test_register_adds_plugin_handler(self):
        from server.healing.integration_registry import (
            get_integration_handler,
            register_handler,
        )
        config = {"method": "POST", "endpoint": "/api/test", "auth": "bearer"}
        register_handler("test_plugin_op", "test_platform", config)
        result = get_integration_handler("test_plugin_op", "test_platform")
        assert result == config

    def test_register_overwrites_existing(self):
        from server.healing.integration_registry import (
            get_integration_handler,
            register_handler,
        )
        config1 = {"method": "POST", "endpoint": "/api/v1", "auth": "bearer"}
        config2 = {"method": "PUT", "endpoint": "/api/v2", "auth": "session"}
        register_handler("test_overwrite_op", "test_platform", config1)
        register_handler("test_overwrite_op", "test_platform", config2)
        result = get_integration_handler("test_overwrite_op", "test_platform")
        assert result == config2


class TestCategorySpotChecks:
    """Each category must have minimum required number of operations."""

    def _ops(self, category: str) -> list[str]:
        from server.healing.integration_registry import list_operations
        return list_operations(category)

    def test_nas_has_5_or_more(self):
        assert len(self._ops("nas")) >= 5

    def test_hypervisor_has_5_or_more(self):
        assert len(self._ops("hypervisor")) >= 5

    def test_dns_has_4_or_more(self):
        assert len(self._ops("dns")) >= 4

    def test_media_has_4_or_more(self):
        assert len(self._ops("media")) >= 4

    def test_media_management_has_4_or_more(self):
        assert len(self._ops("media_management")) >= 4

    def test_vpn_has_3_or_more(self):
        assert len(self._ops("vpn")) >= 3

    def test_backup_has_4_or_more(self):
        assert len(self._ops("backup")) >= 4

    def test_security_has_3_or_more(self):
        assert len(self._ops("security")) >= 3

    def test_network_hardware_has_4_or_more(self):
        assert len(self._ops("network_hardware")) >= 4

    def test_logging_has_3_or_more(self):
        assert len(self._ops("logging")) >= 3

    def test_database_has_4_or_more(self):
        assert len(self._ops("database")) >= 4

    def test_container_runtime_has_4_or_more(self):
        assert len(self._ops("container_runtime")) >= 4

    def test_reverse_proxy_has_4_or_more(self):
        assert len(self._ops("reverse_proxy")) >= 4

    def test_download_client_has_3_or_more(self):
        assert len(self._ops("download_client")) >= 3

    def test_monitoring_has_3_or_more(self):
        assert len(self._ops("monitoring")) >= 3

    def test_smart_home_has_3_or_more(self):
        assert len(self._ops("smart_home")) >= 3

    def test_identity_auth_has_3_or_more(self):
        assert len(self._ops("identity_auth")) >= 3

    def test_certificate_has_3_or_more(self):
        assert len(self._ops("certificate")) >= 3

    def test_git_devops_has_3_or_more(self):
        assert len(self._ops("git_devops")) >= 3

    def test_mail_has_3_or_more(self):
        assert len(self._ops("mail")) >= 3

    def test_cloud_cdn_has_3_or_more(self):
        assert len(self._ops("cloud_cdn")) >= 3

    def test_power_ups_has_3_or_more(self):
        assert len(self._ops("power_ups")) >= 3

    def test_surveillance_has_3_or_more(self):
        assert len(self._ops("surveillance")) >= 3

    def test_metrics_has_3_or_more(self):
        assert len(self._ops("metrics")) >= 3

    def test_message_queue_has_3_or_more(self):
        assert len(self._ops("message_queue")) >= 3

    def test_photo_management_has_3_or_more(self):
        assert len(self._ops("photo_management")) >= 3

    def test_automation_workflow_has_3_or_more(self):
        assert len(self._ops("automation_workflow")) >= 3

    def test_file_sync_has_3_or_more(self):
        assert len(self._ops("file_sync")) >= 3
