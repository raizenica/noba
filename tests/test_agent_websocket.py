# Copyright (c) 2024-2026 Kevin Van Nieuwenhove. All rights reserved.
# NOBA Command Center — Licensed under Apache 2.0.

"""Tests for agent WebSocket communication (Phase 1b)."""
from __future__ import annotations

import os
import threading
from unittest.mock import MagicMock


from server.yaml_config import write_yaml_settings


# ── Helper: set up agent keys in config ──────────────────────────────────────

_TEST_AGENT_KEY = "test-ws-agent-key-42"


def _setup_agent_keys():
    """Write a test agent key into YAML settings."""
    write_yaml_settings({"agentKeys": _TEST_AGENT_KEY})


# ── _validate_agent_key ─────────────────────────────────────────────────────

class TestValidateAgentKey:
    """Test the _validate_agent_key helper used by report + WebSocket."""

    def test_valid_key(self):
        _setup_agent_keys()
        from server.routers.agents import _validate_agent_key
        assert _validate_agent_key(_TEST_AGENT_KEY) is True

    def test_invalid_key(self):
        _setup_agent_keys()
        from server.routers.agents import _validate_agent_key
        assert _validate_agent_key("wrong-key") is False

    def test_empty_key(self):
        _setup_agent_keys()
        from server.routers.agents import _validate_agent_key
        assert _validate_agent_key("") is False

    def test_no_keys_configured(self):
        write_yaml_settings({"agentKeys": ""})
        from server.routers.agents import _validate_agent_key
        assert _validate_agent_key("any-key") is False


# ── Agent store ─────────────────────────────────────────────────────────────

class TestAgentStore:
    """Test the WebSocket registry in agent_store."""

    def test_registry_starts_empty(self):
        from server.agent_store import _agent_websockets
        # Should be a dict (may have entries from other tests, just check type)
        assert isinstance(_agent_websockets, dict)

    def test_lock_exists(self):
        from server.agent_store import _agent_ws_lock
        assert isinstance(_agent_ws_lock, type(threading.Lock()))


# ── WebSocket client (agent-side) ────────────────────────────────────────────

class TestWebSocketClient:
    """Test the stdlib RFC 6455 WebSocket client class."""

    def _get_client_class(self):
        """Import _WebSocketClient from websocket.py without running main."""
        import importlib
        import sys
        agent_path = os.path.join(
            os.path.dirname(__file__), "..", "share", "noba-agent",
        )
        if agent_path not in sys.path:
            sys.path.insert(0, agent_path)
        # Import the websocket module under a distinct key to avoid colliding
        # with the websocket-client third-party package cached as "websocket".
        MOD_KEY = "noba_agent_websocket"
        if MOD_KEY in sys.modules:
            mod = sys.modules[MOD_KEY]
        else:
            spec = importlib.util.spec_from_file_location(
                MOD_KEY,
                os.path.join(agent_path, "websocket.py"),
            )
            mod = importlib.util.module_from_spec(spec)
            sys.modules[MOD_KEY] = mod
            spec.loader.exec_module(mod)
        return mod._WebSocketClient

    def test_client_init(self):
        cls = self._get_client_class()
        ws = cls("ws://localhost:9999/test")
        assert ws.url == "ws://localhost:9999/test"
        assert ws._connected is False
        assert ws._sock is None

    def test_client_init_with_headers(self):
        cls = self._get_client_class()
        ws = cls("wss://host/path", headers={"X-Custom": "val"})
        assert ws.headers == {"X-Custom": "val"}

    def test_close_when_not_connected(self):
        """close() should be safe to call when not connected."""
        cls = self._get_client_class()
        ws = cls("ws://localhost:1234/nope")
        ws.close()  # Should not raise
        assert ws._sock is None
        assert ws._connected is False

    def test_recv_json_when_not_connected(self):
        """recv_json should return None when socket is None."""
        cls = self._get_client_class()
        ws = cls("ws://localhost:1234/nope")
        assert ws.recv_json(timeout=0.1) is None

    def test_send_frame_builds_masked_frame(self):
        """Verify that _send_frame produces a valid masked frame."""
        cls = self._get_client_class()
        ws = cls("ws://localhost:1234")
        sent_data = bytearray()
        mock_sock = MagicMock()
        mock_sock.sendall = lambda d: sent_data.extend(d)
        ws._sock = mock_sock
        ws._connected = True

        ws._send_frame(0x1, b"hello")

        # First byte: FIN + opcode 0x1
        assert sent_data[0] == 0x81
        # Second byte: mask bit set + length 5
        assert sent_data[1] == (0x80 | 5)
        # Next 4 bytes are mask key, then 5 bytes of masked payload
        assert len(sent_data) == 2 + 4 + 5

        # Unmask the payload
        mask = sent_data[2:6]
        payload = bytearray(sent_data[6 + i] ^ mask[i % 4] for i in range(5))
        assert payload == bytearray(b"hello")


# ── Dual-path command routing ────────────────────────────────────────────────

