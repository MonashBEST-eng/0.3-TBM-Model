# monitoring_panel.py
# Displays live sensor readings from the TBM across categorised sections.
# All values are placeholders — update via update_sensor(key, value) from update_ui()
# in the main GUI when real MQTT telemetry arrives.
#
# Threshold breaches also raise alarms in alarms_panel.py (auto-resolving —
# the alarm clears itself the moment the reading comes back into range).

import tkinter as tk
import time
import GUI_menus.alarms_panel as alarms_panel

# Theme (match main GUI)
BG_MAIN  = "#0f172a"
BG_CARD  = "#1f2937"
BG_PANEL = "#111827"
ACCENT   = "#22c55e"

# ==================================================
# SENSOR DEFINITIONS
# Each entry: (display_key, label, unit, color, warning_threshold, critical_threshold)
# Thresholds are upper limits — set to None to disable highlighting
# ==================================================
SENSORS = {
    # ---- THERMAL ----
    "TEMP_CUTTERHEAD":  ("Cutterhead Temp",     "°C",   "orange",  60,   80),
    "TEMP_MOTOR":       ("Motor Temp",           "°C",   "orange",  70,   90),
    "TEMP_HYDRAULIC":   ("Hydraulic Oil Temp",   "°C",   "orange",  55,   75),
    "TEMP_AMBIENT":     ("Ambient Temp",         "°C",   "orange",  40,   50),

    # ---- PRESSURE ----
    "PRESS_HYDRAULIC":  ("Hydraulic Pressure",   "bar",  "cyan",   180,  220),
    "PRESS_CUTTERHEAD": ("Cutterhead Face Press","bar",  "cyan",   150,  200),
    "PRESS_GREASE":     ("Grease Pressure",      "bar",  "cyan",    80,  120),
    "PRESS_AIR":        ("Air Supply Pressure",  "bar",  "cyan",     8,   10),

    # ---- ELECTRICAL ----
    "VOLT_MAIN":        ("Main Bus Voltage",     "V",    "#facc15", 260,  270),
    "VOLT_CONTROL":     ("Control Bus Voltage",  "V",    "#facc15",  26,   28),
    "CURR_CUTTERHEAD":  ("Cutterhead Current",   "A",    "#fb923c", 80,  100),
    "CURR_CONVEYOR":    ("Conveyor Current",     "A",    "#fb923c", 40,   55),
    "CURR_MOTOR":       ("Drive Motor Current",  "A",    "#fb923c", 90,  120),

    # ---- MOTION / MECHANICAL ----
    "RPM_CUTTERHEAD":   ("Cutterhead RPM",       "rpm",  "#a78bfa",  8,   12),
    "TORQUE_CUTTERHEAD":("Cutterhead Torque",    "kNm",  "#a78bfa", 80,  100),
    "SPEED_ADVANCE":    ("Advance Speed",        "mm/min","#a78bfa",80,  100),
    "FORCE_THRUST":     ("Thrust Force",         "kN",   "#a78bfa",2000,2500),

    # ---- FLOW ----
    "FLOW_HYDRAULIC":   ("Hydraulic Flow Rate",  "L/min","#34d399",  90,  110),
    "FLOW_COOLANT":     ("Coolant Flow Rate",    "L/min","#34d399",  40,   55),

    # ---- SYSTEM ----
    "BATTERY_SOC":      ("Battery SOC",          "%",    ACCENT,     20,   10),  # lower = warn for SOC

    # ---- ODRIVE (H7 Ethernet<->CAN relay) ----
    # Velocity thresholds sit just under MAX_VELOCITY / RAMP_RATE in
    # IO_devices/odrive_controller.py (35 turns/s cap) as an overspeed
    # sanity check on top of that cap, not a substitute for it.
    "ODRIVE_AXIS0_VEL": ("Axis 0 Velocity",      "turns/s", "#38bdf8", 30,  35),
    "ODRIVE_AXIS0_POS": ("Axis 0 Position",      "turns",   "#38bdf8", None, None),
    "ODRIVE_AXIS1_VEL": ("Axis 1 Velocity",      "turns/s", "#38bdf8", 30,  35),
    "ODRIVE_AXIS1_POS": ("Axis 1 Position",      "turns",   "#38bdf8", None, None),
}

# Holds references to the live value labels so update_sensor() can find them
_sensor_labels: dict[str, tk.Label] = {}


