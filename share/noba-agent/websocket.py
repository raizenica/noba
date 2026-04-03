# Copyright (c) 2024-2026 Kevin Van Nieuwenhove. All rights reserved.
# NOBA Command Center — Licensed under Apache 2.0.

"""Minimal RFC 6455 WebSocket client using only Python stdlib."""
from __future__ import annotations

import json
import os
import socket
import urllib.parse


class _WebSocketClient:
    """Minimal RFC 6455 WebSocket client using only Python stdlib."""

    def __init__(self, url: str, headers: dict | None = None):
        self.url = url
        self.headers = headers or {}
        self._sock: socket.socket | None = None
        self._connected = False

    def connect(self) -> None:
        """Perform HTTP Upgrade handshake."""
        import base64

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
            ctx.minimum_version = ssl.TLSVersion.TLSv1_2
            raw = ctx.wrap_socket(raw, server_hostname=host)

        ws_key = base64.b64encode(os.urandom(16)).decode()
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

        resp = b""
        while b"\r\n\r\n" not in resp:
            chunk = raw.recv(4096)
            if not chunk:
                raise ConnectionError("Connection closed during handshake")
            resp += chunk

        status_line = resp.split(b"\r\n")[0]
        if b"101" not in status_line:
            raise ConnectionError(f"WebSocket upgrade failed: {status_line!r}")

        self._sock = raw
        self._connected = True

    def send_json(self, obj: dict) -> None:
        """Send a JSON message as a masked text frame."""
        data = json.dumps(obj).encode()
        self._send_frame(0x1, data)

    def recv_json(self, timeout: float | None = None) -> dict | None:
        """Receive a JSON message. Returns None on timeout or close."""
        if self._sock is None:
            return None
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
            if self._sock is not None and timeout is not None:
                self._sock.settimeout(None)

    def close(self) -> None:
        """Send close frame and shut down."""
        if self._connected:
            try:
                self._send_frame(0x8, b"")
            except Exception:
                pass
            self._connected = False
        if self._sock:
            try:
                self._sock.close()
            except Exception:
                pass
            self._sock = None

    def _send_frame(self, opcode: int, data: bytes) -> None:
        """Send a masked WebSocket frame (RFC 6455 section 5.2)."""
        import struct as _struct

        if self._sock is None:
            raise ConnectionError("Not connected")

        frame = bytearray()
        frame.append(0x80 | opcode)
        length = len(data)
        mask_bit = 0x80

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

    def _recv_frame(self) -> bytes | None:
        """Receive a WebSocket frame, handle control frames transparently."""
        import struct as _struct

        header = self._recv_exact(2)
        if not header:
            return None

        opcode = header[0] & 0x0F
        is_masked = bool(header[1] & 0x80)
        length = header[1] & 0x7F

        if length == 126:
            raw_len = self._recv_exact(2)
            if raw_len is None:
                return None
            length = _struct.unpack("!H", raw_len)[0]
        elif length == 127:
            raw_len = self._recv_exact(8)
            if raw_len is None:
                return None
            length = _struct.unpack("!Q", raw_len)[0]

        if is_masked:
            mask = self._recv_exact(4)
            if mask is None:
                return None
            payload = self._recv_exact(length)
            if payload is None:
                return None
            data = bytearray(b ^ mask[i % 4] for i, b in enumerate(payload))
        else:
            data = self._recv_exact(length)
            if data is None:
                return None

        if opcode == 0x8:  # Close
            self._connected = False
            return None
        if opcode == 0x9:  # Ping -> pong
            self._send_frame(0xA, bytes(data))
            return self._recv_frame()
        if opcode == 0xA:  # Pong -> ignore
            return self._recv_frame()
        return bytes(data)

    def _recv_exact(self, n: int) -> bytes | None:
        """Read exactly n bytes."""
        buf = bytearray()
        while len(buf) < n:
            chunk = self._sock.recv(n - len(buf))
            if not chunk:
                return None
            buf.extend(chunk)
        return bytes(buf)
