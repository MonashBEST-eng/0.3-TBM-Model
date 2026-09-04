# heartbeat_panel.py
# 5-second GUI<->STM heartbeat over MQTT, acting as a deadman's switch: if
# either side stops hearing from the other for 3 missed beats (15s), BOTH
# sides independently trip their own emergency stop -- the GUI arms the
# same shared E-STOP state as the mushroom button (see dashboard_panel.py),
# and the STM (separately, in its own firmware) broadcasts EMERGENCY_STOP
# on the CAN bus.
#
# Protocol:
#   GUI  -> "tbm/heartbeat"       / "PING"   every 5s
#   STM  -> "stm32/heartbeat_ack" / "PONG"   immediately on receiving a ping
#
# Recovery from a tripped heartbeat fault requires pressing the green
# RESUME button (create_resume_widget) -- it does NOT auto-clear just
# because pings start arriving again, mirroring how the E-STOP mushroom
# itself requires a deliberate reset rather than silently re-arming.
#
# Wiring this up in the main GUI:
#   1. import heartbeat_panel
#   2. heartbeat_panel.start_heartbeat_loop(root)   -- call once, after
#      the main window/widgets are built
#   3. In update_ui()'s "mqtt_rx" handling, when the topic is
#      "stm32/heartbeat_ack", call heartbeat_panel.on_heartbeat_ack()

import time
import tkinter as tk
import GTW_Control_Comms.gtw_mqtt_commands as command
import GUI_menus.dashboard_panel as dashboard_panel

# =========================
# TIMING
# =========================
PING_INTERVAL_MS = 5000     # how often the GUI sends a ping
TIMEOUT_MS       = 10500    # trips on the 2nd missed beat (10000 would be
                            # exactly 2x, so 10500 gives a small jitter
                            # allowance) - must match HEARTBEAT_TIMEOUT_MS
                            # in the STM firmware
LED_FLASH_MS     = 500      # flash period for the healthy-state LED
TEST_SUPPRESS_MS = 11500    # Test button withholds real pings for this long --
                            # slightly over TIMEOUT_MS so the watchdog genuinely trips

# =========================
# STATE
# =========================
_last_ack_time_ms      = None   # last confirmed heartbeat ACK from the STM
_link_fault            = False  # latched -- only _resume_pressed() clears it
_test_in_progress       = False
_test_suppress_until_ms = 0

_led_widgets   = []   # every flashing-LED Canvas currently on screen
_status_labels = []   # every status Label currently on screen
_led_flash_on  = False

_loop_started    = False
_next_ping_ms    = 0
_next_flash_ms   = 0


def _now_ms() -> int:
    return int(time.time() * 1000)


# =========================
# DRAWING / REFRESH
# =========================
def _draw_led(canvas):
    canvas.delete("all")
    w = int(canvas["width"])
    h = int(canvas["height"])
    if _link_fault:
        color = "#ef4444"   # solid red -- link lost
    else:
        color = "#facc15" if _led_flash_on else "#4b5563"   # flashing yellow while healthy
    canvas.create_oval(4, 4, w - 4, h - 4, fill=color, outline="#111827", width=2)


def _refresh_widgets():
    for cv in list(_led_widgets):
        if cv.winfo_exists():
            _draw_led(cv)
        else:
            _led_widgets.remove(cv)

    for lbl in list(_status_labels):
        if not lbl.winfo_exists():
            _status_labels.remove(lbl)
            continue
        if _link_fault:
            lbl.config(text="🔴 LINK LOST — PRESS RESUME", fg="#ef4444")
        elif _test_in_progress:
            lbl.config(text="🟡 TESTING HEARTBEAT...", fg="#facc15")
        else:
            lbl.config(text="🟡 HEARTBEAT OK", fg="#9ca3af")


