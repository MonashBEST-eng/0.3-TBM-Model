# dashboard_panel.py
# Live operations dashboard — E-STOP button, camera feeds, Ethernet comms log
# and control log. Sensor readings live in monitoring_panel.py; this panel
# stays focused on real-time control/safety and comms visibility. Opens as
# its own panel (Toplevel), matching monitoring_panel.py / control_panel.py /
# sbg_panel.py. Open it via the "Dashboard" sidebar button in the main GUI.
#
# Other modules (mainly the main GUI's update_ui loop) push data in via:
#   log_comms(msg, tag)
#   log_status(msg, tag)
#   log(msg)              # legacy alias -> log_status
#   add_alarm(msg)
#
# All of these are safe to call whether or not the panel is currently open —
# if it's closed they simply no-op, same as update_sbg() does in sbg_panel.py.

import tkinter as tk
from tkinter import simpledialog
import time
import GTW_Control_Comms.gtw_mqtt_commands as command
import GUI_menus.settings_store as settings_store
import GUI_menus.file_logger as file_logger
import GUI_menus.camera_streams as camera_streams

# Live camera feeds need opencv-python + Pillow. Both are already used
# elsewhere in this app, but we degrade gracefully (placeholders only) if
# either is missing on a given machine instead of crashing the whole panel.
try:
    import cv2
    from PIL import Image, ImageTk
    CAMERA_LIBS_AVAILABLE = True
except Exception:
    CAMERA_LIBS_AVAILABLE = False

# =========================
# THEME — matches main GUI
# =========================
BG_MAIN  = "#0f172a"
BG_PANEL = "#111827"
BG_CARD  = "#1f2937"
ACCENT   = "#22c55e"
TEXT     = "#e5e7eb"

MAX_LOG_LINES = 500   # cap both logs to avoid memory creep — tune via set_max_log_lines()

# How often (ms) each camera panel pulls a fresh frame off its CameraStream.
# 150ms ~= 6-7fps, which is plenty for a monitoring feed and keeps 3 streams
# worth of decode+resize+Tk redraw cheap on modest hardware.
CAMERA_REFRESH_MS = 150


def set_max_log_lines(n: int):
    """Called by the Settings panel (Alarms behavior → log line cap)."""
    global MAX_LOG_LINES
    MAX_LOG_LINES = max(50, int(n))   # floor of 50 so the logs can't be nuked to nothing

# =========================
# MODULE-LEVEL WIDGET REFS
# Populated when the panel is open, cleared on close.
# All update helpers below check these before touching widgets, so it's
# always safe to call them even if the panel isn't currently open.
# =========================
_comms_box: tk.Text | None = None
_status_box: tk.Text | None = None
_panel_ref: tk.Toplevel | None = None

# E-STOP button — latches like a real mushroom button: stays tripped across
# panel re-opens until explicitly reset, mirroring physical hardware.
# Multiple mushroom buttons can exist at once (the Dashboard's big one, plus
# a compact one in the sidebar) — they all share this one _estop_active
# flag and get redrawn together whenever either is pressed.
_estop_active: bool = False
_estop_widgets: list = []          # every mushroom Canvas currently on screen
_estop_status_labels: list = []    # every (Label, mode) pair; mode is "full" or "short"


