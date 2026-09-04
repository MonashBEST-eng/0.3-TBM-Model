import os
import sys

def resource_path(relative_path):
    try:
        base_path = sys._MEIPASS  # PyInstaller temp folder
    except AttributeError:
        base_path = os.path.abspath(".")
    return os.path.join(base_path, relative_path)



## IMPORT REQUIRED GUI PACKAGES
import tkinter as tk
from PIL import Image, ImageTk
import time
from collections import deque





#######################################
#### FUNCTION FILE INSTANTIATIONS #####
#######################################

## import commands module
import GTW_Control_Comms.gtw_mqtt_commands as gtw_mqtt_commands
import GUI_menus.settings_store as settings_store

# Apply any persisted broker settings BEFORE the first connection attempt
gtw_mqtt_commands.set_broker(
    settings_store.get("network", "broker", default="192.168.1.10"),
    settings_store.get("network", "port", default=1883),
)
gtw_mqtt_commands.start_mqtt()

# import control pannel - digital button box in GUI - this links the GUI control panel menu option to its actual menu 
from GUI_menus.control_panel import open_control_panel, get_odrive_controller, update_odrive_display
from GUI_menus.button_box_link_panel import open_button_panel, get_button_box
from GUI_menus.monitoring_panel import open_monitoring_panel, update_sensor, apply_thresholds
from GUI_menus.sbg_panel import open_sbg_panel, update_sbg
from GUI_menus.dashboard_panel import (
    open_dashboard_panel, log_comms, log_status,
    log, add_alarm, update_graph, _decode_mqtt_command, set_max_log_lines,
    create_estop_widget,
)
from GUI_menus.splash_panel import build_splash
import GUI_menus.alarms_panel as alarms_panel
import GUI_menus.heartbeat_panel as heartbeat_panel
from GUI_menus.settings_panel import open_settings_panel
from GUI_menus.system_log_panel import open_system_log_panel
from IO_devices.sbg_reader import SbgReader

# Apply any persisted sensor threshold overrides on top of the defaults
# baked into monitoring_panel.SENSORS
apply_thresholds(settings_store.get("thresholds", default={}))
set_max_log_lines(settings_store.get("alarms", "log_max_lines", default=500))

# import button box module - physical button box
# incorporated into gui to allow setting of com port, and ensuring it is active :)
button_box = get_button_box()   # shared instance — uses the same msg_queue as MQTT
sbg_reader = SbgReader(gtw_mqtt_commands.msg_queue)  # SBG USB reader — connect via SBG IMU panel

# ODrive motor control — runs over the H7 Ethernet<->CAN relay (same
# tbm/can_tx / stm32/can_rx topics as everything else), not a local PCAN
# adapter. Starting the loop here (rather than only when the Control Panel
# is opened) means heartbeats/telemetry get processed even before the
# panel window is first opened. Sending START/STOP still requires opening
# the Control Panel's ODRIVE MOTOR card.
odrive_controller = get_odrive_controller()
odrive_controller.start_loop()


# =========================
# THEME COLORS
# =========================
BG_MAIN = "#0f172a"
BG_PANEL = "#111827"
BG_CARD = "#1f2937"
ACCENT = "#22c55e"
TEXT = "#e5e7eb"

# =========================
# ROOT WINDOW
# =========================
root = tk.Tk()
root.title("Monash BEST TBM Control Interface👷")
root.geometry("1920x1080")
root.configure(bg=BG_MAIN)


# =========================
# HEADER
# =========================
header = tk.Frame(root, bg=BG_PANEL, height=70)
header.pack(fill="x")

# --- TITLE (no logo in header) ---
tk.Label(header, text="TBM CONTROL SYSTEM",
         fg="white", bg=BG_PANEL,
         font=("Segoe UI", 20, "bold")).pack(side="left", padx=20)

# --- CLOCK ---
time_label = tk.Label(header, fg="white", bg=BG_PANEL, font=("Segoe UI", 12))
time_label.pack(side="right", padx=20)

def update_time():
    now = time.strftime("%H:%M:%S\n%d/%m/%Y")
    time_label.config(text=now)
    root.after(1000, update_time)

update_time()


# =========================
# SAFE SHUTDOWN PROTECTION
# =========================
from tkinter import simpledialog

def safe_close():
    # Ask confirmation first
    confirm = tk.messagebox.askyesno("Confirm Shutdown",
                                     "Do you want to shut down the SCADA system?")
    if not confirm:
        return

    # Ask password — read fresh each time so a change in Settings takes
    # effect immediately, without needing a restart
    pwd = simpledialog.askstring("Authentication",
                                 "Enter shutdown password:",
                                 show="*")

    if pwd == settings_store.get("safety", "shutdown_password", default="0000"):

        # WHEN SHUTDOWN PASSWORD ENTERED ON ACCIDENTAL EXIT WHILE SYSTEM ACTIVE
        # EXECUTE ALL COMMANDS TO SHUT TBM DOWN SAFELY
        root.destroy()
    else:
        tk.messagebox.showerror("Access Denied", "Incorrect password")

