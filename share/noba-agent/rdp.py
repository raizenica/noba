"""Remote Desktop (RDP) capture, encoding, and input injection."""
# Copyright (c) 2024-2026 Kevin Van Nieuwenhove. All rights reserved.
# NOBA Command Center — Licensed under Apache 2.0.

from __future__ import annotations

import importlib.util as _ilu
import os
import queue as _queue
import subprocess
import sys
import threading
import time

from utils import _PLATFORM


# ── Load rdp_session script from the package ────────────────────────────────

def _load_mutter_script() -> str:
    spec = _ilu.find_spec("rdp_session")
    if spec is None:
        raise RuntimeError("rdp_session module not found in agent package")
    return spec.loader.get_data(spec.origin).decode("utf-8")


_MUTTER_SESSION_SCRIPT = _load_mutter_script()


# ── RDP state ────────────────────────────────────────────────────────────────

_rdp_frame_queue: _queue.Queue = _queue.Queue(maxsize=2)
_rdp_active = threading.Event()
_rdp_lock = threading.Lock()
_rdp_thread: threading.Thread | None = None
_mutter_proc: "subprocess.Popen | None" = None
_mutter_proc_lock = threading.Lock()
_mutter_io_lock = threading.Lock()

# Cached ctypes state (loaded once per process)
_rdp_x11_lib = None
_rdp_xtst_lib = None
_rdp_x11_dpy = None

# ── Browser e.code → X11 hardware keycode ────────────────────────────────────
# X11 hardware keycode = Linux evdev scancode + 8.
# W3C KeyboardEvent.code values (physical key names) map directly to evdev
# scancodes, making this a reliable, keyboard-layout-independent translation.
# Using e.code instead of e.keyCode avoids the A=65→spacebar mapping bug.
_JS_CODE_TO_X11 = {
    "Escape": 9, "F1": 67, "F2": 68, "F3": 69, "F4": 70, "F5": 71, "F6": 72,
    "F7": 73, "F8": 74, "F9": 75, "F10": 76, "F11": 95, "F12": 96,
    "Backquote": 49, "Digit1": 10, "Digit2": 11, "Digit3": 12, "Digit4": 13,
    "Digit5": 14, "Digit6": 15, "Digit7": 16, "Digit8": 17, "Digit9": 18,
    "Digit0": 19, "Minus": 20, "Equal": 21, "Backspace": 22,
    "Tab": 23,
    "KeyQ": 24, "KeyW": 25, "KeyE": 26, "KeyR": 27, "KeyT": 28,
    "KeyY": 29, "KeyU": 30, "KeyI": 31, "KeyO": 32, "KeyP": 33,
    "BracketLeft": 34, "BracketRight": 35, "Enter": 36,
    "CapsLock": 66,
    "KeyA": 38, "KeyS": 39, "KeyD": 40, "KeyF": 41, "KeyG": 42,
    "KeyH": 43, "KeyJ": 44, "KeyK": 45, "KeyL": 46,
    "Semicolon": 47, "Quote": 48, "Backslash": 51,
    "ShiftLeft": 50, "IntlBackslash": 94,
    "KeyZ": 52, "KeyX": 53, "KeyC": 54, "KeyV": 55, "KeyB": 56,
    "KeyN": 57, "KeyM": 58,
    "Comma": 59, "Period": 60, "Slash": 61, "ShiftRight": 62,
    "ControlLeft": 37, "AltLeft": 64, "Space": 65, "AltRight": 108,
    "ControlRight": 105, "MetaLeft": 133, "MetaRight": 134,
    "Insert": 118, "Delete": 119, "Home": 110, "End": 115,
    "PageUp": 112, "PageDown": 117,
    "ArrowLeft": 113, "ArrowUp": 111, "ArrowRight": 114, "ArrowDown": 116,
    "NumLock": 77, "NumpadDivide": 106, "NumpadMultiply": 63,
    "Numpad7": 79, "Numpad8": 80, "Numpad9": 81, "NumpadSubtract": 82,
    "Numpad4": 83, "Numpad5": 84, "Numpad6": 85, "NumpadAdd": 86,
    "Numpad1": 87, "Numpad2": 88, "Numpad3": 89,
    "Numpad0": 90, "NumpadDecimal": 91, "NumpadEnter": 104,
    "PrintScreen": 107, "ScrollLock": 78, "Pause": 127,
}


def _js_code_to_x11_keycode(code: str) -> int:
    """Translate a W3C KeyboardEvent.code string to an X11 hardware keycode."""
    return _JS_CODE_TO_X11.get(code, 0)


# ── X11 library loaders ──────────────────────────────────────────────────────

def _rdp_load_x11():
    global _rdp_x11_lib
    if _rdp_x11_lib is None:
        try:
            import ctypes
            import ctypes.util
            name = ctypes.util.find_library("X11") or "libX11.so.6"
            lib = ctypes.CDLL(name)
            lib.XOpenDisplay.restype = ctypes.c_void_p
            lib.XOpenDisplay.argtypes = [ctypes.c_char_p]
            lib.XDefaultScreen.restype = ctypes.c_int
            lib.XDefaultScreen.argtypes = [ctypes.c_void_p]
            lib.XDefaultRootWindow.restype = ctypes.c_ulong
            lib.XDefaultRootWindow.argtypes = [ctypes.c_void_p]
            lib.XDisplayWidth.restype = ctypes.c_int
            lib.XDisplayWidth.argtypes = [ctypes.c_void_p, ctypes.c_int]
            lib.XDisplayHeight.restype = ctypes.c_int
            lib.XDisplayHeight.argtypes = [ctypes.c_void_p, ctypes.c_int]
            lib.XGetImage.restype = ctypes.c_void_p
            lib.XGetImage.argtypes = [
                ctypes.c_void_p, ctypes.c_ulong,
                ctypes.c_int, ctypes.c_int, ctypes.c_uint, ctypes.c_uint,
                ctypes.c_ulong, ctypes.c_int,
            ]
            lib.XDestroyImage.restype = ctypes.c_int
            lib.XDestroyImage.argtypes = [ctypes.c_void_p]
            lib.XCloseDisplay.restype = ctypes.c_int
            lib.XCloseDisplay.argtypes = [ctypes.c_void_p]
            lib.XFlush.restype = ctypes.c_int
            lib.XFlush.argtypes = [ctypes.c_void_p]
            _rdp_x11_lib = lib
        except Exception:
            _rdp_x11_lib = False
    return _rdp_x11_lib if _rdp_x11_lib else None