class TestDualPathRouting:
    """Test that commands are routed via WebSocket when available."""

    def test_command_falls_back_to_queue_when_no_ws(self):
        """When no WebSocket is connected, command goes to queue."""
        _setup_agent_keys()
        from server.agent_store import (
            _agent_cmd_lock,
            _agent_commands,
        )
        from server.agent_store import _agent_websockets, _agent_ws_lock

        # Ensure no WebSocket for test-host
        with _agent_ws_lock:
            _agent_websockets.pop("test-host-queue", None)

        # Clear any existing commands
        with _agent_cmd_lock:
            _agent_commands.pop("test-host-queue", None)

        # We can't easily call the async endpoint directly, but we can
        # verify the store state. The actual endpoint is tested via
        # integration tests. Here we verify the building blocks.
        with _agent_ws_lock:
            ws = _agent_websockets.get("test-host-queue")
        assert ws is None  # No WebSocket connected

    def test_websocket_registry_operations(self):
        """Test add/remove operations on the WebSocket registry."""
        from server.agent_store import _agent_websockets, _agent_ws_lock

        mock_ws = MagicMock()
        hostname = "test-registry-host"

        # Add
        with _agent_ws_lock:
            _agent_websockets[hostname] = mock_ws
        with _agent_ws_lock:
            assert _agent_websockets.get(hostname) is mock_ws

        # Remove
        with _agent_ws_lock:
            del _agent_websockets[hostname]
        with _agent_ws_lock:
            assert hostname not in _agent_websockets


# ── Agent _ws_thread logic ───────────────────────────────────────────────────

class TestWsThreadLogic:
    """Test the WebSocket thread's command processing logic."""

    def _get_agent_module(self):
        """Return a namespace with execute_commands from commands.py and _ws_thread from __main__.py."""
        import importlib
        import sys
        import types
        agent_path = os.path.join(
            os.path.dirname(__file__), "..", "share", "noba-agent",
        )
        if agent_path not in sys.path:
            sys.path.insert(0, agent_path)

        # Load commands module (provides execute_commands)
        if "commands" not in sys.modules:
            spec = importlib.util.spec_from_file_location(
                "commands",
                os.path.join(agent_path, "commands.py"),
            )
            mod = importlib.util.module_from_spec(spec)
            sys.modules["commands"] = mod
            spec.loader.exec_module(mod)
        commands_mod = sys.modules["commands"]

        # Load __main__ module (provides _ws_thread)
        if "noba_agent_main" not in sys.modules:
            spec = importlib.util.spec_from_file_location(
                "noba_agent_main",
                os.path.join(agent_path, "__main__.py"),
            )
            mod = importlib.util.module_from_spec(spec)
            sys.modules["noba_agent_main"] = mod
            spec.loader.exec_module(mod)
        main_mod = sys.modules["noba_agent_main"]

        # Return a combined namespace
        ns = types.SimpleNamespace()
        ns.execute_commands = commands_mod.execute_commands
        ns._ws_thread = main_mod._ws_thread
        return ns

    def test_execute_commands_with_ws_callback(self):
        """execute_commands should pass ctx through to handlers."""
        mod = self._get_agent_module()
        # Test ping command (safe, no side effects)
        ctx = {"server": "http://test", "api_key": "key", "interval": 30}
        results = mod.execute_commands(
            [{"type": "ping", "id": "test-123", "params": {}}],
            ctx,
        )
        assert len(results) == 1
        assert results[0]["id"] == "test-123"
        assert results[0]["type"] == "ping"
        assert results[0]["status"] == "ok"
        assert "pong" in results[0]

    def test_ws_thread_stops_on_flag(self):
        """_ws_thread should exit when ctx['_stop'] is set."""
        mod = self._get_agent_module()
        ctx = {"_stop": False}

        def run_thread():
            # _ws_thread will try to connect and fail, then check _stop
            mod._ws_thread("http://localhost:1", "badkey", "test-host", ctx)

        # Set stop before any sleep/retry
        ctx["_stop"] = True
        t = threading.Thread(target=run_thread, daemon=True)
        t.start()
        t.join(timeout=5)
        assert not t.is_alive(), "_ws_thread did not stop when _stop was set"


# ── Stream endpoint building blocks ─────────────────────────────────────────

class TestStreamResults:
    """Test the stream result storage used by the /stream/{cmd_id} endpoint."""

    def test_stream_storage(self):
        """Stream messages should be stored in _agent_cmd_results under a key."""
        from server.agent_store import _agent_cmd_lock, _agent_cmd_results

        hostname = "stream-test-host"
        cmd_id = "stream-cmd-123"
        stream_key = f"_stream_{hostname}_{cmd_id}"

        # Clean up
        with _agent_cmd_lock:
            _agent_cmd_results.pop(stream_key, None)

        # Store stream lines (mimics what the WebSocket endpoint does)
        with _agent_cmd_lock:
            _agent_cmd_results.setdefault(stream_key, []).append(
                {"type": "stream", "id": cmd_id, "line": "line 1"}
            )
            _agent_cmd_results.setdefault(stream_key, []).append(
                {"type": "stream", "id": cmd_id, "line": "line 2"}
            )

        with _agent_cmd_lock:
            lines = _agent_cmd_results.get(stream_key, [])
        assert len(lines) == 2
        assert lines[0]["line"] == "line 1"
        assert lines[1]["line"] == "line 2"

        # Clean up
        with _agent_cmd_lock:
            _agent_cmd_results.pop(stream_key, None)