root.protocol("WM_DELETE_WINDOW", safe_close)
root.bind("<Alt-F4>", lambda e: safe_close())





# =========================
# MAIN LAYOUT
# =========================
main = tk.Frame(root, bg=BG_MAIN)
main.pack(fill="both", expand=True)

# =========================
# SIDEBAR
# =========================
sidebar = tk.Frame(main, bg=BG_PANEL, width=220)
sidebar.pack(side="left", fill="y")
sidebar.pack_propagate(False)

def nav_button(text):
    return tk.Button(sidebar, text=text,
                     bg=BG_PANEL, fg="white",
                     relief="flat", anchor="w",
                     padx=20, pady=12)

# DASHBOARD MENU OPEN BUTTON — opens the live sensor/camera/log panel
dash_btn = nav_button("Dashboard")
dash_btn.pack(fill="x")
dash_btn.config(command=lambda: open_dashboard_panel(root))

# MONITORING MENU OPEN BUTTON
monitoring_btn = nav_button("Monitoring")
monitoring_btn.pack(fill="x")
monitoring_btn.config(command=lambda: open_monitoring_panel(root))

# ALARMS MENU OPEN BUTTON — badge text/color updated by _refresh_alarms_badge()
alarms_btn = nav_button("Alarms")
alarms_btn.pack(fill="x")
alarms_btn.config(command=lambda: alarms_panel.open_alarms_panel(root))

syslog_btn = nav_button("System Log")
syslog_btn.pack(fill="x")
syslog_btn.config(command=lambda: open_system_log_panel(root))

settings_btn = nav_button("Settings")
settings_btn.pack(fill="x")
settings_btn.config(command=lambda: open_settings_panel(root))

# CONTROL PANEL MENU OPEN BUTTON
ctrl_btn = nav_button("Control Panel")
ctrl_btn.pack(fill="x")
ctrl_btn.config(command=lambda: open_control_panel(root))

# BUTTON BOX MENU OPEN BUTTON
btn_box_btn = nav_button("Button Box")
btn_box_btn.pack(fill="x")
btn_box_btn.config(command=lambda: open_button_panel(root))

# SBG IMU MENU OPEN BUTTON
sbg_btn = nav_button("SBG IMU")
sbg_btn.pack(fill="x")
sbg_btn.config(command=lambda: open_sbg_panel(root))

# =========================
# SIDEBAR STATUS INDICATORS
# =========================
tk.Frame(sidebar, bg="#1e2a3a", height=1).pack(fill="x", pady=8)

def _indicator(text):
    row = tk.Frame(sidebar, bg=BG_PANEL)
    row.pack(fill="x", padx=14, pady=3)
    dot = tk.Label(row, text="●", fg="#ef4444", bg=BG_PANEL,
                   font=("Segoe UI", 9))
    dot.pack(side="left")
    tk.Label(row, text=f"  {text}", fg="#6b7280", bg=BG_PANEL,
             font=("Segoe UI", 8)).pack(side="left")
    return dot

ind_mqtt   = _indicator("MQTT")
ind_tbm    = _indicator("TBM Ready")

# =========================
# ALARMS BADGE
# Shows the unacknowledged alarm count right on the sidebar nav button, so
# operators don't have to open the Alarms panel to know something's up.
# =========================
def _refresh_alarms_badge():
    count = alarms_panel.get_unacknowledged_count()
    if count > 0:
        alarms_btn.config(text=f"Alarms ({count})", fg="#ef4444")
    else:
        alarms_btn.config(text="Alarms", fg="white")

alarms_panel.register_change_callback(_refresh_alarms_badge)
_refresh_alarms_badge()

# =========================
# SIDEBAR SUMMARY CARDS
# =========================
tk.Frame(sidebar, bg="#1e2a3a", height=1).pack(fill="x", pady=8)

def create_card(parent, title, value, color):
    card = tk.Frame(parent, bg=BG_CARD)
    card.pack(fill="x", padx=10, pady=4)
    tk.Label(card, text=title, fg="gray", bg=BG_CARD,
             font=("Segoe UI", 7)).pack(anchor="w", padx=8, pady=(5, 0))
    val = tk.Label(card, text=value, fg=color, bg=BG_CARD,
                   font=("Segoe UI", 13, "bold"))
    val.pack(anchor="w", padx=8, pady=(0, 5))
    return val

status_val = create_card(sidebar, "STATUS", "DISCONNECTED", "#ef4444")