def _rdp_load_xtst():
    global _rdp_xtst_lib
    if _rdp_xtst_lib is None:
        try:
            import ctypes
            import ctypes.util
            name = ctypes.util.find_library("Xtst") or "libXtst.so.6"
            lib = ctypes.CDLL(name)
            lib.XTestFakeMotionEvent.argtypes = [
                ctypes.c_void_p, ctypes.c_int, ctypes.c_int, ctypes.c_int, ctypes.c_ulong]
            lib.XTestFakeButtonEvent.argtypes = [
                ctypes.c_void_p, ctypes.c_uint, ctypes.c_int, ctypes.c_ulong]
            lib.XTestFakeKeyEvent.argtypes = [
                ctypes.c_void_p, ctypes.c_uint, ctypes.c_int, ctypes.c_ulong]
            _rdp_xtst_lib = lib
        except Exception:
            _rdp_xtst_lib = False
    return _rdp_xtst_lib if _rdp_xtst_lib else None


def _rdp_get_x11_display():
    """Return a persistent X11 Display* for input injection (open once, reuse)."""
    global _rdp_x11_dpy
    if _rdp_x11_dpy:
        return _rdp_x11_dpy
    _rdp_set_xauthority()
    lib = _rdp_load_x11()
    if not lib:
        return None
    try:
        display_name = _rdp_find_display()
        dpy = lib.XOpenDisplay(display_name)
        if dpy:
            _rdp_x11_dpy = dpy
        return _rdp_x11_dpy
    except Exception:
        return None


def _rdp_find_display() -> bytes:
    """Return the best X11 display string, probing sockets when $DISPLAY is absent."""
    d = os.environ.get("DISPLAY", "")
    if d:
        return d.encode()
    try:
        for name in sorted(os.listdir("/tmp/.X11-unix/")):
            if name.startswith("X"):
                return f":{name[1:]}".encode()
    except OSError:
        pass
    return b":0"


def _rdp_set_xauthority() -> None:
    """Ensure XAUTHORITY points to the user's Xauthority cookie file."""
    if os.environ.get("XAUTHORITY"):
        return
    import glob as _glob

    uid = os.getuid()
    home = os.path.expanduser("~")

    if uid == 0:
        try:
            import pwd as _pwd
            for sock_name in ["X0", "X1", "X2"]:
                sock = f"/tmp/.X11-unix/{sock_name}"
                if os.path.exists(sock):
                    owner_uid = os.stat(sock).st_uid
                    if owner_uid != 0:
                        entry = _pwd.getpwuid(owner_uid)
                        home = entry.pw_dir
                        uid = owner_uid
                        break
        except Exception:
            pass

    patterns = [
        f"{home}/.Xauthority",
        f"/run/user/{uid}/.mutter-Xwaylandauth.*",
        f"/run/user/{uid}/Xwaylandauth.*",
        f"/run/user/{uid}/xauth*",
        f"/run/user/{uid}/.xauth*",
        f"/tmp/xauth_{uid}*",
        f"/tmp/.xauth*-{uid}",
        "/tmp/xauth_*",
        "/tmp/.xauth*",
        f"/var/run/user/{uid}/xauth*",
    ]
    for pattern in patterns:
        if "*" in pattern or "?" in pattern:
            for m in sorted(_glob.glob(pattern)):
                if os.path.isfile(m) and os.access(m, os.R_OK):
                    os.environ["XAUTHORITY"] = m
                    return
        elif os.path.isfile(pattern) and os.access(pattern, os.R_OK):
            os.environ["XAUTHORITY"] = pattern
            return


def _capture_screen_x11():
    """Capture the X11 root window, trying each available socket.
    Returns (w, h, rgb_bytes) or None. Raises RuntimeError on hard failures."""
    import ctypes
    _rdp_set_xauthority()
    lib = _rdp_load_x11()
    if not lib:
        raise RuntimeError("libX11 not found — install libX11.so.6")

    candidates: list[bytes] = []
    env_d = os.environ.get("DISPLAY", "")
    if env_d:
        candidates.append(env_d.encode())
    try:
        for name in sorted(os.listdir("/tmp/.X11-unix/")):
            if name.startswith("X"):
                cand = f":{name[1:]}".encode()
                if cand not in candidates:
                    candidates.append(cand)
    except OSError:
        pass
    if not candidates:
        candidates = [b":0"]

    last_err = "no displays found"
    for display_name in candidates:
        try:
            dpy = lib.XOpenDisplay(display_name)
            if not dpy:
                last_err = f"XOpenDisplay({display_name.decode()!r}) failed"
                continue
            screen = lib.XDefaultScreen(dpy)
            root = lib.XDefaultRootWindow(dpy)
            attr_buf = (ctypes.c_int * 32)()
            lib.XGetWindowAttributes.restype = ctypes.c_int
            lib.XGetWindowAttributes.argtypes = [ctypes.c_void_p, ctypes.c_ulong, ctypes.c_void_p]
            lib.XGetWindowAttributes(dpy, root, attr_buf)
            w = attr_buf[2]
            h = attr_buf[3]
            if w <= 0 or h <= 0:
                w = lib.XDisplayWidth(dpy, screen)
                h = lib.XDisplayHeight(dpy, screen)
            if w <= 0 or h <= 0:
                lib.XCloseDisplay(dpy)
                last_err = f"{display_name.decode()!r} has {w}x{h} dimensions (virtual/headless)"
                continue
            import threading as _threading
            _img_result: list = [None]

            def _do_xgetimage() -> None:
                ptr = lib.XGetImage(dpy, root, 0, 0, w, h, 0xFFFFFFFF, 2)
                if not ptr:
                    ptr = lib.XGetImage(dpy, root, 0, 0, w, h, 1, 2)
                _img_result[0] = ptr

            _t = _threading.Thread(target=_do_xgetimage, daemon=True)
            _t.start()
            _t.join(timeout=4.0)
            if _t.is_alive():
                lib.XCloseDisplay(dpy)
                last_err = f"XGetImage timed out on {display_name.decode()!r} — compositor blocking X11 capture"
                continue
            img_ptr = _img_result[0]
            if not img_ptr:
                lib.XCloseDisplay(dpy)
                last_err = f"XGetImage returned NULL on {display_name.decode()!r} ({w}x{h})"
                continue

            class _XImageHead(ctypes.Structure):
                _fields_ = [
                    ("width", ctypes.c_int),
                    ("height", ctypes.c_int),
                    ("xoffset", ctypes.c_int),
                    ("format", ctypes.c_int),
                    ("data", ctypes.POINTER(ctypes.c_ubyte)),
                    ("byte_order", ctypes.c_int),
                    ("bitmap_unit", ctypes.c_int),
                    ("bitmap_bit_order", ctypes.c_int),
                    ("bitmap_pad", ctypes.c_int),
                    ("depth", ctypes.c_int),
                    ("bytes_per_line", ctypes.c_int),
                    ("bits_per_pixel", ctypes.c_int),
                ]

            img = ctypes.cast(img_ptr, ctypes.POINTER(_XImageHead)).contents
            bpl = img.bytes_per_line
            bpp = img.bits_per_pixel // 8
            raw = bytes(img.data[:bpl * h])
            lib.XDestroyImage(img_ptr)
            lib.XCloseDisplay(dpy)

            if bpl != w * bpp:
                stripped = bytearray(w * bpp * h)
                for y in range(h):
                    stripped[y * w * bpp:(y + 1) * w * bpp] = raw[y * bpl:y * bpl + w * bpp]
                raw = bytes(stripped)

            rgb = bytearray(w * h * 3)
            rgb[0::3] = raw[2::bpp]
            rgb[1::3] = raw[1::bpp]
            rgb[2::3] = raw[0::bpp]
            return w, h, bytes(rgb)

        except Exception as e:
            last_err = f"{display_name.decode()!r}: {e}"
            print(f"[agent-rdp] X11 capture error on {display_name.decode()!r}: {e}", file=sys.stderr)

    raise RuntimeError(f"X11 capture failed on all displays — {last_err}")


