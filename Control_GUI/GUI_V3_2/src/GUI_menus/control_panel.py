# control_panel.py
# TBM Control Panel — laid out as a 5x5 grid of category cards. Each card is
# one control category (Safety, Startup, Operation Mode, ...) built from
# round industrial pushbuttons (see ui_widgets.py), the same visual family
# as the dashboard's E-STOP mushroom button. Categories not yet defined show
# as a dashed placeholder card, ready for future control groups.

import tkinter as tk
import GTW_Control_Comms.gtw_mqtt_commands as command
import GUI_menus.ui_widgets as ui_widgets
import GUI_menus.heartbeat_panel as heartbeat_panel
from IO_devices.cutterhead_pcan_bridge import get_cutterhead_pcan

# ==================================================
# MODULE-LEVEL INSTANCE
# The cutterhead ODrive now runs over a direct PCAN-USB connection rather
# than the H7 Ethernet<->CAN relay - see cutterhead_pcan_bridge.py.
# get_cutterhead_pcan() there already implements the same
# shared-singleton pattern as get_button_box() in button_box_link_panel.py
# (create once, reuse everywhere), so nothing extra is needed here beyond
# importing it directly. The old IO_devices.odrive_controller.OdriveController
# (H7/MQTT-based) is left in place elsewhere in the project, unused, in
# case that path is ever needed again for a different axis.
# ==================================================

# Theme (match main GUI)
BG_MAIN  = "#0f172a"
BG_CARD  = "#1f2937"
BG_PANEL = "#111827"

GRID_COLS = 4
GRID_ROWS = 6
# All cards render at this exact square size (enforced via pack_propagate
# below) — sized generously enough for the busiest card (ODRIVE MOTOR:
# 4 buttons + speed entry + live telemetry) to fit without clipping at
# the BUTTON_SIZE below.
CARD_SIZE = 360
# One shared pushbutton size used everywhere — category buttons, conveyor,
# ODrive, and the heartbeat RESUME mushroom — so nothing looks oversized
# or undersized relative to anything else on the panel.
BUTTON_SIZE = 80

# Ceiling for the ODrive card's presets and slider, in turns/s. Kept as its
# own constant (rather than importing MAX_VELOCITY) so the panel's ceiling
# is visible here and can be lowered for bench testing without touching the
# controller. The controller still clamps to its own MAX_VELOCITY, so this
# can only ever be more conservative, never less.
ODRIVE_MAX_UI_SPEED = 35.0

# =========================
# CATEGORY DEFINITIONS
# (title, accent color, [ (label, button color, command_fn), ... ])
# Add a new tuple here to fill the next placeholder slot — no layout
# changes needed, the grid just fills in row-major order.
#
# The special string "__HEARTBEAT__" fills a slot with the link-heartbeat
# card (RESUME button, live LED, Test button) instead of a normal button
# category — see _build_heartbeat_card() below.
#
# The special string "__CONVEYOR__" fills a slot with the screw conveyer
# card (BLD-530S, G4 board) - START/STOP/FORWARD/REVERSE buttons plus a
# speed slider, since speed needs a real numeric value rather than fixed
# presets - see _build_conveyor_card() below.

# to make new category use this
# ("NEW CATEGORY", "#a78bfa", [
#     ("BUTTON\nLABEL", "#22c55e", lambda: command.some_function("ARG")),
# ]),

# =========================
def _categories():
    return [
        ("SAFETY", "#ef4444", [
            ("EMERGENCY\nSTOP",  "#ef4444", lambda: command.emergency_mode("EMERGENCY_STOP")),
            ("SAFE\nMODE",       "#22c55e", lambda: command.emergency_mode("SAFE_MODE")),
            ("CLEAR\nEMERGENCY", "#f97316", lambda: command.emergency_mode("CLEAR EMERGENCY")),
        ]),
        "__HEARTBEAT__",
        ("STARTUP", "#f97316", [
            ("INITIALIZE",   "#f97316", lambda: command.system_start_int_mode("INITIALIZE")),
            ("START\nSYSTEM", "#22c55e", lambda: command.system_start_int_mode("START_READY")),
        ]),
        "__CONVEYOR__",
        "__ODRIVE__",
        ("LED (H7 TEST)", "#facc15", [
            ("YELLOW\nLED", "#facc15", lambda: command.set_led("YELLOW LED")),
            ("RED\nLED",    "#ef4444", lambda: command.set_led("RED LED")),
        ]),
    ]