# =========================
# MQTT COMMAND DECODER
# (moved here from the main GUI — only used to make the control log readable)
# =========================
def _decode_mqtt_command(mqtt_msg):
    """
    Convert raw MQTT topic/payload to human-readable command.
    mqtt_msg format: "topic | payload"
    Returns: Human-readable string or None
    """
    try:
        if " | " not in mqtt_msg:
            return None
        topic, payload = mqtt_msg.split(" | ", 1)

        if "EMERGENCY" in payload.upper():
            if "CLEAR" in payload.upper():
                return "🟢 Clear Emergency"
            elif "STOP" in payload.upper():
                return "🚨 EMERGENCY STOP"
            else:
                return "🚨 Emergency Command"

        if "SAFE_MODE" in payload.upper() or "SAFE MODE" in payload.upper():
            return "🟡 Safe Mode"

        if "EMERGENCY" in topic.upper():
            return "🚨 Emergency Command"

        if "operation_mode" in topic:
            if "AUTO" in payload:
                return "Mode → AUTO"
            elif "MANUAL" in payload:
                return "Mode → MANUAL"
            elif "MAINTENANCE" in payload:
                return "Mode → MAINTENANCE"

        if "cutterhead" in topic:
            if "speed_increase" in payload or "INCREASE" in payload:
                return "Cutterhead → Speed Increase"
            elif "speed_decrease" in payload or "DECREASE" in payload:
                return "Cutterhead → Speed Decrease"
            elif "slow_spin" in payload:
                return "Cutterhead → Slow Spin"
            elif "fast_spin" in payload:
                return "Cutterhead → Fast Spin"
            elif "STOP" in payload:
                return "Cutterhead → STOP"
            elif "ON" in payload or "START" in payload:
                return "Cutterhead → START"

        if "mobility" in topic:
            if "FORWARD" in payload:
                return "Advance → FORWARD"
            elif "REVERSE" in payload or "BACKWARD" in payload:
                return "Advance → REVERSE"
            elif "STOP" in payload:
                return "Advance → STOP"

        if "conveyor" in topic or "conveyer" in topic:
            if "ON" in payload or "START" in payload:
                return "Conveyor → ON"
            elif "OFF" in payload or "STOP" in payload:
                return "Conveyor → OFF"

        if "startup" in topic:
            if "READY" in payload:
                return "System → READY"
            elif "START" in payload:
                return "System → START SEQUENCE"

        if "odrive" in topic:
            if "STOP" in payload.upper():
                return "🛑 ODrive → STOP"
            elif "START" in payload.upper():
                return "🔧 ODrive → START"

        if "led" in topic:
            return f"LED → {payload}"

        topic_parts = topic.split("/")
        endpoint = topic_parts[-1] if topic_parts else topic
        return f"{endpoint.replace('_', ' ').title()} → {payload}"

    except Exception:
        return None


# =========================
# PUBLIC UPDATE HELPERS
# Safe to call regardless of whether the panel is open.
# =========================
def _append(box, msg, tag):
    box.insert(tk.END, msg + "\n", tag)
    box.see(tk.END)
    lines = int(box.index("end-1c").split(".")[0])
    if lines > MAX_LOG_LINES:
        box.delete("1.0", f"{lines - MAX_LOG_LINES}.0")


def log_comms(msg, tag="rx"):
    """Write to the Ethernet Comms log. tag: 'rx' | 'tx' | 'conn' | 'err'
    Always recorded to outputs/system_log.txt regardless of whether the
    Dashboard panel is open — only the live Text widget update is skipped
    when it's closed."""
    file_logger.log_to_file(msg, tag)
    if _comms_box is None:
        return
    t = time.strftime("%H:%M:%S")
    _append(_comms_box, f"[{t}] {msg}", tag)


def log_status(msg, tag="info"):
    """Write to the Control log. tag: 'info' | 'btn' | 'alarm' | 'warn'
    Always recorded to outputs/system_log.txt regardless of whether the
    Dashboard panel is open — only the live Text widget update is skipped
    when it's closed."""
    file_logger.log_to_file(msg, tag)
    if _status_box is None:
        return
    t = time.strftime("%H:%M:%S")
    _append(_status_box, f"[{t}] {msg}", tag)


def log(msg, color="white"):
    """Legacy alias — routes to the control log."""
    log_status(msg, tag="info")


def add_alarm(msg):
    log_status(f"ALARM: {msg}", tag="alarm")


def update_graph(v):
    """Kept as a no-op — graph panel was replaced by camera feeds."""
    pass


# =========================
# E-STOP MUSHROOM BUTTON
# Sends the same command as the Control Panel's "EMERGENCY STOP" button
# (command.emergency_mode) — this is just a bigger, harder-to-miss trigger
# for it, styled like a physical industrial e-stop. It latches: once pressed
# it stays tripped (button looks pushed-in, banner shown) until the RESET
# button is used, which sends the "CLEAR EMERGENCY" command.
# =========================
# Status text shown next to/under a mushroom button — "full" is the long
# sentence used on the Dashboard's big button, "short" is a compact version
# for tight spaces like the sidebar.
_STATUS_TEXT_FULL = {
    True:  "🚨  EMERGENCY STOP ACTIVE  —  cutterhead, conveyor and advance are locked out",
    False: "System armed — normal operation",
}
_STATUS_TEXT_SHORT = {
    True:  "🚨 TRIPPED",
    False: "E-STOP",
}


