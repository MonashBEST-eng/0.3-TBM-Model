# sbg_panel.py
# SBG Ellipse-A IMU data display panel.
# Shows company logo, all relevant axis/sensor data fields,
# and a live flight-style attitude indicator (artificial horizon).
#
# To feed live data call:  update_sbg(data_dict)
# where data_dict keys match SBG_FIELDS below.
# e.g. update_sbg({"roll": 12.3, "pitch": -5.1, "yaw": 180.0, ...})

import tkinter as tk
from tkinter import font as tkfont
import math
import os
import sys
import time
import GUI_menus.settings_store as settings_store

try:
    from PIL import Image, ImageTk
    PIL_AVAILABLE = True
except ImportError:
    PIL_AVAILABLE = False

# =========================
# THEME
# =========================
BG_MAIN  = "#0f172a"
BG_PANEL = "#111827"
BG_CARD  = "#1f2937"
ACCENT   = "#22c55e"
TEXT     = "#e5e7eb"

# =========================
# SBG ELLIPSE-A DATA FIELDS
# (key, display_label, unit, color)
# =========================
SBG_FIELDS = [
    # --- Attitude ---
    ("roll",            "Roll",              "°",      "#38bdf8"),
    ("pitch",           "Pitch",             "°",      "#38bdf8"),
    ("yaw",             "Yaw / Heading",     "°",      "#38bdf8"),

    # --- Angular Rate ---
    ("gyro_x",          "Gyro X",            "°/s",    "#a78bfa"),
    ("gyro_y",          "Gyro Y",            "°/s",    "#a78bfa"),
    ("gyro_z",          "Gyro Z",            "°/s",    "#a78bfa"),

    # --- Acceleration ---
    ("accel_x",         "Accel X",           "m/s²",   "#fb923c"),
    ("accel_y",         "Accel Y",           "m/s²",   "#fb923c"),
    ("accel_z",         "Accel Z",           "m/s²",   "#fb923c"),

    # --- Velocity ---
    ("vel_north",       "Velocity North",    "m/s",    "#34d399"),
    ("vel_east",        "Velocity East",     "m/s",    "#34d399"),
    ("vel_down",        "Velocity Down",     "m/s",    "#34d399"),

    # --- Position ---
    ("latitude",        "Latitude",          "°",      "#facc15"),
    ("longitude",       "Longitude",         "°",      "#facc15"),
    ("altitude",        "Altitude",          "m",      "#facc15"),

    # --- Status ---
    ("solution_mode",   "Solution Mode",     "",       ACCENT),
    ("gps_fix",         "GPS Fix",           "",       ACCENT),
    ("num_svs",         "Satellites",        "",       ACCENT),
    ("heading_accuracy","Heading Accuracy",  "°",      "#fb923c"),
    ("position_accuracy","Position Accuracy","m",      "#fb923c"),
]

# Internal label ref store — updated by update_sbg()
_field_labels: dict[str, tk.Label] = {}

# Attitude state for the gyroscope canvas
_attitude = {"roll": 0.0, "pitch": 0.0, "yaw": 0.0}
_gyro_canvas: tk.Canvas | None = None


def update_sbg(data: dict):
    """
    Push new SBG data to the panel.
    Call from your MQTT/serial update loop whenever SBG data arrives.
    data = {"roll": 0.0, "pitch": -2.1, "yaw": 90.0, ...}
    """
    for key, value in data.items():
        if key in _field_labels:
            lbl = _field_labels[key]
            # Find unit for this field
            unit = next((f[2] for f in SBG_FIELDS if f[0] == key), "")
            try:
                lbl.config(text=f"{float(value):.3f} {unit}".strip())
            except (ValueError, TypeError):
                lbl.config(text=str(value))

        # Update attitude state for gyroscope
        if key in ("roll", "pitch", "yaw"):
            _attitude[key] = float(value)

    # Redraw gyroscope if canvas exists
    if _gyro_canvas is not None:
        _draw_attitude(_gyro_canvas)