# =========================
# FAULT TRIP / RESUME
# =========================
def _trip_fault(reason: str):
    global _link_fault
    if _link_fault:
        return
    _link_fault = True
    dashboard_panel.log_status(f"🚨 HEARTBEAT LOST — {reason}", tag="alarm")
    dashboard_panel.trip_emergency_external(f"heartbeat lost ({reason})")
    _refresh_widgets()


def _resume_pressed(event=None):
    """RESUME button handler -- clears both the heartbeat fault and the
    shared E-STOP state together (respecting the E-STOP's optional
    password-reset setting). If the password check fails/is cancelled,
    the fault stays latched exactly as it was."""
    global _link_fault, _test_in_progress, _last_ack_time_ms

    cleared = dashboard_panel.reset_emergency_external("heartbeat RESUME pressed")
    if not cleared:
        return

    _link_fault = False
    _test_in_progress = False
    _last_ack_time_ms = _now_ms()   # fresh window -- don't immediately re-trip
    dashboard_panel.log_status(
        "🟢 Heartbeat RESUME pressed — link monitoring re-armed", tag="info"
    )
    _refresh_widgets()


def _test_pressed(event=None):
    """Genuinely withholds outgoing pings for slightly over the timeout
    window, letting the REAL watchdog logic on both sides detect the loss
    and trip for real -- this proves the actual deadman's path works
    end-to-end (including the STM's own independent watchdog, which will
    also trip during this window since it stops receiving pings too, and
    will broadcast a real EMERGENCY_STOP on the CAN bus), rather than just
    faking the UI state. Recovery afterward still requires pressing RESUME,
    same as a genuine failure."""
    global _test_suppress_until_ms, _test_in_progress

    if _link_fault or _test_in_progress:
        return   # already tripped or already testing -- avoid double-triggering

    _test_suppress_until_ms = _now_ms() + TEST_SUPPRESS_MS
    _test_in_progress = True
    dashboard_panel.log_status(
        "🧪 Heartbeat test started — withholding real pings for "
        f"{TEST_SUPPRESS_MS // 1000}s to confirm the watchdog trips correctly "
        "(this WILL also trip the STM's own watchdog and a real E-STOP — "
        "this is intentional, it's testing the actual mechanism, not a "
        "simulation)",
        tag="warn",
    )
    _refresh_widgets()


def on_heartbeat_ack():
    """Call from the main GUI's update_ui() when an mqtt_rx arrives with
    topic 'stm32/heartbeat_ack'. Updates the last-seen time used for
    timeout detection -- does NOT auto-clear an existing fault, matching
    the mushroom button's manual-reset-only behavior."""
    global _last_ack_time_ms
    _last_ack_time_ms = _now_ms()


# =========================
# MAIN LOOP
# =========================
def _tick(root):
    global _led_flash_on, _next_ping_ms, _next_flash_ms

    now = _now_ms()

    # Send a ping every PING_INTERVAL_MS, unless a test is actively
    # withholding them.
    if now >= _next_ping_ms:
        _next_ping_ms = now + PING_INTERVAL_MS
        if now >= _test_suppress_until_ms:
            command.send_heartbeat()

    # Watchdog check -- only once we've heard from the STM at least once,
    # and only while not already tripped (avoids repeatedly re-logging).
    if _last_ack_time_ms is not None and not _link_fault:
        if now - _last_ack_time_ms > TIMEOUT_MS:
            reason = ("test — no ACK received during the withheld-ping window"
                      if _test_in_progress else
                      "no heartbeat ACK from STM within timeout")
            _trip_fault(reason)

    # Flash the LED while healthy
    if now >= _next_flash_ms:
        _next_flash_ms = now + LED_FLASH_MS
        _led_flash_on = not _led_flash_on
        _refresh_widgets()

    root.after(200, _tick, root)


def start_heartbeat_loop(root):
    """Call once from the main GUI after the window/widgets are built."""
    global _loop_started, _last_ack_time_ms
    if _loop_started:
        return
    _loop_started = True
    # Grace period: don't start timing out until the STM has had a real
    # chance to connect and ACK at least once.
    _last_ack_time_ms = None
    _tick(root)