# =========================
# CARD BUILDERS
# =========================
def _build_category_card(parent, row, col, title, accent, buttons):
    card = tk.Frame(parent, bg=BG_CARD, width=CARD_SIZE, height=CARD_SIZE,
                    highlightbackground=accent, highlightthickness=1)
    card.grid(row=row, column=col, padx=8, pady=8)
    card.pack_propagate(False)

    tk.Frame(card, bg=accent, height=4).pack(fill="x")
    tk.Label(card, text=title, fg=accent, bg=BG_CARD,
             font=("Segoe UI", 10, "bold")).pack(pady=(10, 6))

    btn_area = tk.Frame(card, bg=BG_CARD)
    btn_area.pack(expand=True)

    cols = 3 if len(buttons) > 4 else 2
    for i, (label, color, cmd) in enumerate(buttons):
        r, c = divmod(i, cols)
        btn = ui_widgets.make_industrial_button(btn_area, label, color, cmd, size=BUTTON_SIZE, bg=BG_CARD)
        btn.grid(row=r, column=c, padx=6, pady=6)


def _build_conveyor_card(parent, row, col):
    """Screw conveyer card (BLD-530S, driven by the G4/MCP2515 board) -
    START/STOP/FORWARD/REVERSE as round industrial buttons like the other
    categories, plus a speed slider + SET SPEED button underneath, since
    speed needs a real 0-999 value the operator picks rather than a
    handful of fixed presets. Same card frame/sizing as the button
    categories, green-accented to match the conveyor's existing color."""
    accent = "#34d399"
    card = tk.Frame(parent, bg=BG_CARD, width=CARD_SIZE, height=CARD_SIZE,
                    highlightbackground=accent, highlightthickness=1)
    card.grid(row=row, column=col, padx=8, pady=8)
    card.pack_propagate(False)

    tk.Frame(card, bg=accent, height=4).pack(fill="x")
    tk.Label(card, text="CONVEYOR (BLD-530S)", fg=accent, bg=BG_CARD,
             font=("Segoe UI", 10, "bold")).pack(pady=(10, 6))

    btn_area = tk.Frame(card, bg=BG_CARD)
    btn_area.pack()

    buttons = [
        ("START",   "#22c55e", lambda: command.conveyer_control("START")),
        ("STOP",    "#ef4444", lambda: command.conveyer_control("STOP")),
        ("FORWARD", "#38bdf8", lambda: command.conveyer_control("FORWARD")),
        ("REVERSE", "#f472b6", lambda: command.conveyer_control("REVERSE")),
    ]
    for i, (label, color, cmd) in enumerate(buttons):
        r, c = divmod(i, 2)
        btn = ui_widgets.make_industrial_button(btn_area, label, color, cmd, size=BUTTON_SIZE, bg=BG_CARD)
        btn.grid(row=r, column=c, padx=5, pady=5)

    # ---- Speed slider ----
    speed_frame = tk.Frame(card, bg=BG_CARD)
    speed_frame.pack(pady=(10, 4), fill="x", padx=14)

    speed_var = tk.IntVar(value=0)
    speed_label = tk.Label(speed_frame, text="Speed: 0", fg="#e5e7eb", bg=BG_CARD,
                           font=("Segoe UI", 8, "bold"))
    speed_label.pack(anchor="w")

    def _update_label(val):
        speed_label.config(text=f"Speed: {int(float(val))}")

    speed_scale = tk.Scale(speed_frame, from_=0, to=999, orient="horizontal",
                           variable=speed_var, showvalue=False,
                           bg=BG_CARD, fg="#e5e7eb", troughcolor=BG_MAIN,
                           highlightthickness=0, command=_update_label,
                           length=180)
    speed_scale.pack(fill="x")

    tk.Button(speed_frame, text="SET SPEED", bg=accent, fg="black",
             relief="flat", font=("Segoe UI", 8, "bold"),
             command=lambda: command.conveyer_set_speed(speed_var.get())
    ).pack(pady=(4, 0), fill="x")