# ==================================================
# THRESHOLD ACCESS — used by the Settings panel
# SENSORS values are (label, unit, color, warn, crit) tuples; since tuples
# are immutable we rebuild the entry in place when a threshold changes.
# ==================================================
def get_threshold(key: str):
    """Returns (warn, crit) for a sensor key, or (None, None) if unknown."""
    if key not in SENSORS:
        return (None, None)
    _, _, _, warn, crit = SENSORS[key]
    return (warn, crit)


def set_threshold(key: str, warn, crit):
    """Update a sensor's warn/crit thresholds at runtime (e.g. from the
    Settings panel). Takes effect on the next update_sensor() call for
    that key — existing tile colors don't repaint until then."""
    if key not in SENSORS:
        return
    label_text, unit, color, _, _ = SENSORS[key]
    SENSORS[key] = (label_text, unit, color, warn, crit)


def apply_thresholds(overrides: dict):
    """Apply a batch of {sensor_key: {"warn": x, "crit": y}} overrides —
    called once at startup with whatever was saved to settings_store."""
    for key, vals in overrides.items():
        if key in SENSORS and "warn" in vals and "crit" in vals:
            set_threshold(key, vals["warn"], vals["crit"])


def update_sensor(key: str, value: float | str):
    """
    Call this from your main update_ui() loop to push a new reading.
    Example:
        if key == "TEMP": update_sensor("TEMP_CUTTERHEAD", val)

    Also raises/clears an alarm in alarms_panel.py based on the same
    thresholds used to color the tile.
    """
    if key not in SENSORS:
        return

    label_text, unit, color, warn, crit = SENSORS[key]

    # Format value
    if isinstance(value, float):
        text = f"{value:.1f} {unit}"
    else:
        text = f"{value} {unit}"

    # Determine color/severity based on thresholds
    display_color = color
    severity = None
    if warn is not None and crit is not None:
        try:
            fval = float(value)
            # SOC is inverted (low = bad), detect by checking warn > crit
            if warn > crit:
                if fval <= crit:
                    display_color = "#ef4444"   # red
                    severity = "critical"
                elif fval <= warn:
                    display_color = "#f97316"   # orange
                    severity = "warning"
            else:
                if fval >= crit:
                    display_color = "#ef4444"   # red
                    severity = "critical"
                elif fval >= warn:
                    display_color = "#f97316"   # orange
                    severity = "warning"
        except (ValueError, TypeError):
            pass

    # ---- Alarm hook — auto-raises/clears based on the same thresholds ----
    alarm_key = f"SENSOR_{key}"
    if severity:
        direction = "below" if warn > crit else "above"
        alarms_panel.raise_alarm(
            alarm_key, severity, label_text,
            f"{label_text} {direction} {severity} threshold ({text.strip()})"
        )
    else:
        alarms_panel.clear_alarm(alarm_key)

    if key in _sensor_labels:
        _sensor_labels[key].config(text=text, fg=display_color)


