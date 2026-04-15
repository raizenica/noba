# Copyright (c) 2024-2026 Kevin Van Nieuwenhove. All rights reserved.
# NOBA Command Center — Licensed under Apache 2.0.

"""PTY session management for interactive terminal sessions."""
from __future__ import annotations

import os
import signal
import subprocess
import threading

from utils import _PLATFORM

_pty_sessions: dict[str, dict] = {}
_pty_lock = threading.Lock()


def _pty_find_restricted_user() -> str | None:
    """Find a non-root user to drop to for operator sessions (Linux)."""
    import pwd
    for name in ("noba-agent", "noba", "nobody"):
        try:
            pwd.getpwnam(name)
            return name
        except KeyError:
            continue
    return None


def _pty_open(session_id: str, ws_send, cols: int = 80, rows: int = 24,
              role: str = "admin") -> dict:
    """Open a PTY shell session. Operators get a restricted shell."""
    with _pty_lock:
        if session_id in _pty_sessions:
            return {"type": "pty_error", "session": session_id, "error": "Session already exists"}

    is_restricted = role != "admin"

    if _PLATFORM == "windows":
        shell_cmd = ["powershell.exe", "-NoProfile"]
        if is_restricted:
            shell_cmd = [
                "powershell.exe", "-NoProfile", "-Command",
                "$ExecutionContext.SessionState.LanguageMode = 'ConstrainedLanguage'; "
                "Write-Host '[ Restricted session — ConstrainedLanguage mode ]' -ForegroundColor Yellow; "
                "Set-Location $env:USERPROFILE; "
                "powershell.exe -NoProfile",
            ]
        try:
            proc = subprocess.Popen(
                shell_cmd,
                stdin=subprocess.PIPE,
                stdout=subprocess.PIPE,
                stderr=subprocess.STDOUT,
                bufsize=0,
                creationflags=subprocess.CREATE_NEW_PROCESS_GROUP if hasattr(subprocess, "CREATE_NEW_PROCESS_GROUP") else 0,
            )
        except Exception as e:
            return {"type": "pty_error", "session": session_id, "error": str(e)}

        def reader():
            try:
                while True:
                    data = proc.stdout.read(4096)
                    if not data:
                        break
                    try:
                        ws_send({"type": "pty_output", "session": session_id, "data": data.decode("utf-8", errors="replace")})
                    except Exception:
                        break
            except Exception:
                pass
            finally:
                ws_send({"type": "pty_exit", "session": session_id, "code": proc.poll() or 0})
                with _pty_lock:
                    _pty_sessions.pop(session_id, None)

        t = threading.Thread(target=reader, daemon=True, name=f"pty-{session_id}")
        t.start()

        with _pty_lock:
            _pty_sessions[session_id] = {"proc": proc, "master_fd": None, "reader": t, "platform": "windows"}

    else:
        import pty as pty_mod
        import fcntl
        import struct
        import termios

        master_fd, slave_fd = pty_mod.openpty()

        winsize = struct.pack("HHHH", rows, cols, 0, 0)
        fcntl.ioctl(slave_fd, termios.TIOCSWINSZ, winsize)

        env = os.environ.copy()
        env["TERM"] = "xterm-256color"
        env["COLUMNS"] = str(cols)
        env["LINES"] = str(rows)

        if is_restricted:
            restricted_user = _pty_find_restricted_user()
            if restricted_user:
                shell_cmd = ["su", "-", restricted_user, "-s", "/bin/bash"]
                env["HOME"] = f"/home/{restricted_user}" if restricted_user != "nobody" else "/tmp"
            else:
                shell_cmd = ["/bin/bash", "--restricted"]
                env["PS1"] = "[restricted]\\u@\\h:\\w\\$ "
        else:
            shell = os.environ.get("SHELL", "/bin/bash")
            shell_cmd = [shell]

        try:
            proc = subprocess.Popen(
                shell_cmd,
                stdin=slave_fd,
                stdout=slave_fd,
                stderr=slave_fd,
                start_new_session=True,
                env=env,
                close_fds=True,
            )
        except Exception as e:
            os.close(master_fd)
            os.close(slave_fd)
            return {"type": "pty_error", "session": session_id, "error": str(e)}

        os.close(slave_fd)

        import select as _select_mod

        def reader():
            try:
                while True:
                    r, _, _ = _select_mod.select([master_fd], [], [], 1.0)
                    if r:
                        try:
                            data = os.read(master_fd, 4096)
                        except OSError:
                            break
                        if not data:
                            break
                        try:
                            ws_send({"type": "pty_output", "session": session_id, "data": data.decode("utf-8", errors="replace")})
                        except Exception:
                            break
                    if proc.poll() is not None:
                        try:
                            while True:
                                r, _, _ = _select_mod.select([master_fd], [], [], 0.1)
                                if not r:
                                    break
                                data = os.read(master_fd, 4096)
                                if not data:
                                    break
                                ws_send({"type": "pty_output", "session": session_id, "data": data.decode("utf-8", errors="replace")})
                        except (OSError, Exception):
                            pass
                        break
            except Exception:
                pass
            finally:
                try:
                    os.close(master_fd)
                except OSError:
                    pass
                code = proc.poll()
                if code is None:
                    try:
                        proc.terminate()
                        proc.wait(timeout=3)
                    except Exception:
                        proc.kill()
                    code = proc.returncode or 0
                try:
                    ws_send({"type": "pty_exit", "session": session_id, "code": code})
                except Exception:
                    pass
                with _pty_lock:
                    _pty_sessions.pop(session_id, None)

        t = threading.Thread(target=reader, daemon=True, name=f"pty-{session_id}")
        t.start()

        with _pty_lock:
            _pty_sessions[session_id] = {"proc": proc, "master_fd": master_fd, "reader": t, "platform": "linux"}

    print(f"[agent-pty] Session {session_id} opened")
    return {"type": "pty_opened", "session": session_id}


def _pty_input(session_id: str, data: str) -> None:
    """Send input to a PTY session."""
    with _pty_lock:
        session = _pty_sessions.get(session_id)
    if not session:
        return

    raw = data.encode("utf-8")
    if session["platform"] == "windows":
        try:
            session["proc"].stdin.write(raw)
            session["proc"].stdin.flush()
        except Exception:
            pass
    else:
        try:
            os.write(session["master_fd"], raw)
        except OSError:
            pass


def _pty_resize(session_id: str, cols: int, rows: int) -> None:
    """Resize a PTY session."""
    with _pty_lock:
        session = _pty_sessions.get(session_id)
    if not session or session["platform"] == "windows":
        return
    try:
        import fcntl
        import struct
        import termios
        winsize = struct.pack("HHHH", rows, cols, 0, 0)
        fcntl.ioctl(session["master_fd"], termios.TIOCSWINSZ, winsize)
        session["proc"].send_signal(signal.SIGWINCH)
    except Exception:
        pass


def _pty_close(session_id: str) -> None:
    """Close a PTY session."""
    with _pty_lock:
        session = _pty_sessions.pop(session_id, None)
    if not session:
        return
    try:
        session["proc"].terminate()
        session["proc"].wait(timeout=3)
    except Exception:
        try:
            session["proc"].kill()
        except Exception:
            pass
    if session.get("master_fd") is not None:
        try:
            os.close(session["master_fd"])
        except OSError:
            pass
    print(f"[agent-pty] Session {session_id} closed")


def _pty_close_all() -> None:
    """Close all PTY sessions (called on shutdown)."""
    with _pty_lock:
        ids = list(_pty_sessions.keys())
    for sid in ids:
        _pty_close(sid)