def _capture_screen_windows():
    """Capture the primary monitor using Windows GDI BitBlt. Returns (w, h, rgb_bytes) or None."""
    try:
        import ctypes
        from ctypes import wintypes

        user32 = ctypes.WinDLL("user32")
        gdi32 = ctypes.WinDLL("gdi32")

        w = user32.GetSystemMetrics(0)
        h = user32.GetSystemMetrics(1)

        hwnd = user32.GetDesktopWindow()
        hdc = user32.GetDC(hwnd)
        memdc = gdi32.CreateCompatibleDC(hdc)
        hbmp = gdi32.CreateCompatibleBitmap(hdc, w, h)
        gdi32.SelectObject(memdc, hbmp)
        gdi32.BitBlt(memdc, 0, 0, w, h, hdc, 0, 0, 0x00CC0020)

        class _BITMAPINFOHEADER(ctypes.Structure):
            _fields_ = [
                ("biSize", wintypes.DWORD),
                ("biWidth", wintypes.LONG),
                ("biHeight", wintypes.LONG),
                ("biPlanes", wintypes.WORD),
                ("biBitCount", wintypes.WORD),
                ("biCompression", wintypes.DWORD),
                ("biSizeImage", wintypes.DWORD),
                ("biXPelsPerMeter", wintypes.LONG),
                ("biYPelsPerMeter", wintypes.LONG),
                ("biClrUsed", wintypes.DWORD),
                ("biClrImportant", wintypes.DWORD),
            ]

        bmi = _BITMAPINFOHEADER()
        bmi.biSize = ctypes.sizeof(_BITMAPINFOHEADER)
        bmi.biWidth = w
        bmi.biHeight = -h
        bmi.biPlanes = 1
        bmi.biBitCount = 24
        bmi.biCompression = 0

        buf = (ctypes.c_byte * (w * h * 3))()
        gdi32.GetDIBits(memdc, hbmp, 0, h, buf, ctypes.byref(bmi), 0)

        gdi32.DeleteObject(hbmp)
        gdi32.DeleteDC(memdc)
        user32.ReleaseDC(hwnd, hdc)

        raw = bytes(buf)
        rgb = bytearray(w * h * 3)
        rgb[0::3] = raw[2::3]
        rgb[1::3] = raw[1::3]
        rgb[2::3] = raw[0::3]
        return w, h, bytes(rgb)
    except Exception as e:
        print(f"[agent-rdp] Windows GDI capture error: {e}", file=sys.stderr)
        return None


def _capture_screen_macos():
    """Capture the main display using CoreGraphics. Returns (w, h, rgb_bytes) or None."""
    try:
        import ctypes
        cg = ctypes.CDLL(
            "/System/Library/Frameworks/CoreGraphics.framework/CoreGraphics"
        )
        cg.CGMainDisplayID.restype = ctypes.c_uint32
        cg.CGDisplayCreateImage.restype = ctypes.c_void_p
        cg.CGDisplayCreateImage.argtypes = [ctypes.c_uint32]
        cg.CGImageGetWidth.restype = ctypes.c_size_t
        cg.CGImageGetWidth.argtypes = [ctypes.c_void_p]
        cg.CGImageGetHeight.restype = ctypes.c_size_t
        cg.CGImageGetHeight.argtypes = [ctypes.c_void_p]
        cg.CGImageGetDataProvider.restype = ctypes.c_void_p
        cg.CGImageGetDataProvider.argtypes = [ctypes.c_void_p]
        cg.CGDataProviderCopyData.restype = ctypes.c_void_p
        cg.CGDataProviderCopyData.argtypes = [ctypes.c_void_p]
        cg.CFDataGetLength.restype = ctypes.c_long
        cg.CFDataGetLength.argtypes = [ctypes.c_void_p]
        cg.CFDataGetBytePtr.restype = ctypes.POINTER(ctypes.c_uint8)
        cg.CFDataGetBytePtr.argtypes = [ctypes.c_void_p]
        cg.CFRelease.restype = None
        cg.CFRelease.argtypes = [ctypes.c_void_p]
        cg.CGImageRelease.restype = None
        cg.CGImageRelease.argtypes = [ctypes.c_void_p]

        display_id = cg.CGMainDisplayID()
        img = cg.CGDisplayCreateImage(display_id)
        if not img:
            return None

        w = cg.CGImageGetWidth(img)
        h = cg.CGImageGetHeight(img)
        provider = cg.CGImageGetDataProvider(img)
        data = cg.CGDataProviderCopyData(provider)
        length = cg.CFDataGetLength(data)
        ptr = cg.CFDataGetBytePtr(data)
        raw = bytes(ptr[:length])
        cg.CFRelease(data)
        cg.CGImageRelease(img)

        rgb = bytearray(w * h * 3)
        rgb[0::3] = raw[2::4]
        rgb[1::3] = raw[1::4]
        rgb[2::3] = raw[0::4]
        return w, h, bytes(rgb)
    except Exception as e:
        print(f"[agent-rdp] macOS CoreGraphics capture error: {e}", file=sys.stderr)
        return None