# ==================================================
# ATTITUDE INDICATOR DRAWING
# ==================================================
def _draw_attitude(canvas: tk.Canvas):
    canvas.delete("all")
    w = canvas.winfo_width()
    h = canvas.winfo_height()
    if w < 10 or h < 10:
        return

    cx, cy = w // 2, h // 2
    r = min(cx, cy) - 8   # radius of the instrument

    roll_deg = _attitude["roll"]
    pitch_deg = max(-45, min(45, _attitude["pitch"]))  # Clamp pitch to ±45°
    yaw_deg = _attitude["yaw"]

    roll = math.radians(roll_deg)
    pitch = pitch_deg

    sin_r, cos_r = math.sin(roll), math.cos(roll)

    # ---- Static background: blue sky on top, brown ground on bottom ----
    # Sky (top half)
    sky_pts = []
    for i in range(181):
        angle = math.radians(i)  # 0° to 180° (top semicircle)
        sky_pts.extend([cx + r * math.cos(angle), cy - r * math.sin(angle)])
    canvas.create_polygon(sky_pts, fill="#1e3a5f", outline="")

    # Ground (bottom half)
    ground_pts = []
    for i in range(181):
        angle = math.radians(180 + i)  # 180° to 360° (bottom semicircle)
        ground_pts.extend([cx + r * math.cos(angle), cy - r * math.sin(angle)])
    canvas.create_polygon(ground_pts, fill="#5c3d1a", outline="")

    # ---- Rotating horizon line (offset by pitch, rotated by roll) ----
    horizon_offset = pitch * (r / 45.0)

    hx1 = cx - r * 1.5 * cos_r + horizon_offset * sin_r
    hy1 = cy - r * 1.5 * sin_r - horizon_offset * cos_r
    hx2 = cx + r * 1.5 * cos_r + horizon_offset * sin_r
    hy2 = cy + r * 1.5 * sin_r - horizon_offset * cos_r

    canvas.create_line(hx1, hy1, hx2, hy2, fill="white", width=3)

    # ---- Pitch ladder (rotates with roll, moves with pitch) ----
    for deg in range(-30, 31, 10):
        if deg == 0:
            continue
        offset = (deg + pitch) * (r / 45.0)
        lw = r * 0.35 if deg % 20 == 0 else r * 0.2
        x1 = cx - lw * cos_r + offset * sin_r
        y1 = cy - lw * sin_r - offset * cos_r
        x2 = cx + lw * cos_r + offset * sin_r
        y2 = cy + lw * sin_r - offset * cos_r
        canvas.create_line(x1, y1, x2, y2, fill="white", width=1)
        canvas.create_text(x2 + 6 * cos_r, y2 + 6 * sin_r,
                           text=str(abs(deg)), fill="white",
                           font=("Segoe UI", 7))

    # ---- Roll arc and tick marks ----
    arc_r = r - 6
    canvas.create_arc(cx - arc_r, cy - arc_r, cx + arc_r, cy + arc_r,
                      start=0, extent=180, style="arc",
                      outline="#aaaaaa", width=1)

    for tick_deg in [-60, -45, -30, -20, -10, 0, 10, 20, 30, 45, 60]:
        angle = math.radians(90 - tick_deg)
        tx1 = cx + (arc_r - 6) * math.cos(angle)
        ty1 = cy - (arc_r - 6) * math.sin(angle)
        tx2 = cx + arc_r * math.cos(angle)
        ty2 = cy - arc_r * math.sin(angle)
        canvas.create_line(tx1, ty1, tx2, ty2, fill="#aaaaaa", width=1)

    # Roll indicator triangle (rotates with roll)
    tri_angle = math.radians(90) - roll
    tip_x = cx + (arc_r - 12) * math.cos(tri_angle)
    tip_y = cy - (arc_r - 12) * math.sin(tri_angle)
    left_angle  = tri_angle + math.radians(10)
    right_angle = tri_angle - math.radians(10)
    lx = cx + arc_r * math.cos(left_angle)
    ly = cy - arc_r * math.sin(left_angle)
    rx = cx + arc_r * math.cos(right_angle)
    ry = cy - arc_r * math.sin(right_angle)
    canvas.create_polygon(tip_x, tip_y, lx, ly, rx, ry,
                          fill="white", outline="")

    # ---- Fixed aircraft symbol (center) ----
    # Wings
    canvas.create_line(cx - r*0.4, cy, cx - r*0.15, cy, fill="#facc15", width=3)
    canvas.create_line(cx + r*0.15, cy, cx + r*0.4, cy, fill="#facc15", width=3)
    # Fuselage dot
    canvas.create_oval(cx - 4, cy - 4, cx + 4, cy + 4, fill="#facc15", outline="")
    # Tail
    canvas.create_line(cx, cy, cx, cy - r*0.12, fill="#facc15", width=3)

    # ---- Outer bezel ring ----
    canvas.create_oval(cx - r, cy - r, cx + r, cy + r,
                       outline="#374151", width=3)

    # ---- Heading readout ----
    canvas.create_text(cx, cy + r + 14,
                       text=f"HDG  {yaw_deg:.1f}°",
                       fill="#38bdf8", font=("Segoe UI", 9, "bold"))

    # ---- Roll / Pitch readouts ----
    canvas.create_text(cx - r + 2, cy + r + 14,
                       text=f"R {roll_deg:.1f}°",
                       fill="#a78bfa", font=("Segoe UI", 8), anchor="w")
    canvas.create_text(cx + r, cy + r + 14,
                       text=f"P {pitch_deg:.1f}°",
                       fill="#a78bfa", font=("Segoe UI", 8), anchor="e")