# Stub labels kept so update_ui doesn't crash — the summary cards they used
# to feed (TEMP/PRESS/FLOW) now live in the Dashboard panel's sensor grid.
class _Stub:
    def config(self, **_): pass
temp_val  = _Stub()
press_val = _Stub()
flow_val  = _Stub()

def _update_status(connected: bool):
    if connected:
        status_val.config(text="NORMAL", fg="lime")
    else:
        status_val.config(text="DISCONNECTED", fg="#ef4444")

# =========================
# E-STOP AT BOTTOM OF SIDEBAR
# Quick access from anywhere in the app — shares the exact same
# armed/tripped state as the Dashboard's big E-STOP button. Press either
# one and both update together.
# =========================
tk.Frame(sidebar, bg=BG_PANEL).pack(fill="both", expand=True)

estop_widget = create_estop_widget(sidebar, size=130, bg=BG_PANEL)
estop_widget.pack(side="bottom", pady=15)

# =========================
# CONTENT AREA — sponsor splash screen
# The live dashboard (sensors / cameras / logs) has moved to its own panel,
# opened via the "Dashboard" sidebar button above. This area now just shows
# the splash / sponsors screen, with the sidebar staying visible around it.
# =========================
content = tk.Frame(main, bg=BG_MAIN)
content.pack(side="left", fill="both", expand=True)

build_splash(content)