def _capture_screen_grim() -> tuple | None:
    """Capture via grim (Wayland wlr-screencopy). Returns (w, h, rgb) or None."""
    import tempfile

    grim = _which("grim")
    if not grim:
        print("[agent-rdp] grim not found — install grim for Wayland capture", file=sys.stderr)
        return None
    env = os.environ.copy()
    if not env.get("WAYLAND_DISPLAY"):
        for wl in ("wayland-0", "wayland-1"):
            sock = f"/run/user/{os.getuid()}/wayland-0"
            try:
                for sock_name in ["X0", "X1"]:
                    sp = f"/tmp/.X11-unix/{sock_name}"
                    if os.path.exists(sp):
                        owner_uid = os.stat(sp).st_uid
                        if owner_uid != 0:
                            sock = f"/run/user/{owner_uid}/{wl}"
                            break
            except Exception:
                pass
            if os.path.exists(sock):
                env["WAYLAND_DISPLAY"] = wl
                env["XDG_RUNTIME_DIR"] = os.path.dirname(sock)
                break
    if not env.get("WAYLAND_DISPLAY"):
        print("[agent-rdp] WAYLAND_DISPLAY not set and could not find wayland socket", file=sys.stderr)
        return None
    try:
        with tempfile.NamedTemporaryFile(suffix=".png", delete=False) as tmp:
            tmp_path = tmp.name
        result = subprocess.run(
            [grim, "-t", "png", tmp_path],
            env=env, timeout=5, capture_output=True,
        )
        if result.returncode != 0:
            return None
        with open(tmp_path, "rb") as f:
            png_data = f.read()
        os.unlink(tmp_path)
        return _rdp_decode_png(png_data)
    except Exception as e:
        print(f"[agent-rdp] grim capture error: {e}", file=sys.stderr)
        return None


def _rdp_display_owner() -> tuple:
    """Return (uid, gid, home, display_str, xauth_path) for the X11/Wayland display owner."""
    import pwd as _pwd
    import glob as _g
    uid = os.getuid()
    try:
        entry = _pwd.getpwuid(uid)
        home, gid = entry.pw_dir, entry.pw_gid
    except Exception:
        home, gid = os.path.expanduser("~"), os.getgid()

    display_str = os.environ.get("DISPLAY", "")
    if uid == 0 or not display_str:
        try:
            for sock in sorted(os.listdir("/tmp/.X11-unix/")) if os.path.isdir("/tmp/.X11-unix/") else []:
                if not sock.startswith("X"):
                    continue
                owner_uid = os.stat(f"/tmp/.X11-unix/{sock}").st_uid
                if owner_uid != 0:
                    e2 = _pwd.getpwuid(owner_uid)
                    uid, gid, home = owner_uid, e2.pw_gid, e2.pw_dir
                    display_str = f":{sock[1:]}"
                    break
                elif not display_str:
                    display_str = f":{sock[1:]}"
        except Exception:
            pass
    if not display_str:
        display_str = ":0"

    xauth = ""
    for pattern in [f"{home}/.Xauthority", f"/tmp/xauth_{uid}*", f"/run/user/{uid}/xauth*",
                    f"/run/user/{uid}/.mutter-Xwaylandauth.*"]:
        if "*" in pattern:
            matches = sorted(_g.glob(pattern))
            if matches:
                xauth = matches[-1]
                break
        elif os.path.exists(pattern):
            xauth = pattern
            break
    return uid, gid, home, display_str, xauth


def _capture_screen_gnome() -> tuple | None:
    """Capture via GNOME Shell's D-Bus Screenshot API."""
    uid, gid, home, _, _ = _rdp_display_owner()
    if not os.path.exists(f"/run/user/{uid}/gnome-shell"):
        return None
    bus_path = f"/run/user/{uid}/bus"
    if not os.path.exists(bus_path):
        print("[agent-rdp] GNOME session bus not found", file=sys.stderr)
        return None
    env = os.environ.copy()
    env["HOME"] = home
    env["DBUS_SESSION_BUS_ADDRESS"] = f"unix:path={bus_path}"
    env["XDG_RUNTIME_DIR"] = f"/run/user/{uid}"
    preexec = None
    if os.getuid() == 0 and uid != 0:
        _uid, _gid = uid, gid

        def preexec():
            os.setgid(_gid)
            os.setuid(_uid)

    tmp_path = f"/tmp/noba_rdp_{uid}.png"
    gdbus = _which("gdbus")
    if gdbus:
        try:
            r = subprocess.run(
                [gdbus, "call", "--session",
                 "--dest", "org.gnome.Shell.Screenshot",
                 "--object-path", "/org/gnome/Shell/Screenshot",
                 "--method", "org.gnome.Shell.Screenshot.Screenshot",
                 "false", "false", tmp_path],
                env=env, preexec_fn=preexec, capture_output=True, timeout=5,
            )
            if r.returncode == 0 and os.path.exists(tmp_path):
                with open(tmp_path, "rb") as f:
                    png_data = f.read()
                try:
                    os.unlink(tmp_path)
                except OSError:
                    pass
                result = _rdp_decode_png(png_data)
                if result:
                    print(f"[agent-rdp] captured via gdbus/gnome-shell {result[0]}x{result[1]}", file=sys.stderr)
                    return result
            print(f"[agent-rdp] gdbus rc={r.returncode} stderr={r.stderr[:100]!r}", file=sys.stderr)
        except Exception as e:
            print(f"[agent-rdp] gdbus error: {e}", file=sys.stderr)
    gnome_ss = _which("gnome-screenshot")
    if gnome_ss:
        try:
            r = subprocess.run(
                [gnome_ss, "-f", tmp_path],
                env=env, preexec_fn=preexec, capture_output=True, timeout=5,
            )
            if r.returncode == 0 and os.path.exists(tmp_path):
                with open(tmp_path, "rb") as f:
                    png_data = f.read()
                try:
                    os.unlink(tmp_path)
                except OSError:
                    pass
                result = _rdp_decode_png(png_data)
                if result:
                    print(f"[agent-rdp] captured via gnome-screenshot {result[0]}x{result[1]}", file=sys.stderr)
                    return result
            print(f"[agent-rdp] gnome-screenshot rc={r.returncode} stderr={r.stderr[:100]!r}", file=sys.stderr)
        except Exception as e:
            print(f"[agent-rdp] gnome-screenshot error: {e}", file=sys.stderr)
    return None


def _mutter_subprocess_start(uid: int, gid: int, home: str) -> "subprocess.Popen | None":
    """Launch the persistent Mutter session subprocess. Returns proc if READY, else None."""
    import select as _sel
    env = os.environ.copy()
    env["HOME"] = home
    env["DBUS_SESSION_BUS_ADDRESS"] = f"unix:path=/run/user/{uid}/bus"
    env["XDG_RUNTIME_DIR"] = f"/run/user/{uid}"
    env["PIPEWIRE_RUNTIME_DIR"] = f"/run/user/{uid}"
    preexec_fn = None
    if os.getuid() == 0 and uid != 0:
        _uid, _gid = uid, gid

        def preexec_fn():
            os.setgid(_gid)
            os.setuid(_uid)

    try:
        proc = subprocess.Popen(
            [sys.executable, "-c", _MUTTER_SESSION_SCRIPT],
            env=env, preexec_fn=preexec_fn,
            stdin=subprocess.PIPE, stdout=subprocess.PIPE, stderr=subprocess.PIPE,
        )
        deadline = time.monotonic() + 12.0
        while time.monotonic() < deadline:
            remaining = max(0.05, deadline - time.monotonic())
            rlist = _sel.select([proc.stderr], [], [], min(remaining, 0.5))[0]
            if rlist:
                line = proc.stderr.readline()
                if line:
                    msg = line.decode("utf-8", errors="replace").strip()
                    print(f"[agent-rdp] mutter: {msg}", file=sys.stderr)
                    if msg == "READY":
                        def _drain(p: "subprocess.Popen") -> None:
                            try:
                                for ln in p.stderr:
                                    print(f"[agent-rdp] mutter: {ln.decode('utf-8', errors='replace').rstrip()}", file=sys.stderr)
                            except Exception:
                                pass

                        threading.Thread(target=_drain, args=(proc,), daemon=True).start()
                        return proc
                    if "ERROR" in msg:
                        proc.kill()
                        return None
            if proc.poll() is not None:
                return None
        proc.kill()
        return None
    except Exception as e:
        print(f"[agent-rdp] mutter start error: {e}", file=sys.stderr)
        return None