def _draw_estop(canvas):
    """Redraw the mushroom button in its current (armed/tripped) state.
    The caption ("PUSH FOR EMERGENCY STOP" / "TRIPPED — CLICK TO RESET")
    only draws if the canvas is big enough to hold it legibly — small
    sidebar-sized buttons skip it and rely on a separate short label instead."""
    canvas.delete("all")
    w = int(canvas["width"])
    h = int(canvas["height"])
    cx, cy = w // 2, h // 2

    plate = min(w, h) - 10
    x0, y0, x1, y1 = cx - plate // 2, cy - plate // 2, cx + plate // 2, cy + plate // 2

    # Yellow hazard base plate with black bolts at the corners
    canvas.create_rectangle(x0, y0, x1, y1, fill="#facc15", outline="#111827", width=4)
    for bx, by in [(x0 + 14, y0 + 14), (x1 - 14, y0 + 14), (x0 + 14, y1 - 14), (x1 - 14, y1 - 14)]:
        canvas.create_oval(bx - 5, by - 5, bx + 5, by + 5, fill="#374151", outline="")

    # Dark collar the mushroom head sits in
    collar_r = plate * 0.36
    canvas.create_oval(cx - collar_r, cy - collar_r, cx + collar_r, cy + collar_r,
                       fill="#1f2937", outline="")

    # The mushroom head itself — smaller / darker when pressed, to read as "pushed in"
    if _estop_active:
        btn_r, base, top = plate * 0.27, "#7f1d1d", "#991b1b"
    else:
        btn_r, base, top = plate * 0.30, "#dc2626", "#ef4444"

    canvas.create_oval(cx - btn_r, cy - btn_r, cx + btn_r, cy + btn_r,
                       fill=base, outline="#450a0a", width=3)
    hl_r = btn_r * 0.55
    canvas.create_oval(cx - hl_r, cy - btn_r * 0.55, cx + hl_r, cy - btn_r * 0.55 + hl_r * 0.9,
                       fill=top, outline="")

    if getattr(canvas, "_estop_show_caption", True) and w >= 130:
        label = "TRIPPED — CLICK TO RESET" if _estop_active else "PUSH FOR EMERGENCY STOP"
        canvas.create_text(cx, y1 - 12, text=label, fill="#111827", font=("Segoe UI", 10, "bold"))


def _redraw_all_estop_widgets():
    """Shared redraw logic - used by _estop_pressed() below and by the
    public trip/reset hooks, so all three code paths stay in sync."""
    for cv in list(_estop_widgets):
        if cv.winfo_exists():
            _draw_estop(cv)
        else:
            _estop_widgets.remove(cv)

    for entry in list(_estop_status_labels):
        lbl, mode = entry
        if lbl.winfo_exists():
            text_map = _STATUS_TEXT_FULL if mode == "full" else _STATUS_TEXT_SHORT
            lbl.config(text=text_map[_estop_active], fg="#ef4444" if _estop_active else "#6b7280")
        else:
            _estop_status_labels.remove(entry)


def trip_emergency_external(reason: str):
    """Public hook for other modules (e.g. heartbeat_panel's watchdog) to
    trip the shared E-STOP state without needing to know its internal
    implementation. Behaves exactly like a mushroom-button press while
    armed - no-ops if already tripped."""
    global _estop_active
    if _estop_active:
        return
    _estop_active = True
    command.emergency_mode("EMERGENCY_STOP")
    log_status(f"🚨 EMERGENCY STOP — {reason}", tag="alarm")
    _redraw_all_estop_widgets()


def reset_emergency_external(reason: str) -> bool:
    """Public hook to clear the shared E-STOP state - same password-gated
    behavior as clicking the mushroom while tripped (respects Settings ->
    Safety's optional reset password). Returns True if actually cleared,
    False if the password check failed or was cancelled (caller should NOT
    treat the fault as resolved in that case)."""
    global _estop_active
    if not _estop_active:
        return True

    if settings_store.get("safety", "estop_reset_password_enabled", default=False):
        required = settings_store.get("safety", "estop_reset_password", default="")
        entered = simpledialog.askstring(
            "Confirm Reset", "Enter password to reset emergency stop:", show="*"
        )
        if entered != required:
            if entered is not None:
                log_status("⚠ Emergency stop reset attempt failed — wrong password", tag="warn")
            return False

    _estop_active = False
    command.emergency_mode("CLEAR EMERGENCY")
    log_status(f"🟢 Emergency stop reset — {reason}", tag="info")
    _redraw_all_estop_widgets()
    return True