def _build_odrive_card(parent, row, col, columnspan=2):
    """Cutterhead motor control card - driven over a DIRECT PCAN-USB
    connection (see IO_devices/cutterhead_pcan_bridge.py and the
    unmodified control system in IO_devices/cutterhead_pcan/), not the
    H7 Ethernet<->CAN relay. This card previously drove the same ODrive
    over the H7 path; that path is now retired for this axis specifically
    (see the note near the top of 1_2026_GUI.py) in favour of this
    simpler, more reliable direct connection.

    This card SPANS TWO GRID COLUMNS and lays out in two internal columns,
    same as before. pack_propagate is off, so overflow clips rather than
    resizes - double width keeps every control visible while card HEIGHT
    stays uniform with the rest of the grid."""
    accent = "#38bdf8"
    width = CARD_SIZE * columnspan + 16 * (columnspan - 1)
    card = tk.Frame(parent, bg=BG_CARD, width=width, height=CARD_SIZE,
                    highlightbackground=accent, highlightthickness=1)
    card.grid(row=row, column=col, columnspan=columnspan, padx=8, pady=8)
    card.pack_propagate(False)

    tk.Frame(card, bg=accent, height=4).pack(fill="x")
    tk.Label(card, text="CUTTERHEAD (PCAN)", fg=accent, bg=BG_CARD,
             font=("Segoe UI", 10, "bold")).pack(pady=(8, 4))

    cutterhead = get_cutterhead_pcan()
    started = cutterhead.start_loop()   # idempotent - safe if panel is reopened

    body = tk.Frame(card, bg=BG_CARD)
    body.pack(fill="both", expand=True, padx=12, pady=(0, 8))

    left = tk.Frame(body, bg=BG_CARD)
    left.pack(side="left", anchor="n")
    right = tk.Frame(body, bg=BG_CARD)
    right.pack(side="left", anchor="n", padx=(16, 0), fill="both", expand=True)

    if not started:
        tk.Label(right, text=f"PCAN connect failed:\n{cutterhead.connect_error}",
                 fg="#ef4444", bg=BG_CARD, font=("Segoe UI", 8),
                 wraplength=280, justify="left").pack(anchor="w", pady=(4, 0))

    # speed_var is the single source of truth for target speed: the entry,
    # the preset buttons, the slider and START all read/write it, so the
    # displayed number always matches what a press will actually command.
    speed_var = tk.StringVar(value="5.0")
    slider_var = tk.DoubleVar(value=5.0)
    _syncing = {"busy": False}   # guards against slider<->entry feedback loops

    def _entry_speed():
        """Current entry value, or None if it isn't a valid number."""
        raw = speed_var.get()
        value = _safe_float(raw, default=None)
        if value is None:
            command.msg_queue.put((
                "odrive_status",
                f"[Cutterhead] Ignored speed entry {raw!r} - not a number."
            ))
        return value

    def _set_displayed(value):
        """Update entry + slider together without re-triggering each other."""
        _syncing["busy"] = True
        try:
            speed_var.set(f"{value:.2f}")
            slider_var.set(value)
        finally:
            _syncing["busy"] = False

    def _start_pressed():
        # Uses "speed <v>" rather than the bridge's plain start() - the
        # provided controller.py treats "start" as "ramp to the fixed
        # CRUISE_VELOCITY from config.py", ignoring whatever's in this
        # entry. "speed <v>" both wakes the axes AND targets the entry's
        # value in one command, matching what this button visually implies.
        value = _entry_speed()
        if value is None:
            return
        cutterhead.set_speed(value)

    def _apply_speed(event=None):
        value = _entry_speed()
        if value is None:
            return
        _set_displayed(min(value, ODRIVE_MAX_UI_SPEED))
        cutterhead.set_speed(value)

    # ---------- LEFT: main pushbuttons ----------
    # No CLEAR ERRORS button here - the provided PCAN control system has
    # no equivalent capability (no CAN Clear_Errors command implemented in
    # can_interface.py). If a fault needs clearing, that currently means
    # going over USB with odrivetool, same as during bench testing.
    buttons = [
        ("START", "#22c55e", _start_pressed),
        ("STOP",  "#ef4444", cutterhead.stop),
    ]
    for i, (label, color, cmd) in enumerate(buttons):
        btn = ui_widgets.make_industrial_button(left, label, color, cmd,
                                                size=BUTTON_SIZE, bg=BG_CARD)
        btn.grid(row=i, column=0, padx=5, pady=8)

    # ---------- RIGHT: entry ----------
    entry_row = tk.Frame(right, bg=BG_CARD)
    entry_row.pack(fill="x")

    speed_entry = tk.Entry(entry_row, textvariable=speed_var, width=6)
    speed_entry.pack(side="left")

    # This card lives inside a scrolling Canvas, where an Entry often never
    # takes keyboard focus on click - so typing goes nowhere and the value
    # silently stays at its initial value. Force focus explicitly.
    speed_entry.bind("<Button-1>", lambda e: speed_entry.focus_set())
    speed_entry.bind("<Return>", _apply_speed)

    tk.Button(entry_row, text="SET turns/s", bg=accent, fg="black", relief="flat",
              font=("Segoe UI", 8, "bold"), command=_apply_speed
    ).pack(side="left", padx=(6, 0))

    # ---------- RIGHT: percentage presets ----------
    tk.Label(right, text=f"PRESETS  (% of {ODRIVE_MAX_UI_SPEED:g} turns/s)",
             fg="#6b7280", bg=BG_CARD, font=("Segoe UI", 7, "bold")
    ).pack(anchor="w", pady=(8, 2))

    preset_row = tk.Frame(right, bg=BG_CARD)
    preset_row.pack(fill="x")

    def _preset(pct):
        value = ODRIVE_MAX_UI_SPEED * pct / 100.0
        _set_displayed(value)
        if pct == 0:
            cutterhead.stop()          # 0% is a real stop, not a 0 setpoint
        else:
            cutterhead.set_speed(value)

    for pct in (0, 25, 50, 75, 90, 100):
        colour = "#ef4444" if pct == 0 else ("#f97316" if pct >= 90 else BG_PANEL)
        fg = "black" if pct == 0 or pct >= 90 else "white"
        tk.Button(preset_row, text=f"{pct}%", bg=colour, fg=fg, relief="flat",
                  font=("Segoe UI", 8, "bold"), width=4,
                  command=lambda p=pct: _preset(p)
        ).pack(side="left", padx=2)

    # ---------- RIGHT: live slider ----------
    def _slider_moved(raw):
        # Fires continuously while dragging. The provided command_queue is
        # a plain queue.Queue (unbounded, no single-slot collapsing like
        # the old H7 controller had) - MotorController._drain_commands()
        # does drain it fully every tick though, so a fast drag still
        # only shows a brief lag rather than building up, provided the
        # loop period (config.LOOP_PERIOD, 0.05s) keeps up.
        if _syncing["busy"]:
            return
        value = float(raw)
        speed_var.set(f"{value:.2f}")
        cutterhead.set_speed(value)

    tk.Label(right, text="LIVE SPEED (applies as you drag)",
             fg="#6b7280", bg=BG_CARD, font=("Segoe UI", 7, "bold")
    ).pack(anchor="w", pady=(8, 0))

    tk.Scale(right, from_=0.0, to=ODRIVE_MAX_UI_SPEED, resolution=0.1,
             orient="horizontal", variable=slider_var, command=_slider_moved,
             bg=BG_CARD, fg="white", troughcolor=BG_PANEL,
             highlightthickness=0, sliderrelief="flat", length=260,
             font=("Segoe UI", 7)
    ).pack(anchor="w", fill="x")

    # ---------- RIGHT: live status ----------
    # Unlike the old H7 path, this connection is IN-PROCESS - no MQTT, no
    # msg_queue, no async heartbeat frames to wait for. Status is read
    # directly from the MotorController's own attributes (see
    # cutterhead_pcan_bridge.get_status()) via a plain polling loop.
    #
    # Per-axis position/velocity are deliberately NOT shown here: the
    # provided controller.py only computes those right before publishing
    # them over UDP to monitor.py (see telemetry.py), and duplicating that
    # request here would double the CAN traffic for the same data. Run
    # `python monitor.py` in a separate terminal (per the provided
    # README) for that detail - it works unmodified alongside this GUI.
    status_frame = tk.Frame(right, bg=BG_CARD)
    status_frame.pack(anchor="w", pady=(10, 0), fill="x")

    conn_lbl = tk.Label(status_frame, text="Connecting...", fg="#9ca3af", bg=BG_CARD,
                        font=("Segoe UI", 9, "bold"))
    conn_lbl.pack(anchor="w")
    state_lbl = tk.Label(status_frame, text="-- ", fg="#e5e7eb", bg=BG_CARD,
                         font=("Segoe UI", 8))
    state_lbl.pack(anchor="w")
    vel_lbl = tk.Label(status_frame, text="-- ", fg="#e5e7eb", bg=BG_CARD,
                       font=("Segoe UI", 8))
    vel_lbl.pack(anchor="w")

    def _poll_status():
        # Stop polling once the card's been destroyed (panel closed) -
        # checking winfo_exists() avoids scheduling .after() forever on a
        # dead widget, and avoids the same class of TclError the old H7
        # telemetry path had to guard against explicitly.
        if not card.winfo_exists():
            return

        status = cutterhead.get_status()
        try:
            if status["error"]:
                conn_lbl.config(text=f"ERROR: {status['error']}", fg="#ef4444")
            elif status["connected"]:
                conn_lbl.config(text="Connected", fg="#22c55e")
            else:
                conn_lbl.config(text="Not connected", fg="#9ca3af")

            axes_txt = "IDLE" if status["axes_idle"] else "CLOSED LOOP"
            running_txt = "RUNNING" if status["running"] else "stopped"
            state_lbl.config(
                text=f"{axes_txt}  |  {running_txt}",
                fg="#22c55e" if status["running"] else "#9ca3af",
            )
            vel_lbl.config(
                text=f"target={status['target_velocity']:.3f}  "
                     f"current={status['current_velocity']:.3f} turns/s"
            )
        except tk.TclError:
            return   # widgets torn down mid-update; next winfo_exists() check will stop this

        card.after(250, _poll_status)

    card.after(250, _poll_status)