def _mutter_ensure(uid: int, gid: int, home: str) -> bool:
    """Ensure the Mutter session subprocess is running. Returns True if ready."""
    global _mutter_proc
    with _mutter_proc_lock:
        if _mutter_proc is not None and _mutter_proc.poll() is None:
            return True
    proc = _mutter_subprocess_start(uid, gid, home)
    if proc is None:
        return False
    with _mutter_proc_lock:
        if _mutter_proc is not None and _mutter_proc.poll() is None:
            proc.kill()
        else:
            _mutter_proc = proc
    return True


def _mutter_stop() -> None:
    """Stop the persistent Mutter session subprocess."""
    global _mutter_proc
    with _mutter_proc_lock:
        proc = _mutter_proc
        _mutter_proc = None
    if proc is not None:
        try:
            proc.stdin.write(b"STOP\n")
            proc.stdin.flush()
        except Exception:
            pass
        try:
            proc.kill()
        except Exception:
            pass


def _capture_screen_pipewire() -> tuple | None:
    """Capture via persistent Mutter ScreenCast D-Bus + PipeWire + GStreamer session."""
    import select as _sel
    import struct
    uid, gid, home, _, _ = _rdp_display_owner()
    bus_path = f"/run/user/{uid}/bus"
    pipewire_sock = f"/run/user/{uid}/pipewire-0"
    if not os.path.exists(bus_path) or not os.path.exists(pipewire_sock):
        return None
    if not _mutter_ensure(uid, gid, home):
        return None
    with _mutter_proc_lock:
        proc = _mutter_proc
    if proc is None or proc.poll() is not None:
        return None
    try:
        with _mutter_io_lock:
            proc.stdin.write(b"CAPTURE\n")
            proc.stdin.flush()
        ready = _sel.select([proc.stdout], [], [], 2.0)[0]
        if not ready:
            return None
        magic = proc.stdout.read(4)
        if magic == b"NONE":
            return None
        if magic == b"NOBR":
            dims = proc.stdout.read(8)
            if len(dims) < 8:
                return None
            w, h = struct.unpack(">II", dims)
            size = w * h * 3
            if size > 15_000_000:
                return None
            rgb = proc.stdout.read(size)
            if len(rgb) < size:
                return None
            return (w, h, rgb)
        if magic != b"NOBA":
            return None
        size = struct.unpack(">I", proc.stdout.read(4))[0]
        if size > 15_000_000:
            return None
        png = proc.stdout.read(size)
        if len(png) < size:
            return None
        return _rdp_decode_png(png)
    except Exception as e:
        print(f"[agent-rdp] pipewire error: {e}", file=sys.stderr)
        _mutter_stop()
        return None


def _capture_screen_cmd() -> tuple | None:
    """Capture via grim, wayshot, scrot, or ImageMagick import."""
    uid, gid, home, display_str, xauth = _rdp_display_owner()
    env = os.environ.copy()
    env["DISPLAY"] = display_str
    env["HOME"] = home
    if xauth:
        env["XAUTHORITY"] = xauth
    for wl in ("wayland-0", "wayland-1"):
        if os.path.exists(f"/run/user/{uid}/{wl}"):
            env.setdefault("WAYLAND_DISPLAY", wl)
            env.setdefault("XDG_RUNTIME_DIR", f"/run/user/{uid}")
            break

    preexec = None
    if os.getuid() == 0 and uid != 0:
        _uid, _gid = uid, gid

        def preexec():
            os.setgid(_gid)
            os.setuid(_uid)

    for tool, args in [
        ("grim", ["-t", "png", "-"]),
        ("wayshot", ["--stdout"]),
        ("scrot", ["-"]),
        ("import", ["-window", "root", "-depth", "8", "png:-"]),
    ]:
        exe = _which(tool)
        if not exe:
            continue
        try:
            r = subprocess.run(
                [exe] + args,
                capture_output=True, timeout=8, env=env, preexec_fn=preexec,
            )
            if r.returncode == 0 and r.stdout:
                result = _rdp_decode_png(r.stdout)
                if result:
                    print(f"[agent-rdp] captured via {tool} {result[0]}x{result[1]}", file=sys.stderr)
                    return result
            print(f"[agent-rdp] {tool} rc={r.returncode} stderr={r.stderr[:100]!r}", file=sys.stderr)
        except Exception as e:
            print(f"[agent-rdp] {tool} error: {e}", file=sys.stderr)
    return None


