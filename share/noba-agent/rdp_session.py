# Copyright (c) 2024-2026 Kevin Van Nieuwenhove. All rights reserved.
# NOBA Command Center — Licensed under Apache 2.0.

import sys
import os
import json
import threading
import struct
import gi
gi.require_version("Gio", "2.0")
gi.require_version("GLib", "2.0")
gi.require_version("Gst", "1.0")
from gi.repository import Gio, GLib, Gst
Gst.init(None)
main_loop = GLib.MainLoop()
state = {"rgb": None, "rd_path": None, "sc_stream": None, "ready": False, "width": 1920, "height": 1080}
state_lock = threading.Lock()
bus_addr = os.environ.get("DBUS_SESSION_BUS_ADDRESS", "")
try:
    dbus_conn = Gio.DBusConnection.new_for_address_sync(
        bus_addr,
        Gio.DBusConnectionFlags.AUTHENTICATION_CLIENT | Gio.DBusConnectionFlags.MESSAGE_BUS_CONNECTION,
        None, None)
    rd = dbus_conn.call_sync("org.gnome.Mutter.RemoteDesktop", "/org/gnome/Mutter/RemoteDesktop",
        "org.gnome.Mutter.RemoteDesktop", "CreateSession",
        None, GLib.VariantType("(o)"), Gio.DBusCallFlags.NONE, -1, None)
    rd_path = rd.get_child_value(0).get_string()
    state["rd_path"] = rd_path
    props = dbus_conn.call_sync("org.gnome.Mutter.RemoteDesktop", rd_path,
        "org.freedesktop.DBus.Properties", "GetAll",
        GLib.Variant("(s)", ("org.gnome.Mutter.RemoteDesktop.Session",)),
        GLib.VariantType("(a{sv})"), Gio.DBusCallFlags.NONE, -1, None)
    sid = props.get_child_value(0).lookup_value("SessionId", None).get_string()
    sc = dbus_conn.call_sync("org.gnome.Mutter.ScreenCast", "/org/gnome/Mutter/ScreenCast",
        "org.gnome.Mutter.ScreenCast", "CreateSession",
        GLib.Variant("(a{sv})", ({"remote-desktop-session-id": GLib.Variant("s", sid)},)),
        GLib.VariantType("(o)"), Gio.DBusCallFlags.NONE, -1, None)
    sc_path = sc.get_child_value(0).get_string()
    stream_path = None
    try:
        dcfg = dbus_conn.call_sync("org.gnome.Mutter.DisplayConfig", "/org/gnome/Mutter/DisplayConfig",
            "org.gnome.Mutter.DisplayConfig", "GetCurrentState",
            None, GLib.VariantType("(ua((ssss)a(siiddada{sv})a{sv})a(iiduba(ssss)a{sv})a{sv})"),
            Gio.DBusCallFlags.NONE, -1, None)
        monitors = dcfg.get_child_value(1)
        for i in range(monitors.n_children()):
            connector = monitors.get_child_value(i).get_child_value(0).get_child_value(0).get_string()
            try:
                s = dbus_conn.call_sync("org.gnome.Mutter.ScreenCast", sc_path,
                    "org.gnome.Mutter.ScreenCast.Session", "RecordMonitor",
                    GLib.Variant("(sa{sv})", (connector, {"cursor-mode": GLib.Variant("u", 1)})),
                    GLib.VariantType("(o)"), Gio.DBusCallFlags.NONE, -1, None)
                stream_path = s.get_child_value(0).get_string()
                break
            except Exception:
                pass
    except Exception:
        pass
    if not stream_path:
        s = dbus_conn.call_sync("org.gnome.Mutter.ScreenCast", sc_path,
            "org.gnome.Mutter.ScreenCast.Session", "RecordVirtual",
            GLib.Variant("(a{sv})", ({"cursor-mode": GLib.Variant("u", 0), "is-recording": GLib.Variant("b", True)},)),
            GLib.VariantType("(o)"), Gio.DBusCallFlags.NONE, -1, None)
        stream_path = s.get_child_value(0).get_string()
    state["sc_stream"] = stream_path
except Exception as e:
    print("MUTTER_ERROR:" + str(e), file=sys.stderr, flush=True)
    sys.exit(1)

def _on_sample(sink):
    sample = sink.emit("pull-sample")
    buf = sample.get_buffer()
    caps = sample.get_caps()
    s = caps.get_structure(0)
    w = s.get_int("width")[1]; h = s.get_int("height")[1]
    data = buf.extract_dup(0, buf.get_size())
    with state_lock:
        state["rgb"] = bytes(data[:w * h * 3])
        state["width"] = w
        state["height"] = h
        if not state["ready"]:
            state["ready"] = True
            print("READY", file=sys.stderr, flush=True)
    return Gst.FlowReturn.OK

def _on_gst_bus(bus, msg):
    if msg.type == Gst.MessageType.ERROR:
        err, _ = msg.parse_error()
        print("GST_ERROR:" + str(err), file=sys.stderr, flush=True)