def _safe_float(text, default=0.0):
    """Parse user-entered text. Returns `default` (which callers may set to
    None) rather than silently coercing junk to 0.0 - a bad entry that
    became 0.0 would read as a deliberate stop command."""
    try:
        return float(str(text).strip())
    except (ValueError, TypeError):
        return default


def _build_heartbeat_card(parent, row, col):
    """Link-heartbeat card: RESUME button (clears a tripped heartbeat
    fault and the E-STOP it triggers), a live flashing heartbeat LED, and
    a button that genuinely tests the deadman's-switch path end-to-end.
    Same card frame/sizing as every other category, and the RESUME
    "button" is sized to match the industrial pushbuttons everywhere else
    on the panel (BUTTON_SIZE) — yellow-accented to match the heartbeat's
    own warning-color theme, built from heartbeat_panel's own widgets
    instead of round industrial buttons."""
    card = tk.Frame(parent, bg=BG_CARD, width=CARD_SIZE, height=CARD_SIZE,
                    highlightbackground="#facc15", highlightthickness=1)
    card.grid(row=row, column=col, padx=8, pady=8)
    card.pack_propagate(False)

    tk.Frame(card, bg="#facc15", height=4).pack(fill="x")
    tk.Label(card, text="LINK HEARTBEAT", fg="#facc15", bg=BG_CARD,
             font=("Segoe UI", 10, "bold")).pack(pady=(10, 6))

    content = tk.Frame(card, bg=BG_CARD)
    content.pack(expand=True)

    heartbeat_panel.create_resume_widget(content, size=BUTTON_SIZE, bg=BG_CARD).pack(pady=(0, 14))
    heartbeat_panel.create_heartbeat_indicator(content, bg=BG_CARD, size=24).pack(pady=(0, 14))
    heartbeat_panel.create_test_button(content, bg=BG_CARD).pack()