# =========================
# WIDGETS
# =========================
def create_heartbeat_indicator(parent, bg: str, size: int = 22):
    """Small flashing LED + status label, ready to pack/grid anywhere
    (e.g. the splash screen). Cleans up its own registration automatically
    when the returned Frame is destroyed."""
    wrapper = tk.Frame(parent, bg=bg)

    canvas = tk.Canvas(wrapper, width=size, height=size, bg=bg, highlightthickness=0)
    canvas.pack(side="left", padx=(0, 8))
    _led_widgets.append(canvas)
    _draw_led(canvas)

    label = tk.Label(wrapper, text="🟡 HEARTBEAT OK", bg=bg, fg="#9ca3af",
                     font=("Segoe UI", 9, "bold"))
    label.pack(side="left")
    _status_labels.append(label)

    def _on_destroy(event):
        if canvas in _led_widgets:
            _led_widgets.remove(canvas)
        if label in _status_labels:
            _status_labels.remove(label)

    wrapper.bind("<Destroy>", _on_destroy)
    return wrapper


def create_resume_widget(parent, size: int = 130, bg: str = None):
    """Green RESUME/START button, styled to mirror
    dashboard_panel.create_estop_widget()'s mushroom-button look but
    green. Press to clear a tripped heartbeat fault (and the E-STOP it
    triggers) and resume normal monitoring."""
    container_bg = bg if bg is not None else "#111827"
    wrapper = tk.Frame(parent, bg=container_bg)

    canvas = tk.Canvas(wrapper, width=size, height=size, bg=container_bg,
                       highlightthickness=0, cursor="hand2")
    canvas.pack()
    canvas.bind("<Button-1>", _resume_pressed)

    w = h = size
    cx, cy = w // 2, h // 2
    plate = min(w, h) - 10
    x0, y0, x1, y1 = cx - plate // 2, cy - plate // 2, cx + plate // 2, cy + plate // 2

    # Green hazard-style base plate (mirrors the E-STOP's yellow one) with
    # the same corner-bolt detail for visual consistency.
    canvas.create_rectangle(x0, y0, x1, y1, fill="#bbf7d0", outline="#111827", width=4)
    for bx, by in [(x0 + 14, y0 + 14), (x1 - 14, y0 + 14), (x0 + 14, y1 - 14), (x1 - 14, y1 - 14)]:
        canvas.create_oval(bx - 5, by - 5, bx + 5, by + 5, fill="#374151", outline="")

    collar_r = plate * 0.36
    canvas.create_oval(cx - collar_r, cy - collar_r, cx + collar_r, cy + collar_r,
                       fill="#1f2937", outline="")

    btn_r = plate * 0.30
    canvas.create_oval(cx - btn_r, cy - btn_r, cx + btn_r, cy + btn_r,
                       fill="#16a34a", outline="#052e16", width=3)
    hl_r = btn_r * 0.55
    canvas.create_oval(cx - hl_r, cy - btn_r * 0.55, cx + hl_r, cy - btn_r * 0.55 + hl_r * 0.9,
                       fill="#22c55e", outline="")

    label = tk.Label(wrapper, text="START", bg=container_bg,
                     fg="#22c55e", font=("Segoe UI", 9, "bold"))
    label.pack(pady=(6, 0))

    return wrapper


def create_test_button(parent, bg: str = None):
    """Button that genuinely exercises the real watchdog path end-to-end
    (see _test_pressed's docstring) rather than faking the UI state."""
    container_bg = bg if bg is not None else "#111827"
    return tk.Button(
        parent, text="🧪  Test Heartbeat", command=_test_pressed,
        bg="#1f2937", fg="#facc15", relief="flat",
        font=("Segoe UI", 9, "bold"), padx=12, pady=8,
        activebackground="#374151", activeforeground="#facc15",
        cursor="hand2",
    )