def _start_pipeline(nid):
    pipeline = Gst.Pipeline.new("rdp")
    src = Gst.ElementFactory.make("pipewiresrc", "src")
    conv = Gst.ElementFactory.make("videoconvert", "conv")
    sink = Gst.ElementFactory.make("appsink", "sink")
    sp, _ = Gst.Structure.from_string(
        "props,node.target=(string)" + str(nid) +
        ",media.class=(string)Stream/Input/Video"
        ",media.type=(string)Video,media.category=(string)Capture")
    src.set_property("stream-properties", sp)
    src.set_property("client-name", "noba-agent")
    sink.set_property("sync", False)
    sink.set_property("emit-signals", True)
    sink.set_property("max-buffers", 1)
    sink.set_property("drop", True)
    sink.connect("new-sample", _on_sample)
    pipeline.add(src); pipeline.add(conv); pipeline.add(sink)
    src.link(conv)
    conv.link_filtered(sink, Gst.Caps.from_string("video/x-raw,format=RGB"))
    gbus = pipeline.get_bus()
    gbus.add_signal_watch()
    gbus.connect("message", _on_gst_bus)
    pipeline.set_state(Gst.State.PLAYING)
    state["pipeline"] = pipeline

def _on_dbus_signal(conn, sender, obj_path, iface, sig, params, ud):
    if sig == "PipeWireStreamAdded":
        nid = params.get_child_value(0).get_uint32()
        GLib.idle_add(lambda: _start_pipeline(nid) or False)

dbus_conn.signal_subscribe(None, None, "PipeWireStreamAdded", stream_path,
    None, Gio.DBusSignalFlags.NONE, _on_dbus_signal, None)
dbus_conn.call_sync("org.gnome.Mutter.RemoteDesktop", rd_path,
    "org.gnome.Mutter.RemoteDesktop.Session", "Start",
    None, None, Gio.DBusCallFlags.NONE, -1, None)

def _inject(ev):
    rd = state.get("rd_path")
    sc = state.get("sc_stream")
    if not rd:
        return
    evt = ev.get("event", "")
    try:
        if evt == "mousemove" and sc:
            with state_lock:
                sw, sh = state["width"], state["height"]
            x = float(ev.get("x", 0)) * sw
            y = float(ev.get("y", 0)) * sh
            dbus_conn.call_sync("org.gnome.Mutter.RemoteDesktop", rd,
                "org.gnome.Mutter.RemoteDesktop.Session", "NotifyPointerMotionAbsolute",
                GLib.Variant("(sdd)", (sc, x, y)),
                None, Gio.DBusCallFlags.NONE, 100, None)
        elif evt in ("mousedown", "mouseup"):
            # Mutter uses Linux kernel button codes, not X11 button numbers
            _btn_map = {1: 272, 2: 274, 3: 273}  # left, middle, right
            btn = _btn_map.get(int(ev.get("button", 1)), 272)
            dbus_conn.call_sync("org.gnome.Mutter.RemoteDesktop", rd,
                "org.gnome.Mutter.RemoteDesktop.Session", "NotifyPointerButton",
                GLib.Variant("(ib)", (btn, evt == "mousedown")),
                None, Gio.DBusCallFlags.NONE, 100, None)
        elif evt == "wheel":
            steps = -1 if float(ev.get("delta_y", 0)) > 0 else 1
            dbus_conn.call_sync("org.gnome.Mutter.RemoteDesktop", rd,
                "org.gnome.Mutter.RemoteDesktop.Session", "NotifyPointerAxisDiscrete",
                GLib.Variant("(ui)", (0, steps)),
                None, Gio.DBusCallFlags.NONE, 100, None)
        elif evt in ("keydown", "keyup"):
            # NotifyKeyboardKeycode expects Linux evdev keycodes (not X11).
            # X11 hardware keycode = evdev + 8, so subtract 8 to convert.
            kc = max(0, int(ev.get("keycode", 0)) - 8)
            dbus_conn.call_sync("org.gnome.Mutter.RemoteDesktop", rd,
                "org.gnome.Mutter.RemoteDesktop.Session", "NotifyKeyboardKeycode",
                GLib.Variant("(ub)", (kc, evt == "keydown")),
                None, Gio.DBusCallFlags.NONE, 100, None)
    except Exception as e:
        print("INJECT_ERR:" + str(e), file=sys.stderr, flush=True)

def _cmd_loop():
    import select as _sel2
    for line in sys.stdin:
        cmd = line.strip()
        if cmd == "CAPTURE":
            with state_lock:
                rgb = state.get("rgb")
                w, h = state["width"], state["height"]
            if rgb:
                # NOBR = NOBA Raw: 4-byte magic + 4-byte w + 4-byte h + raw RGB bytes
                sys.stdout.buffer.write(b"NOBR" + struct.pack(">II", w, h) + rgb)
            else:
                sys.stdout.buffer.write(b"NONE")
            sys.stdout.buffer.flush()
        elif cmd == "STOP":
            GLib.idle_add(main_loop.quit)
            break
        elif cmd:
            try:
                ev = json.loads(cmd)
                # Coalesce stale mousemove events: drain all pending lines from
                # stdin and keep only the last mousemove, then process it.
                if ev.get("event") == "mousemove":
                    while _sel2.select([sys.stdin], [], [], 0)[0]:
                        peek = sys.stdin.readline().strip()
                        if not peek:
                            break
                        try:
                            pev = json.loads(peek)
                            if pev.get("event") == "mousemove":
                                ev = pev  # discard stale, keep newer
                            else:
                                _inject(ev)  # flush pending move first
                                ev = pev
                        except Exception:
                            break
                _inject(ev)
            except Exception:
                pass

threading.Thread(target=_cmd_loop, daemon=True).start()
main_loop.run()