def _estop_pressed(event=None):
    """Handles clicks on the mushroom button — arms or resets depending on state."""
    global _estop_active
    if not _estop_active:
        _estop_active = True
        command.emergency_mode("EMERGENCY_STOP")
        log_status("🚨 EMERGENCY STOP — mushroom button pressed", tag="alarm")
    else:
        # Resetting a tripped e-stop can optionally require a password,
        # set in Settings → Safety, so it can't be cleared by an accidental click.
        if settings_store.get("safety", "estop_reset_password_enabled", default=False):
            required = settings_store.get("safety", "estop_reset_password", default="")
            entered = simpledialog.askstring(
                "Confirm Reset", "Enter password to reset emergency stop:", show="*"
            )
            if entered != required:
                if entered is not None:   # user typed something wrong, vs. cancelled
                    log_status("⚠ Emergency stop reset attempt failed — wrong password", tag="warn")
                return

        _estop_active = False
        command.emergency_mode("CLEAR EMERGENCY")
        log_status("🟢 Emergency stop reset — cleared from dashboard", tag="info")

    _redraw_all_estop_widgets()


def _build_estop_section(parent):
    """Builds the E-STOP card and wires it up. Call once per panel open.
    Returns (canvas, banner) so the caller can de-register them on close."""
    card = tk.Frame(parent, bg=BG_CARD)
    card.pack(fill="x", padx=15, pady=(12, 0))

    inner = tk.Frame(card, bg=BG_CARD)
    inner.pack(fill="x", padx=12, pady=12)

    canvas = tk.Canvas(inner, width=160, height=160, bg=BG_CARD, highlightthickness=0)
    canvas.pack(side="left", padx=(0, 20))
    canvas.bind("<Button-1>", _estop_pressed)
    _estop_widgets.append(canvas)
    _draw_estop(canvas)

    text_col = tk.Frame(inner, bg=BG_CARD)
    text_col.pack(side="left", fill="both", expand=True)

    tk.Label(text_col, text="EMERGENCY STOP", fg="#ef4444", bg=BG_CARD,
             font=("Segoe UI", 14, "bold")).pack(anchor="w")

    banner = tk.Label(text_col, text=_STATUS_TEXT_FULL[_estop_active],
                      fg="#ef4444" if _estop_active else "#6b7280", bg=BG_CARD,
                      font=("Segoe UI", 10, "bold"), wraplength=900, justify="left")
    banner.pack(anchor="w", pady=(6, 0))
    _estop_status_labels.append((banner, "full"))

    tk.Label(text_col,
             text="Sends the same command as the Control Panel's EMERGENCY STOP button. "
                  "Click the mushroom again (or it will read RESET) to clear once it's safe to resume.",
             fg="#4b5563", bg=BG_CARD, font=("Segoe UI", 8), wraplength=900,
             justify="left").pack(anchor="w", pady=(4, 0))

    return canvas, banner


def create_estop_widget(parent, size: int = 130, bg: str = None):
    """
    Standalone mushroom E-STOP button for embedding anywhere in the app
    (e.g. the sidebar) — shares the exact same armed/tripped state as the
    Dashboard's big E-STOP button. Pressing either one arms or resets both,
    and both redraw together immediately.

    Returns a Frame (containing the button + a compact "E-STOP"/"TRIPPED"
    status label) ready to pack/grid/place directly. Cleans up its own
    registration automatically when the returned Frame is destroyed.
    """
    container_bg = bg if bg is not None else BG_PANEL
    wrapper = tk.Frame(parent, bg=container_bg)

    canvas = tk.Canvas(wrapper, width=size, height=size, bg=container_bg,
                       highlightthickness=0, cursor="hand2")
    canvas._estop_show_caption = False   # this widget has its own label below instead
    canvas.pack()
    canvas.bind("<Button-1>", _estop_pressed)
    _estop_widgets.append(canvas)
    _draw_estop(canvas)

    label = tk.Label(wrapper, text=_STATUS_TEXT_SHORT[_estop_active], bg=container_bg,
                     fg="#ef4444" if _estop_active else "#6b7280",
                     font=("Segoe UI", 9, "bold"))
    label.pack(pady=(6, 0))
    _estop_status_labels.append((label, "short"))

    def _on_destroy(event):
        if canvas in _estop_widgets:
            _estop_widgets.remove(canvas)
        entry = (label, "short")
        if entry in _estop_status_labels:
            _estop_status_labels.remove(entry)

    wrapper.bind("<Destroy>", _on_destroy)
    return wrapper