# =========================
# SERIAL / MESSAGE HANDLER
# =========================
def update_ui():
    while not gtw_mqtt_commands.msg_queue.empty():
        msg_type, data = gtw_mqtt_commands.msg_queue.get()

        # ---- MQTT connection events → comms log + MQTT indicator only ----
        if msg_type == "conn":
            connected = "Connected" in data
            ind_mqtt.config(fg="#22c55e" if connected else "#ef4444")
            _update_status(connected)
            log_comms(f"[MQTT] {data}", tag="conn")
            # not logged to control log — MQTT only goes to comms log

            if not connected:
                # Lost the connection - no longer a confirmed round trip,
                # so TBM Ready goes back to red until the next successful
                # handshake ACK (sent automatically once reconnected).
                ind_tbm.config(fg="#ef4444")

            if connected:
                alarms_panel.clear_alarm("MQTT_CONN")
            else:
                alarms_panel.raise_alarm("MQTT_CONN", "warning", "MQTT",
                                         f"MQTT connection lost: {data}")

        # ---- Incoming MQTT data → comms log + all sensor displays ----
        elif msg_type == "mqtt_rx":
            log_comms(f"[RX] {data}", tag="rx")

            # data format is "topic | payload" - split once up front so we
            # can react to specific topics (like the handshake ACK) before
            # falling through to the generic telemetry parser below.
            topic_part = data.split("|", 1)[0].strip()

            if topic_part == "stm32/handshake_ack":
                # Confirms the STM actually received our handshake request
                # and replied - this is the real "TBM is alive and talking
                # back" signal, rather than just "some MQTT message arrived".
                ind_tbm.config(fg="#22c55e")

            elif topic_part == "stm32/heartbeat_ack":
                # Ongoing 5s deadman's-switch ACK - separate from the
                # one-shot handshake above. Feeds the heartbeat watchdog's
                # timeout tracking; does NOT by itself clear a tripped
                # fault (that requires pressing RESUME).
                heartbeat_panel.on_heartbeat_ack()

            elif topic_part == "stm32/can_rx":
                # A CAN frame the STM received off the bus, relayed here
                # over Ethernet. The GUI, not the STM, decides what any
                # given CAN ID/data actually means - this is the place to
                # add specific handling as your CAN ID scheme grows (e.g.
                # "if frame['id'] == 0x0A0: <cutterhead board reporting
                # status>"). For now it's logged so nothing arriving off
                # the bus goes unnoticed even before specific handling
                # exists for a given ID.
                can_payload = data.split("|", 1)[1].strip() if "|" in data else ""
                frame = gtw_mqtt_commands.decode_can_rx_payload(can_payload)
                if frame is not None:
                    # ODrive frames are handled (and logged more selectively,
                    # via the odrive_heartbeat/odrive_encoder cases below)
                    # by the ODrive controller itself. Only fall through to
                    # the generic raw-frame log for anything it doesn't
                    # recognise as its own — otherwise ODrive's ~1-10 Hz
                    # heartbeat/encoder traffic would flood the control log.
                    if not odrive_controller.process_can_frame(frame):
                        hex_data = " ".join(f"{b:02X}" for b in frame["data"])
                        log_status(
                            f"[CAN RX] ID=0x{frame['id']:X} DLC={frame['dlc']} Data: {hex_data}",
                            tag="info",
                        )
                    # ---- Extend here as specific CAN IDs get meaning ----
                    # if frame["id"] == 0x0A0:
                    #     ...interpret cutterhead board status, raise/clear
                    #     an alarm, update a UI indicator, etc.

            # Parse telemetry — format:  topic | KEY:val,KEY:val,...
            try:
                payload = data.split("|")[1].strip()

                for p in payload.split(","):
                    key, val = p.split(":")
                    val = float(val)

                    # ---- Dashboard summary cards ----
                    if key == "TEMP":
                        temp_val.config(text=f"{val} °C")
                        update_graph(val)
                        update_sensor("TEMP_CUTTERHEAD", val)

                    elif key == "PRESS":
                        press_val.config(text=f"{val} bar")
                        update_sensor("PRESS_HYDRAULIC", val)

                    elif key == "FLOW":
                        flow_val.config(text=f"{val} L/min")
                        update_sensor("FLOW_HYDRAULIC", val)

                    # ---- All other sensors — monitoring panel ----
                    else:
                        update_sensor(key, val)

            except:
                pass

        # ---- Outgoing MQTT commands → comms log + control log ----
        elif msg_type == "mqtt_tx":
            log_comms(f"[TX] {data}", tag="tx")
            # Also log human-readable command to Control Log
            readable_cmd = _decode_mqtt_command(data)
            if readable_cmd:
                log_status(f"[CMD] {readable_cmd}", tag="btn")

                # Safety-relevant commands also raise/clear alarms — this
                # catches EMERGENCY STOP / SAFE MODE / CLEAR from *any*
                # source (dashboard mushroom button, Control Panel, etc.)
                # since they all funnel through the same MQTT command path.
                if "EMERGENCY STOP" in readable_cmd:
                    alarms_panel.raise_alarm("ESTOP", "critical", "Safety",
                                             "Emergency stop activated")
                elif "Clear Emergency" in readable_cmd:
                    alarms_panel.clear_alarm("ESTOP")
                    alarms_panel.clear_alarm("SAFE_MODE")
                elif "Safe Mode" in readable_cmd:
                    alarms_panel.raise_alarm("SAFE_MODE", "warning", "Safety",
                                             "System placed in safe mode")

        # ---- ODrive status/log messages → control log ----
        elif msg_type == "odrive_status":
            log_status(data, tag="info")

        # ---- ODrive heartbeat (axis state / error) → control log +
        #      Control Panel telemetry + alarm ----
        elif msg_type == "odrive_heartbeat":
            node_id, axis_error, axis_state = data
            update_odrive_display(node_id, axis_state=axis_state, axis_error=axis_error)

            alarm_key = f"ODRIVE_AXIS{node_id}"
            if axis_error:
                log_status(f"[ODrive] Axis {node_id} error 0x{axis_error:08X}", tag="alarm")
                alarms_panel.raise_alarm(alarm_key, "critical", "ODrive",
                                         f"Axis {node_id} error 0x{axis_error:08X}")
            else:
                alarms_panel.clear_alarm(alarm_key)

        # ---- ODrive encoder estimates → Control Panel telemetry +
        #      Monitoring panel sensor tiles (no comms/control log spam) ----
        elif msg_type == "odrive_encoder":
            node_id, position, velocity = data
            update_odrive_display(node_id, position=position, velocity=velocity)
            update_sensor(f"ODRIVE_AXIS{node_id}_POS", position)
            update_sensor(f"ODRIVE_AXIS{node_id}_VEL", velocity)

        # ---- SBG IMU data → sbg panel ----
        elif msg_type == "sbg_rx":
            # data is expected to be a dict: {"roll": x, "pitch": y, ...}
            update_sbg(data)
            # Don't spam comms log with continuous SBG data

        # ---- SBG connection status → comms log ----
        elif msg_type == "sbg_status":
            log_comms(f"{data}", tag="conn")

        # ---- Physical button box events → status log only (indicator dot
        #      removed from sidebar — button box connectivity alarm still
        #      raised/cleared below so it's not silently lost, just no
        #      longer shown as a dedicated sidebar dot) ----
        elif msg_type == "btn_status":
            connected = "Connected" in data
            log_status(f"[BTN BOX] {data}", tag="btn")

            if connected:
                alarms_panel.clear_alarm("BTNBOX_CONN")
            else:
                alarms_panel.raise_alarm("BTNBOX_CONN", "warning", "Button Box", data)

        elif msg_type == "btn_press":
            log_status(f"[BTN BOX] Button {data} pressed", tag="btn")

        elif msg_type == "btn_toggle":
            btn_id, state = data
            log_status(f"[BTN BOX] Toggle {btn_id} → {'ON' if state else 'OFF'}", tag="btn")

        # ---- Fallback → status log ----
        else:
            log_status(str(data), tag="info")

    root.after(100, update_ui)

update_ui()
alarms_panel.start_auto_resolve_timer(root)
heartbeat_panel.start_heartbeat_loop(root)

# =========================
# RUN
# =========================
root.mainloop()