def _rdp_decode_png(data: bytes) -> tuple | None:
    """Decode a PNG byte string to (w, h, rgb_bytes). Pure stdlib."""
    import zlib as _zlib
    import struct as _struct
    if data[:8] != b"\x89PNG\r\n\x1a\n":
        return None
    pos = 8
    chunks: dict = {}
    while pos < len(data) - 12:
        length = _struct.unpack_from(">I", data, pos)[0]
        tag = data[pos + 4:pos + 8]
        chunks.setdefault(tag, []).append(data[pos + 8:pos + 8 + length])
        pos += 12 + length
    if b"IHDR" not in chunks:
        return None
    ihdr = chunks[b"IHDR"][0]
    w, h = _struct.unpack_from(">II", ihdr)
    bit_depth, color_type = ihdr[8], ihdr[9]
    if bit_depth != 8 or color_type not in (2, 6):
        return None
    raw = _zlib.decompress(b"".join(chunks.get(b"IDAT", [])))
    bpp = 3 if color_type == 2 else 4
    stride = w * bpp + 1
    rgb = bytearray(w * h * 3)
    prev = bytes(w * bpp)
    for y in range(h):
        row = raw[y * stride:y * stride + stride]
        filt = row[0]
        cur = bytearray(row[1:])
        if filt == 1:
            for i in range(bpp, len(cur)):
                cur[i] = (cur[i] + cur[i - bpp]) & 0xFF
        elif filt == 2:
            for i in range(len(cur)):
                cur[i] = (cur[i] + prev[i]) & 0xFF
        elif filt == 3:
            for i in range(len(cur)):
                a = cur[i - bpp] if i >= bpp else 0
                cur[i] = (cur[i] + (a + prev[i]) // 2) & 0xFF
        elif filt == 4:
            for i in range(len(cur)):
                a = cur[i - bpp] if i >= bpp else 0
                b_val = prev[i]
                c = prev[i - bpp] if i >= bpp else 0
                p = a + b_val - c
                pa, pb, pc = abs(p - a), abs(p - b_val), abs(p - c)
                pr = a if pa <= pb and pa <= pc else (b_val if pb <= pc else c)
                cur[i] = (cur[i] + pr) & 0xFF
        if bpp == 3:
            rgb[y * w * 3:(y + 1) * w * 3] = cur
        else:
            for x in range(w):
                rgb[(y * w + x) * 3:(y * w + x) * 3 + 3] = cur[x * 4:x * 4 + 3]
        prev = bytes(cur)
    return w, h, bytes(rgb)


def _which(cmd: str) -> str | None:
    """Locate an executable in PATH. Returns path string or None."""
    import shutil
    return shutil.which(cmd)


def _capture_screen() -> tuple | None:
    """Dispatch to the platform-appropriate screen capture. Returns (w, h, rgb) or None."""
    if _PLATFORM == "windows":
        return _capture_screen_windows()
    if _PLATFORM == "darwin":
        return _capture_screen_macos()
    _wayland_present = False
    try:
        if os.path.isdir("/run/user"):
            for _uid_dir in os.listdir("/run/user"):
                for _wl in ("wayland-0", "wayland-1"):
                    if os.path.exists(f"/run/user/{_uid_dir}/{_wl}"):
                        _wayland_present = True
                        break
                if _wayland_present:
                    break
    except OSError:
        pass
    x11_err = ""
    if not _wayland_present:
        try:
            result = _capture_screen_x11()
            if result:
                return result
        except RuntimeError as e:
            x11_err = str(e)
    result = _capture_screen_grim()
    if result:
        return result
    result = _capture_screen_pipewire()
    if result:
        return result
    result = _capture_screen_gnome()
    if result:
        return result
    result = _capture_screen_cmd()
    if result:
        return result
    x11_note = "skipped (Wayland detected)" if _wayland_present else (x11_err or "returned None")
    raise RuntimeError(
        f"All capture methods failed. X11: {x11_note}. "
        f"grim/gnome-screenshot/gdbus/scrot: not found or compositor rejected capture."
    )


def _rdp_scale_half(width: int, height: int, rgb_bytes: bytes) -> tuple:
    """Downsample by 2× using every other pixel/row."""
    new_w = max(1, width // 2)
    new_h = max(1, height // 2)
    rows = []
    for y in range(new_h):
        row_start = (y * 2) * width * 3
        row = rgb_bytes[row_start:row_start + width * 3]
        scaled = bytearray(new_w * 3)
        scaled[0::3] = row[0::6]
        scaled[1::3] = row[1::6]
        scaled[2::3] = row[2::6]
        rows.append(bytes(scaled))
    return new_w, new_h, b"".join(rows)


_HAS_PILLOW: bool | None = None


def _rdp_encode_frame(width: int, height: int, rgb_bytes: bytes, quality: int = 70) -> str:
    """Encode RGB bytes as JPEG (Pillow) or PNG fallback. Returns base64 string."""
    global _HAS_PILLOW
    import base64 as _b64
    if _HAS_PILLOW is None:
        try:
            from PIL import Image as _Img  # noqa: F401
            _HAS_PILLOW = True
        except ImportError:
            _HAS_PILLOW = False
    if _HAS_PILLOW:
        try:
            from PIL import Image as _Img
            import io as _io
            img = _Img.frombytes("RGB", (width, height), rgb_bytes)
            buf = _io.BytesIO()
            img.save(buf, "JPEG", quality=quality, optimize=False)
            return _b64.b64encode(buf.getvalue()).decode("ascii")
        except Exception:
            pass
    import struct
    import zlib

    def _chunk(name: bytes, data: bytes) -> bytes:
        body = name + data
        return struct.pack(">I", len(data)) + body + struct.pack(">I", zlib.crc32(body) & 0xFFFFFFFF)

    ihdr = struct.pack(">IIBBBBB", width, height, 8, 2, 0, 0, 0)
    bpr = width * 3
    raw = bytearray(height * (1 + bpr))
    for y in range(height):
        raw[y * (1 + bpr)] = 0
        raw[y * (1 + bpr) + 1:(y + 1) * (1 + bpr)] = rgb_bytes[y * bpr:(y + 1) * bpr]
    idat = zlib.compress(bytes(raw), 1)
    png = b"\x89PNG\r\n\x1a\n" + _chunk(b"IHDR", ihdr) + _chunk(b"IDAT", idat) + _chunk(b"IEND", b"")
    return _b64.b64encode(png).decode("ascii")


def _rdp_clipboard_env() -> tuple:
    """Return (env, preexec_fn) for running clipboard tools as the desktop user."""
    uid, gid, home, _, _ = _rdp_display_owner()
    env = os.environ.copy()
    env["HOME"] = home
    env["DBUS_SESSION_BUS_ADDRESS"] = f"unix:path=/run/user/{uid}/bus"
    env["XDG_RUNTIME_DIR"] = f"/run/user/{uid}"
    preexec_fn = None
    if os.getuid() == 0 and uid != 0:
        _uid, _gid = uid, gid

        def preexec_fn():
            os.setgid(_gid)
            os.setuid(_uid)

    return env, preexec_fn


def _rdp_clipboard_get() -> str:
    """Read the active desktop clipboard and return as a string."""
    if _PLATFORM == "linux":
        env, preexec_fn = _rdp_clipboard_env()
        for cmd in (["wl-paste", "--no-newline"], ["xclip", "-selection", "clipboard", "-o"],
                    ["xsel", "--clipboard", "--output"]):
            try:
                r = subprocess.run(cmd, capture_output=True, timeout=3,
                                   env=env, preexec_fn=preexec_fn)
                if r.returncode == 0:
                    return r.stdout.decode("utf-8", errors="replace")
            except (FileNotFoundError, subprocess.TimeoutExpired):
                continue
    elif _PLATFORM == "windows":
        try:
            r = subprocess.run(["powershell", "-noprofile", "-c", "Get-Clipboard"],
                               capture_output=True, timeout=3)
            return r.stdout.decode("utf-8", errors="replace").rstrip("\r\n")
        except Exception:
            pass
    elif _PLATFORM == "darwin":
        try:
            r = subprocess.run(["pbpaste"], capture_output=True, timeout=3)
            return r.stdout.decode("utf-8", errors="replace")
        except Exception:
            pass
    return ""


def _rdp_clipboard_paste(text: str) -> None:
    """Set the remote clipboard to text and inject Ctrl+V to paste it."""
    if _PLATFORM == "linux":
        env, preexec_fn = _rdp_clipboard_env()
        for cmd, stdin in (
            (["wl-copy", "--"], None),
            (["xclip", "-selection", "clipboard"], text.encode()),
            (["xsel", "--clipboard", "--input"], text.encode()),
        ):
            try:
                kw = {"input": stdin if stdin is not None else text.encode()}
                subprocess.run(cmd, timeout=3, check=False,
                               env=env, preexec_fn=preexec_fn, **kw)
                break
            except (FileNotFoundError, subprocess.TimeoutExpired):
                continue
    elif _PLATFORM == "windows":
        try:
            # Pass text via stdin to avoid PowerShell injection via repr(text)
            subprocess.run(
                ["powershell", "-NoProfile", "-Command",
                 "[Console]::In.ReadToEnd() | Set-Clipboard"],
                input=text.encode("utf-8", errors="replace"),
                timeout=3, check=False,
            )
        except Exception:
            pass
    elif _PLATFORM == "darwin":
        try:
            subprocess.run(["pbcopy"], input=text.encode(), timeout=3, check=False)
        except Exception:
            pass
    # Inject Ctrl+V to trigger paste in the focused application
    for evt in (
        {"event": "keydown", "code": "ControlLeft"},
        {"event": "keydown", "code": "KeyV"},
        {"event": "keyup",   "code": "KeyV"},
        {"event": "keyup",   "code": "ControlLeft"},
    ):
        _rdp_inject_input(evt)


def _rdp_inject_input(event: dict) -> None:
    """Inject a mouse or keyboard event on the current platform."""
    if _PLATFORM == "linux":
        _rdp_inject_x11(event)
    elif _PLATFORM == "windows":
        _rdp_inject_windows(event)
    elif _PLATFORM == "darwin":
        _rdp_inject_macos(event)


def _rdp_inject_mutter(event: dict) -> None:
    """Send an input event to the persistent Mutter session subprocess via stdin."""
    with _mutter_proc_lock:
        proc = _mutter_proc
    if proc is None or proc.poll() is not None:
        return
    try:
        import json as _json
        line = (_json.dumps(event) + "\n").encode()
        print(f"[agent-rdp] inject→mutter: {event.get('event')} ({event.get('x','')},{event.get('y','')})", file=sys.stderr)
        with _mutter_io_lock:
            proc.stdin.write(line)
            proc.stdin.flush()
    except Exception as e:
        print(f"[agent-rdp] mutter input error: {e}", file=sys.stderr)


def _rdp_inject_x11(event: dict) -> None:
    """Inject input via XTest (libXtst) or Mutter D-Bus on Wayland."""
    with _mutter_proc_lock:
        proc = _mutter_proc
    if proc is not None and proc.poll() is None:
        # Resolve e.code → X11 hardware keycode before sending to mutter subprocess
        if event.get("event") in ("keydown", "keyup"):
            code = event.get("code", "")
            kc = _js_code_to_x11_keycode(code)
            if kc:
                event = {**event, "keycode": kc}
        _rdp_inject_mutter(event)
        return
    lib = _rdp_load_x11()
    xtst = _rdp_load_xtst()
    dpy = _rdp_get_x11_display()
    if not (lib and xtst and dpy):
        return
    try:
        evt = event.get("event", "")
        nx = float(event.get("x", 0))
        ny = float(event.get("y", 0))

        screen = lib.XDefaultScreen(dpy)
        sw = lib.XDisplayWidth(dpy, screen)
        sh = lib.XDisplayHeight(dpy, screen)
        px = max(0, min(sw - 1, int(nx * sw)))
        py = max(0, min(sh - 1, int(ny * sh)))

        if evt == "mousemove":
            xtst.XTestFakeMotionEvent(dpy, -1, px, py, 0)
        elif evt == "mousedown":
            xtst.XTestFakeButtonEvent(dpy, int(event.get("button", 1)), 1, 0)
        elif evt == "mouseup":
            xtst.XTestFakeButtonEvent(dpy, int(event.get("button", 1)), 0, 0)
        elif evt == "wheel":
            btn = 4 if float(event.get("delta_y", 0)) < 0 else 5
            xtst.XTestFakeButtonEvent(dpy, btn, 1, 0)
            xtst.XTestFakeButtonEvent(dpy, btn, 0, 0)
        elif evt == "keydown":
            kc = _js_code_to_x11_keycode(event.get("code", "")) or int(event.get("keycode", 0))
            xtst.XTestFakeKeyEvent(dpy, kc, 1, 0)
        elif evt == "keyup":
            kc = _js_code_to_x11_keycode(event.get("code", "")) or int(event.get("keycode", 0))
            xtst.XTestFakeKeyEvent(dpy, kc, 0, 0)
        lib.XFlush(dpy)
    except Exception as e:
        print(f"[agent-rdp] X11 input error: {e}", file=sys.stderr)


def _rdp_inject_windows(event: dict) -> None:
    """Inject input via user32 SendInput."""
    try:
        import ctypes
        from ctypes import wintypes

        class _MOUSEINPUT(ctypes.Structure):
            _fields_ = [("dx", wintypes.LONG), ("dy", wintypes.LONG),
                        ("mouseData", wintypes.DWORD), ("dwFlags", wintypes.DWORD),
                        ("time", wintypes.DWORD), ("dwExtraInfo", ctypes.POINTER(wintypes.ULONG))]

        class _KEYBDINPUT(ctypes.Structure):
            _fields_ = [("wVk", wintypes.WORD), ("wScan", wintypes.WORD),
                        ("dwFlags", wintypes.DWORD), ("time", wintypes.DWORD),
                        ("dwExtraInfo", ctypes.POINTER(wintypes.ULONG))]

        class _INPUT_UNION(ctypes.Union):
            _fields_ = [("mi", _MOUSEINPUT), ("ki", _KEYBDINPUT)]

        class _INPUT(ctypes.Structure):
            _fields_ = [("type", wintypes.DWORD), ("u", _INPUT_UNION)]

        user32 = ctypes.WinDLL("user32")
        evt = event.get("event", "")
        nx = float(event.get("x", 0))
        ny = float(event.get("y", 0))

        abs_x = int(nx * 65535)
        abs_y = int(ny * 65535)

        inp = _INPUT()
        if evt == "mousemove":
            inp.type = 0
            inp.u.mi.dx = abs_x
            inp.u.mi.dy = abs_y
            inp.u.mi.dwFlags = 0x8001
        elif evt in ("mousedown", "mouseup"):
            btn = int(event.get("button", 1))
            down_flags = {1: 0x0002, 2: 0x0008, 3: 0x0020}
            up_flags   = {1: 0x0004, 2: 0x0010, 3: 0x0040}
            flags = down_flags.get(btn, 0x0002) if evt == "mousedown" else up_flags.get(btn, 0x0004)
            inp.type = 0
            inp.u.mi.dwFlags = flags | 0x8000
            inp.u.mi.dx = abs_x
            inp.u.mi.dy = abs_y
        elif evt == "wheel":
            inp.type = 0
            inp.u.mi.dwFlags = 0x0800
            delta = int(event.get("delta_y", 0))
            inp.u.mi.mouseData = ctypes.c_ulong(-delta * 120 & 0xFFFFFFFF).value
        elif evt in ("keydown", "keyup"):
            inp.type = 1
            inp.u.ki.wVk = int(event.get("keycode", 0))
            inp.u.ki.dwFlags = 0x0002 if evt == "keyup" else 0
        else:
            return

        user32.SendInput(1, ctypes.byref(inp), ctypes.sizeof(_INPUT))
    except Exception as e:
        print(f"[agent-rdp] Windows input error: {e}", file=sys.stderr)


def _rdp_inject_macos(event: dict) -> None:
    """Inject input via CoreGraphics CGEventPost."""
    try:
        import ctypes
        cg = ctypes.CDLL(
            "/System/Library/Frameworks/CoreGraphics.framework/CoreGraphics"
        )
        cg.CGEventCreateMouseEvent.restype = ctypes.c_void_p
        cg.CGEventCreateMouseEvent.argtypes = [
            ctypes.c_void_p, ctypes.c_uint32,
            ctypes.c_double, ctypes.c_double, ctypes.c_uint32]
        cg.CGEventCreateKeyboardEvent.restype = ctypes.c_void_p
        cg.CGEventCreateKeyboardEvent.argtypes = [
            ctypes.c_void_p, ctypes.c_uint16, ctypes.c_bool]
        cg.CGEventPost.restype = None
        cg.CGEventPost.argtypes = [ctypes.c_uint32, ctypes.c_void_p]
        cg.CFRelease.restype = None
        cg.CFRelease.argtypes = [ctypes.c_void_p]

        cg.CGDisplayPixelsWide.restype = ctypes.c_size_t
        cg.CGDisplayPixelsWide.argtypes = [ctypes.c_uint32]
        cg.CGDisplayPixelsHigh.restype = ctypes.c_size_t
        cg.CGDisplayPixelsHigh.argtypes = [ctypes.c_uint32]
        cg.CGMainDisplayID.restype = ctypes.c_uint32
        did = cg.CGMainDisplayID()
        sw = cg.CGDisplayPixelsWide(did)
        sh = cg.CGDisplayPixelsHigh(did)

        evt = event.get("event", "")
        nx = float(event.get("x", 0))
        ny = float(event.get("y", 0))
        px = nx * sw
        py = ny * sh

        ev_map = {
            ("mousemove", 0): (5, 0), ("mousemove", 1): (5, 0),
            ("mousedown", 1): (1, 1), ("mouseup", 1): (2, 1),
            ("mousedown", 3): (3, 3), ("mouseup", 3): (4, 3),
        }
        if evt in ("mousemove", "mousedown", "mouseup"):
            btn = int(event.get("button", 1))
            etype, ebtn = ev_map.get((evt, btn), (5, 0))
            ref = cg.CGEventCreateMouseEvent(None, etype, px, py, ebtn)
            if ref:
                cg.CGEventPost(0, ref)
                cg.CFRelease(ref)
        elif evt == "wheel":
            pass
        elif evt in ("keydown", "keyup"):
            down = evt == "keydown"
            ref = cg.CGEventCreateKeyboardEvent(None, int(event.get("keycode", 0)), down)
            if ref:
                cg.CGEventPost(0, ref)
                cg.CFRelease(ref)
    except Exception as e:
        print(f"[agent-rdp] macOS input error: {e}", file=sys.stderr)


def _rdp_capture_loop(quality: int, fps: int) -> None:
    """Background thread: capture screen, encode, push to frame queue."""
    interval = 1.0 / max(1, fps)
    if quality <= 50:
        do_scale = True
    elif quality <= 75:
        do_scale = True
    else:
        do_scale = False

    print(f"[agent-rdp] Capture started at {fps}fps quality={quality}")

    _consecutive_failures = 0
    _MAX_FAILURES = 8

    while _rdp_active.is_set():
        t0 = time.monotonic()
        try:
            result = _capture_screen()
            if result:
                _consecutive_failures = 0
                w, h, rgb = result
                if do_scale:
                    w, h, rgb = _rdp_scale_half(w, h, rgb)
                frame_data = _rdp_encode_frame(w, h, rgb, quality)
                frame = {"type": "rdp_frame", "w": w, "h": h, "data": frame_data}
                try:
                    _rdp_frame_queue.put_nowait(frame)
                except _queue.Full:
                    try:
                        _rdp_frame_queue.get_nowait()
                    except _queue.Empty:
                        pass
                    try:
                        _rdp_frame_queue.put_nowait(frame)
                    except _queue.Full:
                        pass
            else:
                _rdp_frame_queue.put_nowait({"type": "rdp_unavailable",
                                             "reason": "No display available on this agent"})
                _rdp_active.clear()
                break
        except RuntimeError as e:
            _consecutive_failures += 1
            print(f"[agent-rdp] Display error ({_consecutive_failures}/{_MAX_FAILURES}): {e}", file=sys.stderr)
            if _consecutive_failures >= _MAX_FAILURES:
                try:
                    _rdp_frame_queue.put_nowait({"type": "rdp_unavailable", "reason": str(e)})
                except _queue.Full:
                    pass
                _rdp_active.clear()
                break
            _rdp_active.wait(timeout=0.5)
            continue
        except Exception as e:
            print(f"[agent-rdp] Frame error: {e}", file=sys.stderr)

        elapsed = time.monotonic() - t0
        sleep_time = max(0.0, interval - elapsed)
        if sleep_time > 0:
            _rdp_active.wait(timeout=sleep_time)

    print("[agent-rdp] Capture stopped")


def _rdp_start(quality: int = 70, fps: int = 5) -> None:
    """Start or restart the RDP capture thread."""
    global _rdp_thread
    with _rdp_lock:
        if _rdp_active.is_set():
            _rdp_active.clear()
            if _rdp_thread and _rdp_thread.is_alive():
                _rdp_thread.join(timeout=2)
        _rdp_active.set()
        _rdp_thread = threading.Thread(
            target=_rdp_capture_loop, args=(quality, fps),
            daemon=True, name="noba-rdp",
        )
        _rdp_thread.start()


def _rdp_stop() -> None:
    """Stop the RDP capture thread and Mutter session subprocess."""
    global _rdp_thread
    _rdp_active.clear()
    _mutter_stop()
    while not _rdp_frame_queue.empty():
        try:
            _rdp_frame_queue.get_nowait()
        except _queue.Empty:
            break