# ==================================================
# PANEL WINDOW
# ==================================================
def open_sbg_panel(root):
    from IO_devices.sbg_reader import SbgReader
    from tkinter import ttk
    import GTW_Control_Comms.gtw_mqtt_commands as gtw_mqtt_commands

    global _gyro_canvas
    _field_labels.clear()

    # Lazy-create shared SbgReader on root (one instance across reopens)
    if not hasattr(root, "_sbg_reader"):
        root._sbg_reader = SbgReader(gtw_mqtt_commands.msg_queue)
    sbg = root._sbg_reader

    panel = tk.Toplevel(root)
    panel.title("SBG Ellipse-A  —  IMU Data")
    panel.geometry("1000x820")
    panel.configure(bg=BG_MAIN)

    # ---- Header ----
    hdr = tk.Frame(panel, bg=BG_PANEL, height=60)
    hdr.pack(fill="x")
    hdr.pack_propagate(False)

    # SBG Logo - try both .png and .jpg, make it bigger
    logo_loaded = False
    if PIL_AVAILABLE:
        for filename in ["sbg_logo.png", "SBG_logo-bis_RVB_500.jpg"]:
            path = os.path.join(os.path.abspath("."), "GUI_images", filename)
            if not os.path.exists(path):
                path = os.path.join(getattr(sys, "_MEIPASS", "."), "GUI_images", filename)
            if os.path.exists(path):
                try:
                    img = Image.open(path).resize((180, 60), Image.LANCZOS)
                    photo = ImageTk.PhotoImage(img)
                    lbl = tk.Label(hdr, image=photo, bg=BG_PANEL)
                    lbl.image = photo
                    lbl.pack(side="left", padx=16, pady=5)
                    logo_loaded = True
                    break
                except Exception:
                    pass

    if not logo_loaded:
        tk.Label(hdr, text="SBG SYSTEMS",
                 fg="#38bdf8", bg=BG_PANEL,
                 font=("Segoe UI", 14, "bold")).pack(side="left", padx=16)

    tk.Label(hdr, text="Ellipse-A  |  IMU / AHRS DATA",
             fg="white", bg=BG_PANEL,
             font=("Segoe UI", 13, "bold")).pack(side="left", padx=8)

    # Connection dot + last-updated (right side of header)
    conn_dot = tk.Label(hdr, text="●",
                        fg=ACCENT if sbg.is_connected else "#ef4444",
                        bg=BG_PANEL, font=("Segoe UI", 12))
    conn_dot.pack(side="right", padx=(0, 12))

    last_update_lbl = tk.Label(hdr,
                                text="Connected" if sbg.is_connected else "No data",
                                fg="gray", bg=BG_PANEL, font=("Segoe UI", 8))
    last_update_lbl.pack(side="right", padx=(0, 4))

    # ---- USB Connection bar (below header) ----
    conn_bar = tk.Frame(panel, bg=BG_CARD)
    conn_bar.pack(fill="x", padx=12, pady=(8, 0))

    tk.Label(conn_bar, text="USB PORT", fg="#6b7280", bg=BG_CARD,
             font=("Segoe UI", 8, "bold")).pack(side="left", padx=(12, 6), pady=8)

    port_var = tk.StringVar()
    port_menu = ttk.Combobox(conn_bar, textvariable=port_var,
                              width=12, state="readonly")
    port_menu.pack(side="left", padx=(0, 6), pady=8)

    def _refresh_ports():
        ports = SbgReader.list_ports()
        port_menu["values"] = ports
        if sbg.is_connected:
            pass   # don't overwrite current port while connected
        else:
            # Prefer the last port that successfully connected, from
            # Settings → Serial port defaults.
            saved_port = settings_store.get("serial", "sbg_port", default="")
            if saved_port and saved_port in ports:
                port_var.set(saved_port)
            elif ports:
                port_var.set(ports[0])
            else:
                port_var.set("")

    _refresh_ports()

    tk.Button(conn_bar, text="↻", bg=BG_PANEL, fg="white", relief="flat",
              font=("Segoe UI", 9),
              command=_refresh_ports).pack(side="left", padx=(0, 10), pady=8)

    def _do_connect():
        port = port_var.get()
        if not port:
            return
        ok = sbg.connect(port)
        if ok:
            settings_store.set_value(("serial", "sbg_port"), port)
            settings_store.save()
        _refresh_status()

    def _do_disconnect():
        sbg.disconnect()
        _refresh_status()

    connect_btn = tk.Button(conn_bar, text="Connect",
                             bg="#16a34a", fg="white", relief="flat",
                             font=("Segoe UI", 9, "bold"), width=9,
                             state="disabled" if sbg.is_connected else "normal",
                             command=_do_connect)
    connect_btn.pack(side="left", padx=(0, 6), pady=8)

    disconnect_btn = tk.Button(conn_bar, text="Disconnect",
                                bg="#dc2626", fg="white", relief="flat",
                                font=("Segoe UI", 9, "bold"), width=10,
                                state="normal" if sbg.is_connected else "disabled",
                                command=_do_disconnect)
    disconnect_btn.pack(side="left", pady=8)

    # Baud rate label (informational)
    tk.Label(conn_bar, text="115200 baud  |  8N1",
             fg="#374151", bg=BG_CARD,
             font=("Segoe UI", 8)).pack(side="right", padx=12)

    def _refresh_status():
        if not panel.winfo_exists():
            return
        connected = sbg.is_connected
        conn_dot.config(fg=ACCENT if connected else "#ef4444")
        last_update_lbl.config(
            text=f"Updated {time.strftime('%H:%M:%S')}" if connected else "No data")
        connect_btn.config(state="disabled" if connected else "normal")
        disconnect_btn.config(state="normal" if connected else "disabled")

    # Poll connection status every 500 ms
    def _poll():
        if panel.winfo_exists():
            _refresh_status()
            panel.after(500, _poll)
    _poll()

    # ---- Main body: left = data fields, right = attitude indicator ----
    body = tk.Frame(panel, bg=BG_MAIN)
    body.pack(fill="both", expand=True, padx=12, pady=10)
    body.columnconfigure(0, weight=3)
    body.columnconfigure(1, weight=2)
    body.rowconfigure(0, weight=1)

    # ==========================
    # LEFT COLUMN — data fields
    # ==========================
    left = tk.Frame(body, bg=BG_MAIN)
    left.grid(row=0, column=0, sticky="nsew", padx=(0, 8))

    # Scrollable in case of small window
    left_canvas = tk.Canvas(left, bg=BG_MAIN, highlightthickness=0)
    left_scroll = tk.Scrollbar(left, orient="vertical", command=left_canvas.yview)
    left_canvas.configure(yscrollcommand=left_scroll.set)
    left_canvas.pack(side="left", fill="both", expand=True)
    left_scroll.pack(side="right", fill="y")

    data_frame = tk.Frame(left_canvas, bg=BG_MAIN)
    data_frame.bind("<Configure>",
                    lambda e: left_canvas.configure(
                        scrollregion=left_canvas.bbox("all")))
    _dwin = left_canvas.create_window((0, 0), window=data_frame, anchor="nw")
    left_canvas.bind("<Configure>",
                     lambda e: left_canvas.itemconfig(_dwin, width=e.width))

    # Group fields by category
    GROUPS = [
        ("🧭  ATTITUDE",        ["roll", "pitch", "yaw"]),
        ("🔄  ANGULAR RATE",    ["gyro_x", "gyro_y", "gyro_z"]),
        ("⚡  ACCELERATION",    ["accel_x", "accel_y", "accel_z"]),
    ]

    field_lookup = {f[0]: f for f in SBG_FIELDS}

    for group_title, keys in GROUPS:
        # Section header
        sec = tk.Frame(data_frame, bg=BG_CARD)
        sec.pack(fill="x", pady=(8, 0))

        tk.Label(sec, text=group_title,
                 fg="cyan", bg=BG_CARD,
                 font=("Segoe UI", 10, "bold")).pack(anchor="w", padx=12, pady=(8, 4))

        # Field rows — 3 per row using grid
        grid_frame = tk.Frame(sec, bg=BG_CARD)
        grid_frame.pack(fill="x", padx=8, pady=(0, 10))
        COLS = 3
        for col in range(COLS):
            grid_frame.columnconfigure(col, weight=1)

        for i, key in enumerate(keys):
            if key not in field_lookup:
                continue
            _, label, unit, color = field_lookup[key]
            row, col = divmod(i, COLS)

            tile = tk.Frame(grid_frame, bg=BG_MAIN, padx=8, pady=6)
            tile.grid(row=row, column=col, padx=4, pady=3, sticky="ew")

            tk.Label(tile, text=label, fg="#6b7280", bg=BG_MAIN,
                     font=("Segoe UI", 7)).pack(anchor="w")

            val_lbl = tk.Label(tile,
                               text=f"-- {unit}".strip() if unit else "--",
                               fg=color, bg=BG_MAIN,
                               font=("Segoe UI", 12, "bold"),
                               width=12, anchor="w")
            val_lbl.pack(anchor="w")

            tk.Frame(tile, bg=ACCENT, height=2).pack(fill="x", pady=(3, 0))

            _field_labels[key] = val_lbl

    # ---- SBG specs card below data fields ----
    info_card = tk.Frame(data_frame, bg=BG_CARD)
    info_card.pack(fill="x", pady=(8, 0))

    tk.Label(info_card, text="SBG ELLIPSE-A  SPECS",
             fg="cyan", bg=BG_CARD,
             font=("Segoe UI", 9, "bold")).pack(anchor="w", padx=12, pady=(8, 4))

    specs = [
        ("Roll / Pitch Accuracy", "0.05°  RMS"),
        ("Heading Accuracy",      "0.2°  RMS"),
        ("Gyro Bias",             "0.3°/hr"),
        ("Accel Bias",            "0.05 mg"),
        ("Output Rate",           "up to 200 Hz"),
        ("Interface",             "RS-232 / CAN"),
    ]

    for label, value in specs:
        row = tk.Frame(info_card, bg=BG_CARD)
        row.pack(fill="x", padx=12, pady=1)
        tk.Label(row, text=label, fg="#6b7280", bg=BG_CARD,
                 font=("Segoe UI", 8), width=20, anchor="w").pack(side="left")
        tk.Label(row, text=value, fg=TEXT, bg=BG_CARD,
                 font=("Segoe UI", 8, "bold")).pack(side="left")

    tk.Frame(info_card, bg=BG_CARD, height=8).pack()

    # ==========================
    # RIGHT COLUMN — directional indicator
    # ==========================
    right = tk.Frame(body, bg=BG_MAIN)
    right.grid(row=0, column=1, sticky="nsew")
    right.rowconfigure(0, weight=1)
    right.columnconfigure(0, weight=1)

    tk.Label(right, text="ATTITUDE INDICATOR",
             fg="cyan", bg=BG_MAIN,
             font=("Segoe UI", 10, "bold")).pack(side="top", pady=(4, 6))

    gyro_card = tk.Frame(right, bg=BG_CARD)
    gyro_card.pack(side="top", fill="both", expand=True, pady=(0, 8))

    gyro_cv = tk.Canvas(gyro_card, bg="#0a0f1e", highlightthickness=0)
    gyro_cv.pack(fill="both", expand=True, padx=8, pady=8)

    _gyro_canvas = gyro_cv

    def _on_gyro_resize(e):
        _draw_attitude(gyro_cv)

    gyro_cv.bind("<Configure>", _on_gyro_resize)

    # ---- Last updated ticker ----
    def _update_last(connected=False):
        if panel.winfo_exists():
            if connected:
                last_update_lbl.config(
                    text=f"Updated  {time.strftime('%H:%M:%S')}")
            panel.after(1000, lambda: _update_last(connected))

    _update_last(False)

    # Expose connection update so main GUI can call it
    def set_connected(state: bool):
        conn_dot.config(fg=ACCENT if state else "#ef4444")
        _update_last(state)

    panel._set_sbg_connected = set_connected

    # Clean up canvas ref on close
    def _on_close():
        global _gyro_canvas
        _gyro_canvas = None
        panel.destroy()

    panel.protocol("WM_DELETE_WINDOW", _on_close)