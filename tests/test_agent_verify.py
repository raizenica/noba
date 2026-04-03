# Copyright (c) 2024-2026 Kevin Van Nieuwenhove. All rights reserved.
# NOBA Command Center — Licensed under Apache 2.0.

"""Tests for healing.agent_verify: ask agent to confirm target state."""
from __future__ import annotations

from unittest.mock import patch


class TestVerifyResult:
    def test_result_fields(self):
        from server.healing.agent_verify import VerifyResult
        r = VerifyResult(agent_reachable=True, confirmed_down=True, detail="stopped")
        assert r.agent_reachable
        assert r.confirmed_down
        assert r.detail == "stopped"

    def test_default_values(self):
        from server.healing.agent_verify import VerifyResult
        r = VerifyResult()
        assert r.agent_reachable is False
        assert r.confirmed_down is None
        assert r.detail == ""


class TestVerifyTargetWithAgent:
    def test_agent_confirms_down(self):
        from server.healing.agent_verify import verify_target_with_agent
        with patch("server.healing.agent_verify._query_agent") as mock_q:
            mock_q.return_value = {"status": "down", "detail": "container exited"}
            result = verify_target_with_agent("host1", "plex")
            assert result.agent_reachable is True
            assert result.confirmed_down is True
            assert result.detail == "container exited"

    def test_agent_confirms_up(self):
        from server.healing.agent_verify import verify_target_with_agent
        with patch("server.healing.agent_verify._query_agent") as mock_q:
            mock_q.return_value = {"status": "up", "detail": "running"}
            result = verify_target_with_agent("host1", "plex")
            assert result.agent_reachable is True
            assert result.confirmed_down is False

    def test_agent_unreachable(self):
        from server.healing.agent_verify import verify_target_with_agent
        with patch("server.healing.agent_verify._query_agent") as mock_q:
            mock_q.return_value = None
            result = verify_target_with_agent("host1", "plex")
            assert result.agent_reachable is False
            assert result.confirmed_down is None

    def test_agent_returns_unknown_status(self):
        from server.healing.agent_verify import verify_target_with_agent
        with patch("server.healing.agent_verify._query_agent") as mock_q:
            mock_q.return_value = {"status": "unknown", "detail": "check failed"}
            result = verify_target_with_agent("host1", "plex")
            assert result.agent_reachable is True
            assert result.confirmed_down is None  # unknown = can't confirm either way

    def test_agent_returns_error(self):
        from server.healing.agent_verify import verify_target_with_agent
        with patch("server.healing.agent_verify._query_agent") as mock_q:
            mock_q.side_effect = Exception("connection refused")
            result = verify_target_with_agent("host1", "plex")
            assert result.agent_reachable is False
            assert result.confirmed_down is None