def _build_placeholder_card(parent, row, col):
    card = tk.Frame(parent, bg=BG_MAIN, width=CARD_SIZE, height=CARD_SIZE,
                    highlightbackground="#1e2a3a", highlightthickness=1)
    card.grid(row=row, column=col, padx=8, pady=8)
    card.pack_propagate(False)

    inner = tk.Frame(card, bg=BG_MAIN)
    inner.place(relx=0.5, rely=0.5, anchor="center")

    ui_widgets.make_placeholder_slot(inner, size=64).pack()
    tk.Label(inner, text="FUTURE\nCONTROL CATEGORY", fg="#374151", bg=BG_MAIN,
             font=("Segoe UI", 8, "bold"), justify="center").pack(pady=(8, 0))


# =========================
# PANEL WINDOW
# =========================
def open_control_panel(root):
    panel = tk.Toplevel(root)
    panel.title("TBM Control Panel")
    panel.geometry("1550x1000")
    panel.configure(bg=BG_MAIN)

    tk.Label(panel, text="TBM CONTROL PANEL",
             fg="white", bg=BG_MAIN,
             font=("Segoe UI", 18, "bold")).pack(pady=10)

    # =========================
    # SCROLLABLE CONTAINER (in case the window is resized smaller)
    # =========================
    canvas = tk.Canvas(panel, bg=BG_MAIN, highlightthickness=0)
    scrollbar = tk.Scrollbar(panel, orient="vertical", command=canvas.yview)

    scroll_frame = tk.Frame(canvas, bg=BG_MAIN)
    scroll_frame.bind(
        "<Configure>",
        lambda e: canvas.configure(scrollregion=canvas.bbox("all"))
    )

    canvas.pack(side="left", fill="both", expand=True)
    scrollbar.pack(side="right", fill="y")

    def _on_canvas_resize(event):
        canvas.itemconfig(canvas_window, width=event.width)

    canvas_window = canvas.create_window((0, 0), window=scroll_frame, anchor="nw")
    canvas.configure(yscrollcommand=scrollbar.set)
    canvas.bind("<Configure>", _on_canvas_resize)

    def _on_mousewheel(event):
        canvas.yview_scroll(int(-1 * (event.delta / 120)), "units")
    canvas.bind_all("<MouseWheel>", _on_mousewheel)
    panel.bind("<Destroy>", lambda e: canvas.unbind_all("<MouseWheel>"))

    # =========================
    # 5x5 CATEGORY GRID
    # =========================
    grid_container = tk.Frame(scroll_frame, bg=BG_MAIN)
    grid_container.pack(padx=12, pady=6)

    categories = _categories()

    # Layout cursor. Most cards occupy one cell, but the ODrive card spans
    # two columns (it holds far more controls - see _build_odrive_card), so
    # a plain divmod() would let the next card overlap it. Walk cells
    # explicitly and skip past whatever each card consumed.
    def _span_of(cat):
        return 2 if cat == "__ODRIVE__" else 1

    placed = []          # (cat, row, col) in final positions
    row = col = 0
    for cat in categories:
        span = _span_of(cat)
        # Never split a wide card across a row boundary.
        if col + span > GRID_COLS:
            row += 1
            col = 0
        placed.append((cat, row, col))
        col += span
        if col >= GRID_COLS:
            row += 1
            col = 0

    # Fill out the remaining cells of the grid with placeholders.
    total_cells = GRID_ROWS * GRID_COLS
    used = sum(_span_of(c) for c, _, _ in placed)
    while used < total_cells:
        if col + 1 > GRID_COLS:
            row += 1
            col = 0
        placed.append((None, row, col))
        col += 1
        used += 1
        if col >= GRID_COLS:
            row += 1
            col = 0

    for cat, row, col in placed:
        if cat is None:
            _build_placeholder_card(grid_container, row, col)
        elif cat == "__HEARTBEAT__":
            _build_heartbeat_card(grid_container, row, col)
        elif cat == "__CONVEYOR__":
            _build_conveyor_card(grid_container, row, col)
        elif cat == "__ODRIVE__":
            _build_odrive_card(grid_container, row, col, columnspan=2)
        else:
            title, accent, buttons = cat
            _build_category_card(grid_container, row, col, title, accent, buttons)