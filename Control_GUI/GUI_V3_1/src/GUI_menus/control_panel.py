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
from IO_devices.odrive_controller import OdriveController

# ==================================================
# MODULE-LEVEL INSTANCE
# One OdriveController shared across the whole application, same pattern
# as get_button_box() in button_box_link_panel.py. It uses the same
# msg_queue as MQTT so ODrive status/heartbeat/encoder messages appear in
# the main GUI log/monitoring automatically.
# ==================================================
odrive_controller: OdriveController | None = None


def get_odrive_controller() -> OdriveController:
    """Return (creating if needed) the shared OdriveController instance."""
    global odrive_controller
    if odrive_controller is None:
        odrive_controller = OdriveController(command.msg_queue)
    return odrive_controller

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


AXIS_STATE_NAMES = {1: "IDLE", 8: "CLOSED LOOP"}

# Live ODrive telemetry labels, keyed "axis{node_id}_state"/"_pos"/"_vel".
# Populated by _build_odrive_card() while the panel is open; update_odrive_display()
# below checks before touching them, same guard pattern dashboard_panel.py
# uses for _comms_box/_status_box, so it's always safe to call even when
# the Control Panel isn't currently open.
_odrive_labels: dict[str, tk.Label] = {}


def update_odrive_display(node_id, position=None, velocity=None, axis_state=None, axis_error=None):
    """Call from the main GUI's update_ui() on odrive_heartbeat/odrive_encoder
    messages. Safe to call whether or not the Control Panel is open."""
    prefix = f"axis{node_id}"

    if position is not None and f"{prefix}_pos" in _odrive_labels:
        _odrive_labels[f"{prefix}_pos"].config(text=f"{position:.3f} turns")

    if velocity is not None and f"{prefix}_vel" in _odrive_labels:
        rps = velocity
        _odrive_labels[f"{prefix}_vel"].config(text=f"{rps:.3f} rps ({rps * 60.0:.1f} rpm)")

    if axis_state is not None and f"{prefix}_state" in _odrive_labels:
        lbl = _odrive_labels[f"{prefix}_state"]
        if axis_error:
            lbl.config(text=f"ERROR 0x{axis_error:08X}", fg="#ef4444")
        else:
            name = AXIS_STATE_NAMES.get(axis_state, f"STATE {axis_state}")
            lbl.config(text=name, fg="#22c55e" if axis_state == 8 else "#9ca3af")


def _build_odrive_card(parent, row, col):
    """ODrive motor control card - Start/Stop industrial buttons, an
    explicit speed entry, and live axis0/axis1 state+telemetry, driven over
    the H7 Ethernet<->CAN relay (see IO_devices/odrive_controller.py and
    GTW_Control_Comms/odrive_can.py). Same card frame/sizing as the other
    categories, blue-accented."""
    accent = "#38bdf8"
    card = tk.Frame(parent, bg=BG_CARD, width=CARD_SIZE, height=CARD_SIZE,
                    highlightbackground=accent, highlightthickness=1)
    card.grid(row=row, column=col, padx=8, pady=8)
    card.pack_propagate(False)

    tk.Frame(card, bg=accent, height=4).pack(fill="x")
    tk.Label(card, text="ODRIVE MOTOR", fg=accent, bg=BG_CARD,
             font=("Segoe UI", 10, "bold")).pack(pady=(10, 6))

    odrive = get_odrive_controller()
    odrive.start_loop()   # idempotent — safe even if the panel is reopened

    btn_area = tk.Frame(card, bg=BG_CARD)
    btn_area.pack()

    buttons = [
        ("START", "#22c55e", odrive.start),
        ("STOP",  "#ef4444", odrive.stop),
        ("SPEED\n+", "#facc15", lambda: odrive.nudge(2.0)),
        ("SPEED\n-", "#f97316", lambda: odrive.nudge(-2.0)),
    ]
    for i, (label, color, cmd) in enumerate(buttons):
        r, c = divmod(i, 2)
        btn = ui_widgets.make_industrial_button(btn_area, label, color, cmd, size=BUTTON_SIZE, bg=BG_CARD)
        btn.grid(row=r, column=c, padx=5, pady=5)

    # ---- explicit speed entry ----
    speed_frame = tk.Frame(card, bg=BG_CARD)
    speed_frame.pack(pady=(8, 4), fill="x", padx=14)
    speed_var = tk.StringVar(value="5.0")
    row_frame = tk.Frame(speed_frame, bg=BG_CARD)
    row_frame.pack(fill="x")
    tk.Entry(row_frame, textvariable=speed_var, width=6).pack(side="left")
    tk.Button(row_frame, text="SET turns/s", bg=accent, fg="black", relief="flat",
              font=("Segoe UI", 8, "bold"),
              command=lambda: odrive.set_speed(_safe_float(speed_var.get()))
    ).pack(side="left", padx=(6, 0))

    # ---- live telemetry ----
    telem = tk.Frame(card, bg=BG_CARD)
    telem.pack(pady=(6, 4))

    def _axis_col(col_idx, axis_name):
        tk.Label(telem, text=axis_name, fg="#6b7280", bg=BG_CARD,
                 font=("Segoe UI", 8, "bold")).grid(row=0, column=col_idx, padx=6)
        state_lbl = tk.Label(telem, text="UNKNOWN", fg="#9ca3af", bg=BG_CARD,
                              font=("Segoe UI", 9, "bold"))
        state_lbl.grid(row=1, column=col_idx, padx=6)
        pos_lbl = tk.Label(telem, text="-- turns", fg="#e5e7eb", bg=BG_CARD,
                            font=("Segoe UI", 8))
        pos_lbl.grid(row=2, column=col_idx, padx=6)
        vel_lbl = tk.Label(telem, text="-- rps", fg="#e5e7eb", bg=BG_CARD,
                            font=("Segoe UI", 8))
        vel_lbl.grid(row=3, column=col_idx, padx=6)
        return state_lbl, pos_lbl, vel_lbl

    axis0_state, axis0_pos, axis0_vel = _axis_col(0, "AXIS 0")
    axis1_state, axis1_pos, axis1_vel = _axis_col(1, "AXIS 1")

    _odrive_labels.update({
        "axis0_state": axis0_state, "axis0_pos": axis0_pos, "axis0_vel": axis0_vel,
        "axis1_state": axis1_state, "axis1_pos": axis1_pos, "axis1_vel": axis1_vel,
    })


def _safe_float(text, default=0.0):
    try:
        return float(text)
    except ValueError:
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
    total_cells = GRID_ROWS * GRID_COLS
    while len(categories) < total_cells:
        categories.append(None)   # placeholder marker for an empty slot

    for i, cat in enumerate(categories[:total_cells]):
        row, col = divmod(i, GRID_COLS)
        if cat is None:
            _build_placeholder_card(grid_container, row, col)
        elif cat == "__HEARTBEAT__":
            _build_heartbeat_card(grid_container, row, col)
        elif cat == "__CONVEYOR__":
            _build_conveyor_card(grid_container, row, col)
        elif cat == "__ODRIVE__":
            _build_odrive_card(grid_container, row, col)
        else:
            title, accent, buttons = cat
            _build_category_card(grid_container, row, col, title, accent, buttons)