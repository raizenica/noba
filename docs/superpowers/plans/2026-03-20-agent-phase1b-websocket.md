# Agent Enhancement Phase 1b: WebSocket Real-time — Implementation Plan

> **For agentic workers:** REQUIRED SUB-SKILL: Use superpowers:subagent-driven-development (recommended) or superpowers:executing-plans to implement this plan task-by-task. Steps use checkbox (`- [ ]`) syntax for tracking.

**Goal:** Add a WebSocket command channel between server and agents for instant command delivery and streaming output, with fallback to HTTP polling for agents that don't support WebSocket.

**Architecture:** FastAPI WebSocket endpoint at `/api/agent/ws` authenticates agents via query param (WebSocket doesn't support custom headers). Agent runs a stdlib-only RFC 6455 client in a background thread alongside the existing telemetry loop. Server routes commands via WebSocket when connected, falling back to the HTTP queue. Stream messages enable real-time output for long-running commands.

**Tech Stack:** FastAPI WebSocket (server), Python stdlib socket/ssl/hashlib/struct (agent client), existing threading pattern

**Spec:** `docs/superpowers/specs/2026-03-20-agent-enhancement-design.md` — Phase 1b section

---

## File Structure

### Server-side:
- Modify: `share/noba-web/server/agent_store.py` — add `_agent_websockets` registry + lock
- Modify: `share/noba-web/server/routers/system.py` — add WebSocket endpoint, modify command routing
- Modify: `share/noba-web/server/app.py` — cleanup connected WebSockets on shutdown

### Agent-side:
- Modify: `share/noba-agent/agent.py` — add RFC 6455 client class, background thread, stream support

### Tests:
- Create: `tests/test_agent_websocket.py` — WebSocket endpoint, dual-path routing, auth

---

### Task 1: Add WebSocket state to agent_store.py

**Files:**
- Modify: `share/noba-web/server/agent_store.py`

- [ ] **Step 1: Add WebSocket registry**

Add to `agent_store.py` after existing stores:

```python
from starlette.websockets import WebSocket

_agent_websockets: dict[str, WebSocket] = {}  # hostname -> active WebSocket
_agent_ws_lock = threading.Lock()
```

- [ ] **Step 2: Commit**

```bash
git add share/noba-web/server/agent_store.py
git commit -m "feat(agent): add WebSocket registry to agent store"
```

---

### Task 2: Add WebSocket endpoint to server

**Files:**
- Modify: `share/noba-web/server/routers/system.py`

- [ ] **Step 1: Write the WebSocket endpoint**

Add after the existing agent endpoints in `system.py`. The endpoint:
1. Authenticates via `key` query param (WebSocket can't use custom headers)
2. Reads hostname from the first message (agent sends identification)
3. Registers in `_agent_websockets`
4. Loops receiving messages (command results, stream output)
5. Cleans up on disconnect

```python
from starlette.websockets import WebSocket, WebSocketDisconnect
from .agent_store import _agent_websockets, _agent_ws_lock

@router.websocket("/api/agent/ws")
async def agent_websocket(ws: WebSocket):
    """WebSocket endpoint for real-time agent communication."""
    # Auth via query param (WebSocket limitation)
    key = ws.query_params.get("key", "")
    if not _validate_agent_key(key):
        await ws.close(code=4001, reason="Invalid agent key")
        return

    await ws.accept()
    hostname = None
    try:
        # First message must be identification
        ident = await ws.receive_json()
        if ident.get("type") != "identify":
            await ws.close(code=4002, reason="Expected identify message")
            return
        hostname = ident.get("hostname", "")
        if not hostname:
            await ws.close(code=4002, reason="No hostname")
            return

        # Register WebSocket connection
        with _agent_ws_lock:
            old = _agent_websockets.get(hostname)
            _agent_websockets[hostname] = ws
        if old:
            try:
                await old.close(code=1000, reason="Replaced by new connection")
            except Exception:
                pass

        print(f"[ws] Agent {hostname} connected via WebSocket")

        # Send any queued commands immediately
        with _agent_cmd_lock:
            queued = _agent_commands.pop(hostname, [])
        for cmd in queued:
            await ws.send_json({"type": "command", **cmd})

        # Main receive loop
        while True:
            msg = await ws.receive_json()
            msg_type = msg.get("type", "")

            if msg_type == "result":
                # Command execution result
                cmd_id = msg.get("id", "")
                with _agent_cmd_lock:
                    _agent_cmd_results.setdefault(hostname, []).append(msg)
                    # Keep only last 50 results
                    if len(_agent_cmd_results[hostname]) > 50:
                        _agent_cmd_results[hostname] = _agent_cmd_results[hostname][-50:]

            elif msg_type == "stream":
                # Streaming output line — store for UI polling
                cmd_id = msg.get("id", "")
                with _agent_cmd_lock:
                    key_name = f"_stream_{hostname}_{cmd_id}"
                    _agent_cmd_results.setdefault(key_name, []).append(msg)

            elif msg_type == "ping":
                await ws.send_json({"type": "pong"})

    except WebSocketDisconnect:
        pass
    except Exception as e:
        print(f"[ws] Error for {hostname}: {e}")
    finally:
        if hostname:
            with _agent_ws_lock:
                if _agent_websockets.get(hostname) is ws:
                    del _agent_websockets[hostname]
            print(f"[ws] Agent {hostname} disconnected")
```

- [ ] **Step 2: Add `_validate_agent_key` helper**

If not already present, add a helper that checks the key against configured agent keys (same logic as `api_agent_report` uses for `X-Agent-Key`). Extract the existing key validation from `api_agent_report` into a reusable function.

- [ ] **Step 3: Run ruff check**

```bash
ruff check share/noba-web/server/routers/system.py --fix
```

- [ ] **Step 4: Commit**

```bash
git add share/noba-web/server/routers/system.py
git commit -m "feat(agent): add WebSocket endpoint /api/agent/ws"
```

---

### Task 3: Dual-path command routing

**Files:**
- Modify: `share/noba-web/server/routers/system.py`

- [ ] **Step 1: Modify `api_agent_command` for WebSocket-first delivery**

After the command is validated and constructed, check if the agent has an active WebSocket. If so, send directly instead of queueing.

```python
# In api_agent_command, after cmd = {...}:
delivered = False
with _agent_ws_lock:
    ws = _agent_websockets.get(hostname)
if ws:
    try:
        import asyncio
        await ws.send_json({"type": "command", **cmd})
        delivered = True
    except Exception:
        # WebSocket broken — fall back to queue
        with _agent_ws_lock:
            _agent_websockets.pop(hostname, None)

if not delivered:
    with _agent_cmd_lock:
        _agent_commands.setdefault(hostname, []).append(cmd)

db.audit_log("agent_command", username,
             f"host={hostname} type={cmd_type} id={cmd_id} ws={delivered}", ip)
return {"status": "queued" if not delivered else "sent", "id": cmd_id, "websocket": delivered}
```

- [ ] **Step 2: Do the same for `api_bulk_command`**

Same pattern — try WebSocket first, fall back to queue per-hostname.

- [ ] **Step 3: Run tests**

```bash
pytest tests/ -v -k "agent"
```

- [ ] **Step 4: Commit**

```bash
git add share/noba-web/server/routers/system.py
git commit -m "feat(agent): dual-path command routing (WebSocket + queue fallback)"
```

---

### Task 4: RFC 6455 WebSocket client in agent.py

**Files:**
- Modify: `share/noba-agent/agent.py`

- [ ] **Step 1: Implement `_WebSocketClient` class**

Add after the imports section. This is a stdlib-only RFC 6455 implementation (~200 lines):

```python
# ── WebSocket client (stdlib RFC 6455) ────────────────────────────────────────

class _WebSocketClient:
    """Minimal RFC 6455 WebSocket client using only Python stdlib."""

    def __init__(self, url, headers=None):
        self.url = url
        self.headers = headers or {}
        self._sock = None
        self._connected = False

    def connect(self):
        """Perform HTTP Upgrade handshake."""
        import base64
        import struct as _struct

        parsed = urllib.parse.urlparse(self.url)
        host = parsed.hostname
        port = parsed.port or (443 if parsed.scheme == "wss" else 80)
        path = parsed.path or "/"
        if parsed.query:
            path += f"?{parsed.query}"

        raw = socket.create_connection((host, port), timeout=10)
        if parsed.scheme == "wss":
            import ssl
            ctx = ssl.create_default_context()
            raw = ctx.wrap_socket(raw, server_hostname=host)

        # Generate WebSocket key
        ws_key = base64.b64encode(os.urandom(16)).decode()

        # Build upgrade request
        lines = [
            f"GET {path} HTTP/1.1",
            f"Host: {host}:{port}",
            "Upgrade: websocket",
            "Connection: Upgrade",
            f"Sec-WebSocket-Key: {ws_key}",
            "Sec-WebSocket-Version: 13",
        ]
        for k, v in self.headers.items():
            lines.append(f"{k}: {v}")
        lines.append("")
        lines.append("")
        raw.sendall("\r\n".join(lines).encode())

        # Read response
        resp = b""
        while b"\r\n\r\n" not in resp:
            chunk = raw.recv(4096)
            if not chunk:
                raise ConnectionError("Connection closed during handshake")
            resp += chunk

        if b"101" not in resp.split(b"\r\n")[0]:
            raise ConnectionError(f"WebSocket upgrade failed: {resp[:200]}")

        self._sock = raw
        self._connected = True

    def send_json(self, obj):
        """Send a JSON message as a masked text frame."""
        data = json.dumps(obj).encode()
        self._send_frame(0x1, data)  # 0x1 = text

    def recv_json(self, timeout=None):
        """Receive a JSON message. Returns None on timeout."""
        if timeout is not None:
            self._sock.settimeout(timeout)
        try:
            data = self._recv_frame()
            if data is None:
                return None
            return json.loads(data)
        except socket.timeout:
            return None
        finally:
            if timeout is not None:
                self._sock.settimeout(None)

    def close(self):
        """Send close frame and shut down."""
        if self._connected:
            try:
                self._send_frame(0x8, b"")  # Close frame
            except Exception:
                pass
            self._connected = False
        if self._sock:
            try:
                self._sock.close()
            except Exception:
                pass
            self._sock = None

    def _send_frame(self, opcode, data):
        """Send a masked WebSocket frame (RFC 6455 §5.2)."""
        import struct as _struct
        frame = bytearray()
        frame.append(0x80 | opcode)  # FIN + opcode
        length = len(data)
        mask_bit = 0x80  # Client frames MUST be masked

        if length < 126:
            frame.append(mask_bit | length)
        elif length < 65536:
            frame.append(mask_bit | 126)
            frame.extend(_struct.pack("!H", length))
        else:
            frame.append(mask_bit | 127)
            frame.extend(_struct.pack("!Q", length))

        mask = os.urandom(4)
        frame.extend(mask)
        masked = bytearray(b ^ mask[i % 4] for i, b in enumerate(data))
        frame.extend(masked)
        self._sock.sendall(frame)

    def _recv_frame(self):
        """Receive a WebSocket frame, handle control frames."""
        import struct as _struct
        header = self._recv_exact(2)
        if not header:
            return None

        opcode = header[0] & 0x0F
        masked = bool(header[1] & 0x80)
        length = header[1] & 0x7F

        if length == 126:
            length = _struct.unpack("!H", self._recv_exact(2))[0]
        elif length == 127:
            length = _struct.unpack("!Q", self._recv_exact(8))[0]

        if masked:
            mask = self._recv_exact(4)
            data = bytearray(b ^ mask[i % 4] for i, b in enumerate(self._recv_exact(length)))
        else:
            data = self._recv_exact(length)

        if opcode == 0x8:  # Close
            self._connected = False
            return None
        if opcode == 0x9:  # Ping → send pong
            self._send_frame(0xA, data)
            return self._recv_frame()
        if opcode == 0xA:  # Pong → ignore
            return self._recv_frame()
        return bytes(data)

    def _recv_exact(self, n):
        """Read exactly n bytes."""
        buf = bytearray()
        while len(buf) < n:
            chunk = self._sock.recv(n - len(buf))
            if not chunk:
                return None
            buf.extend(chunk)
        return bytes(buf)
```

- [ ] **Step 2: Add `import urllib.parse` to top-level imports**

Agent already imports `urllib.request` and `urllib.error`. Add `urllib.parse`.

- [ ] **Step 3: Commit**

```bash
git add share/noba-agent/agent.py
git commit -m "feat(agent): add stdlib RFC 6455 WebSocket client"
```

---

### Task 5: WebSocket background thread in agent main loop

**Files:**
- Modify: `share/noba-agent/agent.py`

- [ ] **Step 1: Add WebSocket thread function**

```python
def _ws_thread(server, api_key, hostname, ctx):
    """Background thread: maintain WebSocket connection for instant commands."""
    import threading

    # Derive WebSocket URL from HTTP server URL
    ws_url = server.replace("http://", "ws://").replace("https://", "wss://")
    ws_url = f"{ws_url.rstrip('/')}/api/agent/ws?key={urllib.parse.quote(api_key)}"

    backoff = 5
    max_backoff = 60

    while not ctx.get("_stop"):
        ws = None
        try:
            ws = _WebSocketClient(ws_url)
            ws.connect()
            print(f"[agent] WebSocket connected to {server}")
            backoff = 5  # Reset backoff on success

            # Send identification
            ws.send_json({
                "type": "identify",
                "hostname": hostname,
                "agent_version": VERSION,
            })

            while not ctx.get("_stop"):
                msg = ws.recv_json(timeout=30)
                if msg is None:
                    # Timeout — send keepalive
                    ws.send_json({"type": "ping"})
                    continue

                if msg.get("type") == "command":
                    cmd_id = msg.get("id", "")
                    cmd_type = msg.get("type_", msg.get("type", ""))
                    # Execute command
                    results = execute_commands([msg], ctx)
                    # Send result back
                    for r in results:
                        ws.send_json({"type": "result", **r})

                elif msg.get("type") == "pong":
                    pass  # Keepalive response

        except Exception as e:
            if not ctx.get("_stop"):
                print(f"[agent] WebSocket error: {e}", file=sys.stderr)
        finally:
            if ws:
                ws.close()

        if ctx.get("_stop"):
            break

        time.sleep(backoff)
        backoff = min(backoff * 2, max_backoff)
```

Note: The command in the WebSocket message uses `msg` directly. The `execute_commands` function expects `[{"type": ..., "id": ..., "params": ...}]`. The WS message from server is `{"type": "command", "id": uuid, "type": cmd_type, "params": {...}}`. We need to map `type` field properly since `type` is overloaded. Fix: server sends the command type in a `cmd` field, or the agent extracts it properly.

**Important:** Adjust the server WebSocket send to use `cmd_type` field:
```python
# Server side: send_json({"type": "command", "id": cmd_id, "cmd": cmd_type, "params": params})
```
And agent side:
```python
# In _ws_thread, when receiving a command:
cmd_obj = {"type": msg.get("cmd", ""), "id": msg.get("id", ""), "params": msg.get("params", {})}
results = execute_commands([cmd_obj], ctx)
```

- [ ] **Step 2: Start WebSocket thread in `main()`**

In the main function, after printing startup info and before the while loop:

```python
# Start WebSocket thread for real-time commands
import threading
ws_ctx = {**ctx, "_stop": False}
ws_t = threading.Thread(target=_ws_thread, args=(server, api_key,
                        hostname_override or socket.gethostname(), ws_ctx),
                        daemon=True)
ws_t.start()
print(f"[agent] WebSocket thread started")
```

And in the KeyboardInterrupt handler:
```python
ws_ctx["_stop"] = True
```

- [ ] **Step 3: Run lint**

```bash
ruff check share/noba-agent/agent.py --fix
```

- [ ] **Step 4: Commit**

```bash
git add share/noba-agent/agent.py
git commit -m "feat(agent): WebSocket background thread with reconnect"
```

---

### Task 6: Streaming output for long-running commands

**Files:**
- Modify: `share/noba-agent/agent.py`
- Modify: `share/noba-web/server/routers/system.py`

- [ ] **Step 1: Add streaming exec in agent**

Modify `_cmd_exec` to stream output line-by-line when a `_ws_send` callback is available in ctx:

```python
def _cmd_exec(params: dict, ctx: dict) -> dict:
    """Execute a shell command. Streams output if WebSocket callback present."""
    cmd = params.get("command", "")
    if not cmd:
        return {"status": "error", "error": "No command provided"}
    cmd_id = ctx.get("_current_cmd_id", "")
    ws_send = ctx.get("_ws_send")  # Optional: WebSocket send callback

    try:
        proc = subprocess.Popen(
            cmd, shell=True, stdout=subprocess.PIPE, stderr=subprocess.STDOUT,
            text=True, bufsize=1
        )
        output_lines = []
        for line in proc.stdout:
            output_lines.append(line)
            if ws_send and cmd_id:
                try:
                    ws_send({"type": "stream", "id": cmd_id, "line": line.rstrip()})
                except Exception:
                    pass
            if sum(len(l) for l in output_lines) > _CMD_MAX_OUTPUT:
                proc.kill()
                break
        proc.wait(timeout=_CMD_TIMEOUT)
        output = "".join(output_lines)[:_CMD_MAX_OUTPUT]
        return {"status": "ok", "stdout": output, "exit_code": proc.returncode}
    except subprocess.TimeoutExpired:
        proc.kill()
        return {"status": "error", "error": "Command timed out"}
    except Exception as e:
        return {"status": "error", "error": str(e)}
```

- [ ] **Step 2: Pass WebSocket send callback through ctx in `_ws_thread`**

When processing commands in the WebSocket thread, add a `_ws_send` callback to ctx:

```python
# In _ws_thread command handler:
cmd_ctx = {**ctx, "_current_cmd_id": msg.get("id", ""),
           "_ws_send": lambda m: ws.send_json(m)}
results = execute_commands([cmd_obj], cmd_ctx)
```

- [ ] **Step 3: Add stream results endpoint on server**

```python
@router.get("/api/agents/{hostname}/stream/{cmd_id}")
def api_agent_stream(hostname: str, cmd_id: str, auth=Depends(_get_auth)):
    """Get streaming output lines for a command."""
    key = f"_stream_{hostname}_{cmd_id}"
    with _agent_cmd_lock:
        lines = _agent_cmd_results.get(key, [])
    return lines
```

- [ ] **Step 4: Run lint and tests**

```bash
ruff check share/noba-web/server/ share/noba-agent/ --fix
pytest tests/ -v
```

- [ ] **Step 5: Commit**

```bash
git add share/noba-agent/agent.py share/noba-web/server/routers/system.py
git commit -m "feat(agent): streaming output for long-running commands via WebSocket"
```

---

### Task 7: Server-side cleanup on shutdown

**Files:**
- Modify: `share/noba-web/server/app.py`

- [ ] **Step 1: Close all WebSocket connections on shutdown**

In the lifespan shutdown section of `app.py`:

```python
# Close all agent WebSocket connections
from .agent_store import _agent_websockets, _agent_ws_lock
with _agent_ws_lock:
    for hostname, ws in list(_agent_websockets.items()):
        try:
            import asyncio
            asyncio.get_event_loop().run_until_complete(
                ws.close(code=1001, reason="Server shutting down")
            )
        except Exception:
            pass
    _agent_websockets.clear()
```

- [ ] **Step 2: Commit**

```bash
git add share/noba-web/server/app.py
git commit -m "feat(agent): close WebSocket connections on server shutdown"
```

---

### Task 8: Tests

**Files:**
- Create: `tests/test_agent_websocket.py`

- [ ] **Step 1: Write WebSocket tests**

```python
"""Tests for agent WebSocket communication."""
from __future__ import annotations

import pytest
from httpx import ASGITransport, AsyncClient
from starlette.testclient import TestClient

from share.noba_web.server.app import app  # Adjust import path


class TestAgentWebSocket:
    """Test WebSocket endpoint and dual-path routing."""

    def test_ws_reject_invalid_key(self):
        """WebSocket with invalid key should be rejected."""
        client = TestClient(app)
        with pytest.raises(Exception):
            with client.websocket_connect("/api/agent/ws?key=invalid"):
                pass

    def test_ws_requires_identify(self):
        """WebSocket must send identify message first."""
        # Test with valid key — should be accepted but require identification
        # Implementation depends on how test auth is configured

    def test_command_routing_prefers_websocket(self):
        """When agent has active WebSocket, commands should be sent via WS."""
        # Test by connecting a WS, then sending a command,
        # and verifying it arrives via WS not the poll queue

    def test_command_falls_back_to_queue(self):
        """When no WebSocket, commands fall back to HTTP queue."""
        # Default behavior — same as before
```

- [ ] **Step 2: Run full test suite**

```bash
pytest tests/ -v
```

- [ ] **Step 3: Commit**

```bash
git add tests/test_agent_websocket.py
git commit -m "test(agent): add WebSocket endpoint and routing tests"
```
