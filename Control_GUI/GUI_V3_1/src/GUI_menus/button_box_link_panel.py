import tkinter as tk
from tkinter import ttk
import GTW_Control_Comms.gtw_mqtt_commands as command
import GUI_menus.settings_store as settings_store
from IO_devices.Button_Box_Rx import ButtonBox

# Theme (match main GUI)
BG_MAIN  = "#0f172a"
BG_CARD  = "#1f2937"
BG_PANEL = "#111827"
ACCENT   = "#22c55e"

# ==================================================
# MODULE-LEVEL INSTANCE
# One ButtonBox shared across the whole application.
# It uses the same msg_queue as MQTT so button events
# appear in the main GUI log automatically.
# ==================================================
button_box: ButtonBox | None = None

def get_button_box() -> ButtonBox:
    """Return (creating if needed) the shared ButtonBox instance."""
    global button_box
    if button_box is None:
        button_box = ButtonBox(command.msg_queue)
    return button_box


# ==================================================
# PANEL WINDOW
# ==================================================
def open_button_panel(root):
    panel = tk.Toplevel(root)
    panel.title("Control Box Linker")
    panel.geometry("500x500")
    panel.configure(bg=BG_MAIN)
    panel.resizable(False, False)

    tk.Label(panel, text="PHYSICAL BUTTON BOX",
             fg="white", bg=BG_MAIN,
             font=("Segoe UI", 16, "bold")).pack(pady=(16, 4))

    tk.Label(panel, text="Configure and connect the Arduino button box via serial port.",
             fg="gray", bg=BG_MAIN,
             font=("Segoe UI", 9)).pack(pady=(0, 12))

    box = get_button_box()

    # =========================
    # CONNECTION CARD
    # =========================
    card = tk.Frame(panel, bg=BG_CARD)
    card.pack(fill="x", padx=20, pady=6)

    tk.Label(card, text="CONNECTION",
             fg="cyan", bg=BG_CARD,
             font=("Segoe UI", 10, "bold")).pack(anchor="w", padx=12, pady=(10, 4))

    row = tk.Frame(card, bg=BG_CARD)
    row.pack(fill="x", padx=12, pady=(0, 12))

    # --- COM port dropdown ---
    tk.Label(row, text="COM Port:", fg="white", bg=BG_CARD,
             font=("Segoe UI", 10)).grid(row=0, column=0, padx=(0, 8), sticky="w")

    port_var = tk.StringVar()
    port_menu = ttk.Combobox(row, textvariable=port_var, width=10, state="readonly")
    port_menu.grid(row=0, column=1, padx=(0, 8))

    def refresh_ports():
        ports = ButtonBox.list_ports()
        port_menu["values"] = ports
        # Prefer the last port that successfully connected, from Settings →
        # Serial port defaults, so operators don't have to reselect it
        # every time they open this panel.
        saved_port = settings_store.get("serial", "button_box_port", default="")
        if saved_port and saved_port in ports:
            port_var.set(saved_port)
        elif ports:
            port_var.set(ports[0])
        else:
            port_var.set("")

    refresh_ports()

    tk.Button(row, text="↻ Refresh",
              bg=BG_PANEL, fg="white", relief="flat",
              font=("Segoe UI", 9),
              command=refresh_ports
    ).grid(row=0, column=2, padx=(0, 12))

    # --- Connect / Disconnect buttons ---
    def do_connect():
        port = port_var.get()
        if not port:
            status_var.set("⚠  No port selected")
            return
        ok = box.connect(port)
        if ok:
            # Remember this port for next time
            settings_store.set_value(("serial", "button_box_port"), port)
            settings_store.save()
        _refresh_status()

    def do_disconnect():
        box.disconnect()
        _refresh_status()

    tk.Button(row, text="Connect",
              bg="#16a34a", fg="white", relief="flat",
              font=("Segoe UI", 10, "bold"), width=9,
              command=do_connect
    ).grid(row=0, column=3, padx=(0, 6))

    tk.Button(row, text="Disconnect",
              bg="#dc2626", fg="white", relief="flat",
              font=("Segoe UI", 10, "bold"), width=10,
              command=do_disconnect
    ).grid(row=0, column=4)

    # =========================
    # STATUS CARD
    # =========================
    status_card = tk.Frame(panel, bg=BG_CARD)
    status_card.pack(fill="x", padx=20, pady=6)

    tk.Label(status_card, text="STATUS",
             fg="cyan", bg=BG_CARD,
             font=("Segoe UI", 10, "bold")).pack(anchor="w", padx=12, pady=(10, 4))

    status_row = tk.Frame(status_card, bg=BG_CARD)
    status_row.pack(fill="x", padx=12, pady=(0, 12))

    dot_label  = tk.Label(status_row, text="●", font=("Segoe UI", 14), bg=BG_CARD)
    dot_label.grid(row=0, column=0, padx=(0, 8))

    status_var = tk.StringVar(value="Disconnected")
    tk.Label(status_row, textvariable=status_var,
             fg="white", bg=BG_CARD,
             font=("Segoe UI", 10)).grid(row=0, column=1, sticky="w")

    def _refresh_status():
        if box.is_connected:
            dot_label.config(fg=ACCENT)
            port = port_var.get()
            status_var.set(f"Connected  —  {port}  @  115200 baud")
        else:
            dot_label.config(fg="#dc2626")
            status_var.set("Disconnected")

    _refresh_status()

    # Poll every 500 ms so status dot updates if connection drops unexpectedly
    def _poll():
        if panel.winfo_exists():
            _refresh_status()
            panel.after(500, _poll)

    _poll()

    # =========================
    # BUTTON MAP INFO CARD
    # =========================
    info_card = tk.Frame(panel, bg=BG_CARD)
    info_card.pack(fill="x", padx=20, pady=6)

    tk.Label(info_card, text="BUTTON MAP",
             fg="cyan", bg=BG_CARD,
             font=("Segoe UI", 10, "bold")).pack(anchor="w", padx=12, pady=(10, 4))

    info_text = (
        "Buttons 0–2  →  Toggles  (ON / OFF)\n"
        "Buttons 3–24 →  Momentary press\n\n"
        "Wire button actions in  Button_Box_Rx.py:\n"
        "  _dispatch_press(button_id)\n"
        "  _dispatch_toggle(button_id, state)"
    )

    tk.Label(info_card, text=info_text,
             fg="#9ca3af", bg=BG_CARD,
             font=("Segoe UI", 9), justify="left"
    ).pack(anchor="w", padx=12, pady=(0, 12))