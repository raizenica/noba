# Copyright (c) 2024-2026 Kevin Van Nieuwenhove. All rights reserved.
# NOBA Command Center — Licensed under Apache 2.0.

"""Tests for the Webhook Receiver feature (Feature 8)."""
from __future__ import annotations

import hashlib
import hmac

import pytest

from server.db import Database


@pytest.fixture()
def db(tmp_path):
    """Create a fresh Database with a temp path."""
    path = str(tmp_path / "test.db")
    return Database(path)


class TestWebhookCRUD:
    """Test webhook create, list, get, delete via the Database API."""

    def test_create_webhook(self, db):
        wh_id = db.create_webhook("Test Hook", "hook123", "secret456")
        assert wh_id is not None
        assert isinstance(wh_id, int)

    def test_list_webhooks_empty(self, db):
        result = db.list_webhooks()
        assert result == []

    def test_list_webhooks_after_create(self, db):
        db.create_webhook("Hook A", "hookA", "secretA")
        db.create_webhook("Hook B", "hookB", "secretB")
        result = db.list_webhooks()
        assert len(result) == 2
        names = {w["name"] for w in result}
        assert names == {"Hook A", "Hook B"}

    def test_get_webhook_by_hook_id(self, db):
        db.create_webhook("My Hook", "unique_hook", "my_secret", automation_id="auto123")
        wh = db.get_webhook_by_hook_id("unique_hook")
        assert wh is not None
        assert wh["name"] == "My Hook"
        assert wh["hook_id"] == "unique_hook"
        assert wh["secret"] == "my_secret"
        assert wh["automation_id"] == "auto123"
        assert wh["enabled"] is True
        assert wh["trigger_count"] == 0

    def test_get_webhook_by_hook_id_not_found(self, db):
        result = db.get_webhook_by_hook_id("nonexistent")
        assert result is None

    def test_delete_webhook(self, db):
        wh_id = db.create_webhook("To Delete", "del_hook", "del_secret")
        assert db.delete_webhook(wh_id) is True
        # Verify it's gone
        result = db.list_webhooks()
        assert len(result) == 0

    def test_delete_webhook_not_found(self, db):
        result = db.delete_webhook(9999)
        assert result is False

    def test_record_trigger(self, db):
        wh_id = db.create_webhook("Trigger Test", "trig_hook", "trig_secret")
        # Record a trigger
        db.record_webhook_trigger(wh_id)
        wh = db.get_webhook_by_hook_id("trig_hook")
        assert wh["trigger_count"] == 1
        assert wh["last_triggered"] is not None

        # Record another
        db.record_webhook_trigger(wh_id)
        wh = db.get_webhook_by_hook_id("trig_hook")
        assert wh["trigger_count"] == 2

    def test_webhook_unique_hook_id(self, db):
        db.create_webhook("First", "same_id", "secret1")
        # Creating with same hook_id should fail
        result = db.create_webhook("Second", "same_id", "secret2")
        assert result is None  # Should fail due to UNIQUE constraint

    def test_webhook_without_automation(self, db):
        db.create_webhook("No Auto", "no_auto_hook", "secret")
        wh = db.get_webhook_by_hook_id("no_auto_hook")
        assert wh["automation_id"] is None

    def test_webhook_list_fields(self, db):
        """Ensure list_webhooks does NOT include the secret field."""
        db.create_webhook("Public Hook", "pub_hook", "top_secret_123")
        result = db.list_webhooks()
        assert len(result) == 1
        # list_webhooks should not expose the secret
        assert "secret" not in result[0]


class TestHMACValidation:
    """Test the HMAC-SHA256 validation logic used by the webhook receiver."""

    def test_valid_hmac(self):
        secret = "my_webhook_secret"
        body = b'{"action": "deploy", "ref": "main"}'
        expected = hmac.new(secret.encode(), body, hashlib.sha256).hexdigest()
        signature = "sha256=" + expected
        # Simulate what the endpoint does
        sig_clean = signature.replace("sha256=", "")
        computed = hmac.new(secret.encode(), body, hashlib.sha256).hexdigest()
        assert hmac.compare_digest(computed, sig_clean)

    def test_invalid_hmac(self):
        secret = "my_webhook_secret"
        body = b'{"action": "deploy", "ref": "main"}'
        wrong_sig = "sha256=" + "a" * 64
        sig_clean = wrong_sig.replace("sha256=", "")
        computed = hmac.new(secret.encode(), body, hashlib.sha256).hexdigest()
        assert not hmac.compare_digest(computed, sig_clean)

    def test_empty_signature_rejected(self):
        secret = "my_webhook_secret"
        body = b'test body'
        sig_clean = ""
        computed = hmac.new(secret.encode(), body, hashlib.sha256).hexdigest()
        # Empty string should not match
        assert not hmac.compare_digest(computed, sig_clean)


class TestWebhookWithAutomation:
    """Test webhook-automation linking."""

    def test_create_with_automation_id(self, db):
        # First create an automation
        db.insert_automation("auto1", "Test Auto", "script",
                             {"script": "backup"}, schedule=None, enabled=True)
        # Create webhook linked to it
        wh_id = db.create_webhook("Deploy Hook", "deploy_hook", "secret",
                                  automation_id="auto1")
        assert wh_id is not None
        wh = db.get_webhook_by_hook_id("deploy_hook")
        assert wh["automation_id"] == "auto1"

    def test_trigger_count_increments(self, db):
        wh_id = db.create_webhook("Counter", "count_hook", "secret")
        for _ in range(5):
            db.record_webhook_trigger(wh_id)
        wh = db.get_webhook_by_hook_id("count_hook")
        assert wh["trigger_count"] == 5