# ==================================================
# PANEL WINDOW
# ==================================================
def open_monitoring_panel(root):
    panel = tk.Toplevel(root)
    panel.title("TBM Sensor Monitoring")
    panel.geometry("860x700")
    panel.configure(bg=BG_MAIN)

    # Clear old label references when panel is reopened
    _sensor_labels.clear()

    # ---- Header ----
    hdr = tk.Frame(panel, bg=BG_PANEL)
    hdr.pack(fill="x")

    tk.Label(hdr, text="SENSOR MONITORING",
             fg="white", bg=BG_PANEL,
             font=("Segoe UI", 16, "bold")).pack(side="left", padx=16, pady=12)

    # Last-updated timestamp
    updated_var = tk.StringVar(value="")
    tk.Label(hdr, textvariable=updated_var,
             fg="gray", bg=BG_PANEL,
             font=("Segoe UI", 9)).pack(side="right", padx=16)

    def _tick():
        if panel.winfo_exists():
            updated_var.set(f"Last refresh  {time.strftime('%H:%M:%S')}")
            panel.after(1000, _tick)
    _tick()

    # ---- Scrollable canvas ----
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

    # Mouse-wheel scroll
    def _on_mousewheel(event):
        canvas.yview_scroll(int(-1 * (event.delta / 120)), "units")
    canvas.bind_all("<MouseWheel>", _on_mousewheel)
    panel.bind("<Destroy>", lambda e: canvas.unbind_all("<MouseWheel>"))

    container = scroll_frame

    # ==========================================
    # SECTION + TILE BUILDERS
    # ==========================================
    COLS = 4   # sensor tiles per row

    def create_section(title):
        frame = tk.Frame(container, bg=BG_CARD)
        frame.pack(fill="x", padx=12, pady=6)

        tk.Label(frame, text=title,
                 fg="cyan", bg=BG_CARD,
                 font=("Segoe UI", 10, "bold")
        ).pack(anchor="w", padx=12, pady=(8, 4))

        grid = tk.Frame(frame, bg=BG_CARD)
        grid.pack(fill="x", padx=8, pady=(0, 10))

        for col in range(COLS):
            grid.columnconfigure(col, weight=1)

        return grid

    def add_sensor_tile(grid, row, col, sensor_key):
        label_text, unit, color, _, _ = SENSORS[sensor_key]

        tile = tk.Frame(grid, bg=BG_MAIN, padx=8, pady=8)
        tile.grid(row=row, column=col, padx=5, pady=5, sticky="ew")

        # Sensor name
        tk.Label(tile, text=label_text,
                 fg="#9ca3af", bg=BG_MAIN,
                 font=("Segoe UI", 8)).pack(anchor="w")

        # Live value
        val_label = tk.Label(tile, text=f"-- {unit}",
                             fg=color, bg=BG_MAIN,
                             font=("Segoe UI", 15, "bold"))
        val_label.pack(anchor="w")

        # Status bar (green by default, changes colour with thresholds)
        status_bar = tk.Frame(tile, bg=ACCENT, height=3)
        status_bar.pack(fill="x", pady=(4, 0))

        _sensor_labels[sensor_key] = val_label

    # ==========================================
    # THERMAL SECTION
    # ==========================================
    sec = create_section("🌡  THERMAL")
    thermal_keys = ["TEMP_CUTTERHEAD", "TEMP_MOTOR", "TEMP_HYDRAULIC", "TEMP_AMBIENT"]
    for i, key in enumerate(thermal_keys):
        add_sensor_tile(sec, 0, i, key)

    # ==========================================
    # PRESSURE SECTION
    # ==========================================
    sec = create_section("⬤  PRESSURE")
    pressure_keys = ["PRESS_HYDRAULIC", "PRESS_CUTTERHEAD", "PRESS_GREASE", "PRESS_AIR"]
    for i, key in enumerate(pressure_keys):
        add_sensor_tile(sec, 0, i, key)

    # ==========================================
    # ELECTRICAL SECTION
    # ==========================================
    sec = create_section("⚡  ELECTRICAL")
    elec_keys = ["VOLT_MAIN", "VOLT_CONTROL", "CURR_CUTTERHEAD", "CURR_CONVEYOR",
                 "CURR_MOTOR"]
    for i, key in enumerate(elec_keys):
        add_sensor_tile(sec, i // COLS, i % COLS, key)

    # ==========================================
    # MOTION / MECHANICAL SECTION
    # ==========================================
    sec = create_section("⚙  MOTION & MECHANICAL")
    motion_keys = ["RPM_CUTTERHEAD", "TORQUE_CUTTERHEAD", "SPEED_ADVANCE", "FORCE_THRUST"]
    for i, key in enumerate(motion_keys):
        add_sensor_tile(sec, 0, i, key)

    # ==========================================
    # FLOW SECTION
    # ==========================================
    sec = create_section("〰  FLOW")
    flow_keys = ["FLOW_HYDRAULIC", "FLOW_COOLANT"]
    for i, key in enumerate(flow_keys):
        add_sensor_tile(sec, 0, i, key)

    # ==========================================
    # SYSTEM SECTION
    # ==========================================
    sec = create_section("🖥  SYSTEM")
    add_sensor_tile(sec, 0, 0, "BATTERY_SOC")

    # ==========================================
    # THRESHOLD LEGEND
    # ==========================================
    legend = tk.Frame(container, bg=BG_MAIN)
    legend.pack(fill="x", padx=12, pady=(4, 12))

    for colour, label in [("#34d399", "Normal"), ("#f97316", "Warning"), ("#ef4444", "Critical")]:
        dot = tk.Label(legend, text="●", fg=colour, bg=BG_MAIN, font=("Segoe UI", 10))
        dot.pack(side="left", padx=(8, 2))
        tk.Label(legend, text=label, fg="#9ca3af", bg=BG_MAIN,
                 font=("Segoe UI", 9)).pack(side="left", padx=(0, 12))