# =========================
# PANEL WINDOW
# =========================
def open_dashboard_panel(root):
    global _panel_ref, _comms_box, _status_box

    # If already open, just bring it to front instead of making a duplicate
    if _panel_ref is not None and _panel_ref.winfo_exists():
        _panel_ref.lift()
        _panel_ref.focus_force()
        return

    panel = tk.Toplevel(root)
    panel.title("TBM Dashboard")
    panel.geometry("1600x900")
    panel.configure(bg=BG_MAIN)
    _panel_ref = panel

    # =========================
    # SCROLLABLE CONTENT AREA
    # =========================
    content_outer = tk.Frame(panel, bg=BG_MAIN)
    content_outer.pack(fill="both", expand=True)

    content_canvas = tk.Canvas(content_outer, bg=BG_MAIN, highlightthickness=0)
    content_scroll = tk.Scrollbar(content_outer, orient="vertical",
                                   command=content_canvas.yview)
    content_canvas.configure(yscrollcommand=content_scroll.set)

    content_canvas.pack(side="left", fill="both", expand=True)
    content_scroll.pack(side="right", fill="y")

    content = tk.Frame(content_canvas, bg=BG_MAIN)

    def _on_content_configure(e):
        content_canvas.configure(scrollregion=content_canvas.bbox("all"))

    def _on_canvas_width(e):
        content_canvas.itemconfig(_content_window, width=e.width)

    content.bind("<Configure>", _on_content_configure)
    content_canvas.bind("<Configure>", _on_canvas_width)

    _content_window = content_canvas.create_window((0, 0), window=content, anchor="nw")

    def _on_mousewheel(event):
        content_canvas.yview_scroll(int(-1 * (event.delta / 120)), "units")
    content_canvas.bind_all("<MouseWheel>", _on_mousewheel)

    # =========================
    # E-STOP MUSHROOM BUTTON — front and centre, above everything else
    # =========================
    _estop_dashboard_canvas, _estop_dashboard_banner = _build_estop_section(content)

    # =========================
    # CAMERA FEEDS — 3 live RTSP feeds (DVR x2 + PoE x1), via camera_streams.py.
    # Each panel polls its CameraStream on a Tk `after()` timer and draws the
    # latest frame onto its own Canvas; falls back to the old "disconnected"
    # placeholder graphic whenever a stream has no frame yet (or cv2/Pillow
    # aren't installed on this machine at all).
    # =========================
    cam_row = tk.Frame(content, bg=BG_MAIN)
    cam_row.pack(fill="both", expand=True, padx=15, pady=(10, 6))
    for _c in range(3):
        cam_row.columnconfigure(_c, weight=1)

    # (canvas, after_job_id) pairs for the 3 camera update loops, so _on_close
    # can cancel each one on the SAME widget that scheduled it — cancelling
    # a Tk `after()` job from a *different* widget than the one that created
    # it (e.g. the Toplevel instead of the Canvas) corrupts that widget's
    # destroy bookkeeping and throws "can't delete Tcl command"; confirmed
    # with a minimal repro before settling on this fix.
    _camera_after_jobs = []

    def make_camera_panel(parent, col, cam_name, supports_guideline_removal):
        frame = tk.Frame(parent, bg=BG_CARD)
        frame.grid(row=0, column=col, sticky="nsew",
                   padx=(0 if col == 0 else 6, 6 if col < 2 else 0))
        frame.rowconfigure(1, weight=1)
        frame.columnconfigure(0, weight=1)

        hdr = tk.Frame(frame, bg=BG_CARD)
        hdr.grid(row=0, column=0, sticky="ew", padx=10, pady=(8, 0))

        tk.Label(hdr, text=f"📷  {cam_name}",
                 fg="white", bg=BG_CARD,
                 font=("Segoe UI", 11, "bold")).pack(side="left")

        cam_dot = tk.Label(hdr, text="●", fg="#ef4444", bg=BG_CARD,
                           font=("Segoe UI", 12))
        cam_dot.pack(side="right", padx=(0, 4))

        status_lbl = tk.Label(hdr, text="No Signal",
                 fg="gray", bg=BG_CARD,
                 font=("Segoe UI", 9))
        status_lbl.pack(side="right", padx=(0, 6))

        feed = tk.Canvas(frame, bg="#0a0a0a", highlightthickness=0)
        feed.grid(row=1, column=0, sticky="nsew", padx=10, pady=8)
        feed._photo = None        # keep a ref alive so Tk doesn't GC the PhotoImage
        feed._image_item = None   # canvas item id of the live video image, once created

        def _draw_placeholder(event=None):
            feed.delete("placeholder")
            w = feed.winfo_width()
            h = feed.winfo_height()
            if w < 2 or h < 2:
                return

            for i in range(0, w, 40):
                feed.create_line(i, 0, i, h, fill="#1a1a2e", tags="placeholder")
            for j in range(0, h, 40):
                feed.create_line(0, j, w, j, fill="#1a1a2e", tags="placeholder")

            cx, cy = w // 2, h // 2
            feed.create_line(cx - 20, cy, cx + 20, cy, fill="#374151", width=2, tags="placeholder")
            feed.create_line(cx, cy - 20, cx, cy + 20, fill="#374151", width=2, tags="placeholder")

            bw, bh = 80, 54
            bx, by = cx - bw // 2, cy - bh // 2 - 10
            feed.create_rectangle(bx, by, bx + bw, by + bh,
                                   outline="#374151", width=2, tags="placeholder")
            feed.create_oval(cx - 16, cy - 26, cx + 16, cy + 2,
                             outline="#374151", width=2, tags="placeholder")
            feed.create_rectangle(bx + bw - 18, by - 8, bx + bw - 6, by,
                                   outline="#374151", width=2, tags="placeholder")

            msg = "CAMERA DISCONNECTED" if CAMERA_LIBS_AVAILABLE else "opencv/Pillow not installed"
            feed.create_text(cx, cy + 34,
                             text=msg,
                             fill="#4b5563", font=("Segoe UI", 10, "bold"),
                             tags="placeholder")
            feed.create_text(cx, cy + 52,
                             text="Waiting for video source..." if CAMERA_LIBS_AVAILABLE
                                  else "pip install opencv-python pillow",
                             fill="#374151", font=("Segoe UI", 8),
                             tags="placeholder")

        feed.bind("<Configure>", _draw_placeholder)
        _draw_placeholder()

        def _show_frame(frame_bgr, w, h):
            """Convert one BGR OpenCV frame to a Tk PhotoImage, scaled/letterboxed
            to fit the canvas, and draw it in place of the placeholder."""
            if supports_guideline_removal and camera_streams.guideline_removal_enabled():
                try:
                    frame_bgr = camera_streams.remove_guidelines(frame_bgr, col)
                except Exception:
                    pass   # bad frame shape etc. — just show it un-filtered this tick

            frame_rgb = cv2.cvtColor(frame_bgr, cv2.COLOR_BGR2RGB)
            fh, fw = frame_rgb.shape[:2]
            scale = min(w / fw, h / fh)
            nw, nh = max(1, int(fw * scale)), max(1, int(fh * scale))
            frame_rgb = cv2.resize(frame_rgb, (nw, nh))

            photo = ImageTk.PhotoImage(Image.fromarray(frame_rgb))
            feed.delete("placeholder")
            if feed._image_item is None:
                feed._image_item = feed.create_image(w // 2, h // 2, image=photo, tags="live")
            else:
                feed.coords(feed._image_item, w // 2, h // 2)
                feed.itemconfig(feed._image_item, image=photo)
            feed._photo = photo   # keep the only strong ref so it isn't garbage-collected

        def _update_frame():
            if not feed.winfo_exists():
                return   # panel/canvas destroyed — stop this update chain for good

            w, h = feed.winfo_width(), feed.winfo_height()
            frame_bgr = None
            stream_connected = False

            if CAMERA_LIBS_AVAILABLE:
                stream = camera_streams.get_stream(cam_name)
                if stream is not None:
                    stream_connected = stream.connected
                    frame_bgr = stream.read()

            if frame_bgr is not None and w > 2 and h > 2:
                try:
                    _show_frame(frame_bgr, w, h)
                    cam_dot.config(fg="#22c55e")
                    status_lbl.config(text="LIVE")
                except Exception:
                    frame_bgr = None   # fall through to placeholder below on a bad frame

            if frame_bgr is None:
                if feed._image_item is not None:
                    feed.delete(feed._image_item)
                    feed._image_item = None
                    feed._photo = None
                _draw_placeholder()
                cam_dot.config(fg="#f59e0b" if stream_connected else "#ef4444")
                status_lbl.config(text="Connecting…" if stream_connected else "No Signal")

            job = feed.after(CAMERA_REFRESH_MS, _update_frame)
            _camera_after_jobs.append((feed, job))

        _update_frame()

        return feed, cam_dot

    for _col, (_name, _url, _supports_gr) in enumerate(camera_streams.get_camera_sources()):
        make_camera_panel(cam_row, _col, _name, _supports_gr)

    # Kick off the 3 background RTSP connections now that the panels exist
    # to receive frames. stop_all() in _on_close tears them down again so
    # nothing keeps streaming while the Dashboard is closed.
    camera_streams.start_all()

    # =========================
    # LOG PANELS — side by side
    # =========================
    logs_row = tk.Frame(content, bg=BG_MAIN)
    logs_row.pack(fill="both", expand=True, padx=15, pady=(0, 15))
    logs_row.columnconfigure(0, weight=1)
    logs_row.columnconfigure(1, weight=1)

    # ---- LEFT: Ethernet / MQTT Comms Log ----
    comms_frame = tk.Frame(logs_row, bg=BG_CARD)
    comms_frame.grid(row=0, column=0, sticky="nsew", padx=(0, 6))

    comms_hdr = tk.Frame(comms_frame, bg=BG_CARD)
    comms_hdr.pack(fill="x", padx=10, pady=(8, 0))

    tk.Label(comms_hdr, text="⬡  ETHERNET COMMS LOG",
             fg="#38bdf8", bg=BG_CARD,
             font=("Segoe UI", 11, "bold")).pack(side="left")

    comms_box_local = tk.Text(comms_frame, bg=BG_MAIN, fg="#38bdf8",
                        font=("Consolas", 9), wrap="none")
    comms_box_local.pack(fill="both", expand=True, padx=10, pady=8)

    comms_box_local.tag_config("rx",   foreground="#38bdf8")
    comms_box_local.tag_config("tx",   foreground="#a3e635")
    comms_box_local.tag_config("conn", foreground="#fb923c")
    comms_box_local.tag_config("err",  foreground="#ef4444")

    # ---- RIGHT: Control Log ----
    status_frame = tk.Frame(logs_row, bg=BG_CARD)
    status_frame.grid(row=0, column=1, sticky="nsew", padx=(6, 0))

    tk.Label(status_frame, text="🎮  CONTROL LOG",
             fg="#a78bfa", bg=BG_CARD,
             font=("Segoe UI", 11, "bold")).pack(anchor="w", padx=10, pady=(8, 0))

    status_box_local = tk.Text(status_frame, bg=BG_MAIN, fg="#e5e7eb",
                         font=("Consolas", 9), wrap="none")
    status_box_local.pack(fill="both", expand=True, padx=10, pady=8)

    status_box_local.tag_config("btn",   foreground="#c084fc")
    status_box_local.tag_config("alarm", foreground="#ef4444")
    status_box_local.tag_config("info",  foreground="#e5e7eb")
    status_box_local.tag_config("warn",  foreground="#fb923c")

    _comms_box = comms_box_local
    _status_box = status_box_local

    log_comms("[DASHBOARD] Panel opened", tag="conn")
    log_status("[DASHBOARD] Panel opened", tag="info")

    # =========================
    # CLEANUP ON CLOSE
    # =========================
    def _on_close():
        global _panel_ref, _comms_box, _status_box
        content_canvas.unbind_all("<MouseWheel>")
        if _estop_dashboard_canvas in _estop_widgets:
            _estop_widgets.remove(_estop_dashboard_canvas)
        entry = (_estop_dashboard_banner, "full")
        if entry in _estop_status_labels:
            _estop_status_labels.remove(entry)

        # Stop the 3 camera update loops and tear down the RTSP connections —
        # no point decoding video for a window nobody can see. Each job is
        # cancelled on the SAME canvas that scheduled it (see note above).
        for feed_widget, job_id in _camera_after_jobs:
            try:
                feed_widget.after_cancel(job_id)
            except Exception:
                pass
        camera_streams.stop_all()

        _comms_box = None
        _status_box = None
        _panel_ref = None
        panel.destroy()

    panel.protocol("WM_DELETE_WINDOW", _on_close)
