# settings_panel.py
#
# Central Settings panel. Everything here reads from / writes to
# settings_store.SETTINGS, and a "Save All Settings" button persists it to
# disk and applies the changes that can take effect immediately (thresholds,
# log line cap). Network changes get their own explicit "Save & Reconnect"
# button since forcing a live MQTT reconnect is a more consequential action
# than the rest of the form.
#
# Note: Display → accent color / splash auto-rotate are saved to disk so
# they're not lost, but aren't wired up to actually repaint the UI yet —
# that would mean threading a theme value through every panel. Flagged
# here so it's not a silent gap.

import tkinter as tk
from tkinter import ttk, messagebox

import GUI_menus.settings_store as settings_store
import GUI_menus.monitoring_panel as monitoring_panel
import GUI_menus.dashboard_panel as dashboard_panel
import GUI_menus.splash_panel as splash_panel
import GTW_Control_Comms.gtw_mqtt_commands as command

# =========================
# THEME — match main GUI
# =========================
BG_MAIN  = "#0f172a"
BG_PANEL = "#111827"
BG_CARD  = "#1f2937"
ACCENT   = "#22c55e"
TEXT     = "#e5e7eb"

_panel_ref: tk.Toplevel | None = None


class _PlaceholderPasswordEntry:
    """A password Entry that shows greyed-out, unmasked hint text when
    empty (e.g. "Default: 0000") and switches to real masked input the
    moment the user clicks in and starts typing. get_value() returns ''
    while the hint is still showing, so it's easy to tell "untouched"
    apart from "user actually typed something"."""

    def __init__(self, parent, placeholder: str, width: int = 16):
        self.var = tk.StringVar()
        self.placeholder = placeholder
        self.is_placeholder = True
        self.entry = tk.Entry(parent, textvariable=self.var, width=width)
        self.entry.bind("<FocusIn>", self._on_focus_in)
        self.entry.bind("<FocusOut>", self._on_focus_out)
        self._show_placeholder()

    def _show_placeholder(self):
        self.is_placeholder = True
        self.var.set(self.placeholder)
        self.entry.config(show="", fg="#6b7280")

    def _on_focus_in(self, event=None):
        if self.is_placeholder:
            self.var.set("")
            self.entry.config(show="*", fg=TEXT)
            self.is_placeholder = False

    def _on_focus_out(self, event=None):
        if not self.var.get():
            self._show_placeholder()

    def get_value(self) -> str:
        """'' if the hint is still showing (untouched), else what was typed."""
        return "" if self.is_placeholder else self.var.get()

    def reset(self, new_placeholder: str = None):
        """Clear back to hint state — call after a successful save, with
        an updated hint reflecting the new current state."""
        if new_placeholder is not None:
            self.placeholder = new_placeholder
        self._show_placeholder()

    def pack(self, **kwargs):
        self.entry.pack(**kwargs)


def open_settings_panel(root):
    global _panel_ref

    if _panel_ref is not None and _panel_ref.winfo_exists():
        _panel_ref.lift()
        _panel_ref.focus_force()
        return

    panel = tk.Toplevel(root)
    _panel_ref = panel
    panel.title("Settings")
    panel.geometry("900x900")
    panel.configure(bg=BG_MAIN)

    # ---- Header ----
    hdr = tk.Frame(panel, bg=BG_PANEL)
    hdr.pack(fill="x")
    tk.Label(hdr, text="SETTINGS", fg="white", bg=BG_PANEL,
             font=("Segoe UI", 16, "bold")).pack(side="left", padx=16, pady=12)

    saved_lbl = tk.Label(hdr, text="", fg="#22c55e", bg=BG_PANEL,
                         font=("Segoe UI", 9, "bold"))
    saved_lbl.pack(side="right", padx=16)

    # ---- Scrollable body ----
    canvas = tk.Canvas(panel, bg=BG_MAIN, highlightthickness=0)
    scrollbar = tk.Scrollbar(panel, orient="vertical", command=canvas.yview)
    canvas.configure(yscrollcommand=scrollbar.set)
    canvas.pack(side="left", fill="both", expand=True)
    scrollbar.pack(side="right", fill="y")

    body = tk.Frame(canvas, bg=BG_MAIN)
    body.bind("<Configure>", lambda e: canvas.configure(scrollregion=canvas.bbox("all")))
    _bwin = canvas.create_window((0, 0), window=body, anchor="nw")
    canvas.bind("<Configure>", lambda e: canvas.itemconfig(_bwin, width=e.width))

    def _on_mousewheel(event):
        canvas.yview_scroll(int(-1 * (event.delta / 120)), "units")
    canvas.bind_all("<MouseWheel>", _on_mousewheel)

    def _on_close():
        global _panel_ref
        canvas.unbind_all("<MouseWheel>")
        _panel_ref = None
        panel.destroy()
    panel.protocol("WM_DELETE_WINDOW", _on_close)

    def create_section(title, subtitle=None):
        frame = tk.Frame(body, bg=BG_CARD)
        frame.pack(fill="x", padx=15, pady=8)
        tk.Label(frame, text=title, fg="cyan", bg=BG_CARD,
                 font=("Segoe UI", 11, "bold")).pack(anchor="w", padx=12, pady=(10, 2))
        if subtitle:
            tk.Label(frame, text=subtitle, fg="#6b7280", bg=BG_CARD,
                     font=("Segoe UI", 8), wraplength=800, justify="left"
            ).pack(anchor="w", padx=12, pady=(0, 6))
        inner = tk.Frame(frame, bg=BG_CARD)
        inner.pack(fill="x", padx=12, pady=(0, 12))
        return inner

    # =========================================================
    # SECTION 1 — SENSOR THRESHOLDS
    # =========================================================
    sec = create_section(
        "SENSOR THRESHOLDS",
        "Warning/critical values also drive the alarm system — crossing one raises "
        "an alarm, dropping back into range auto-resolves it."
    )

    hdr_row = tk.Frame(sec, bg=BG_CARD)
    hdr_row.pack(fill="x", pady=(0, 4))
    tk.Label(hdr_row, text="Sensor", fg="#6b7280", bg=BG_CARD, font=("Segoe UI", 8, "bold"),
             width=24, anchor="w").pack(side="left")
    tk.Label(hdr_row, text="Warning", fg="#6b7280", bg=BG_CARD, font=("Segoe UI", 8, "bold"),
             width=10, anchor="w").pack(side="left")
    tk.Label(hdr_row, text="Critical", fg="#6b7280", bg=BG_CARD, font=("Segoe UI", 8, "bold"),
             width=10, anchor="w").pack(side="left")

    threshold_vars = {}
    for key, spec in monitoring_panel.SENSORS.items():
        label_text, unit, color, warn, crit = spec
        row = tk.Frame(sec, bg=BG_CARD)
        row.pack(fill="x", pady=1)
        tk.Label(row, text=f"{label_text} ({unit})", fg=TEXT, bg=BG_CARD,
                 font=("Segoe UI", 9), width=24, anchor="w").pack(side="left")

        warn_var = tk.StringVar(value=str(warn))
        tk.Entry(row, textvariable=warn_var, width=10).pack(side="left", padx=(0, 6))

        crit_var = tk.StringVar(value=str(crit))
        tk.Entry(row, textvariable=crit_var, width=10).pack(side="left")

        threshold_vars[key] = (warn_var, crit_var)

    # =========================================================
    # SECTION 2 — NETWORK / MQTT
    # =========================================================
    sec = create_section(
        "NETWORK / MQTT BROKER",
        "Changing these here doesn't reconnect automatically — use Save & Reconnect "
        "below once you're ready, since it will briefly drop the live connection."
    )

    net_row = tk.Frame(sec, bg=BG_CARD)
    net_row.pack(fill="x", pady=4)
    tk.Label(net_row, text="Broker IP", fg="#9ca3af", bg=BG_CARD,
             font=("Segoe UI", 9), width=14, anchor="w").pack(side="left")
    broker_var = tk.StringVar(value=str(settings_store.get("network", "broker", default="")))
    tk.Entry(net_row, textvariable=broker_var, width=20).pack(side="left", padx=(0, 16))

    tk.Label(net_row, text="Port", fg="#9ca3af", bg=BG_CARD,
             font=("Segoe UI", 9)).pack(side="left")
    port_var = tk.StringVar(value=str(settings_store.get("network", "port", default=1883)))
    tk.Entry(net_row, textvariable=port_var, width=8).pack(side="left", padx=(6, 0))

    def _save_reconnect():
        try:
            port_val = int(port_var.get())
        except ValueError:
            messagebox.showerror("Invalid Port", "Port must be a whole number.")
            return
        broker_val = broker_var.get().strip()
        settings_store.set_value(("network", "broker"), broker_val)
        settings_store.set_value(("network", "port"), port_val)
        settings_store.save()
        command.set_broker(broker_val, port_val)
        command.reconnect()
        dashboard_panel.log_status(f"[SETTINGS] Broker changed to {broker_val}:{port_val} — reconnecting", tag="info")
        saved_lbl.config(text="✓ Reconnecting...")
        panel.after(2000, lambda: saved_lbl.config(text=""))

    tk.Button(sec, text="Save & Reconnect Now", bg="#374151", fg="white", relief="flat",
             font=("Segoe UI", 9, "bold"), command=_save_reconnect
    ).pack(anchor="w", pady=(8, 0))

    # =========================================================
    # SECTION 3 — SAFETY / SHUTDOWN
    # =========================================================
    sec = create_section(
        "SAFETY",
        "Optionally require a password to reset the dashboard E-STOP mushroom button, "
        "so it can't be cleared by an accidental click."
    )

    current_shutdown_pw = settings_store.get("safety", "shutdown_password", default="0000")
    shutdown_pw_hint = ("Default: 0000" if current_shutdown_pw == "0000"
                        else "Custom password set — enter to change")

    pw_row = tk.Frame(sec, bg=BG_CARD)
    pw_row.pack(fill="x", pady=4)
    tk.Label(pw_row, text="New shutdown password", fg="#9ca3af", bg=BG_CARD,
             font=("Segoe UI", 9), width=20, anchor="w").pack(side="left")
    shutdown_pw_entry = _PlaceholderPasswordEntry(pw_row, shutdown_pw_hint, width=24)
    shutdown_pw_entry.pack(side="left")

    pw_confirm_row = tk.Frame(sec, bg=BG_CARD)
    pw_confirm_row.pack(fill="x", pady=4)
    tk.Label(pw_confirm_row, text="Confirm password", fg="#9ca3af", bg=BG_CARD,
             font=("Segoe UI", 9), width=20, anchor="w").pack(side="left")
    shutdown_pw_confirm_entry = _PlaceholderPasswordEntry(pw_confirm_row, "Re-enter to confirm", width=24)
    shutdown_pw_confirm_entry.pack(side="left")

    tk.Label(sec, text="Click into a field to type — leave both untouched to keep the current password.",
             fg="#4b5563", bg=BG_CARD, font=("Segoe UI", 8)).pack(anchor="w", pady=(2, 8))

    estop_pw_enabled_var = tk.BooleanVar(
        value=settings_store.get("safety", "estop_reset_password_enabled", default=False))
    tk.Checkbutton(sec, text="Require a password to reset the E-STOP button",
                   variable=estop_pw_enabled_var, fg=TEXT, bg=BG_CARD,
                   selectcolor=BG_MAIN, activebackground=BG_CARD,
                   font=("Segoe UI", 9)).pack(anchor="w")

    current_estop_pw = settings_store.get("safety", "estop_reset_password", default="")
    estop_pw_hint = ("Not set" if not current_estop_pw
                     else "Custom password set — enter to change")

    estop_pw_row = tk.Frame(sec, bg=BG_CARD)
    estop_pw_row.pack(fill="x", pady=4)
    tk.Label(estop_pw_row, text="E-STOP reset password", fg="#9ca3af", bg=BG_CARD,
             font=("Segoe UI", 9), width=20, anchor="w").pack(side="left")
    estop_pw_entry = _PlaceholderPasswordEntry(estop_pw_row, estop_pw_hint, width=24)
    estop_pw_entry.pack(side="left")

    # =========================================================
    # SECTION 4 — SERIAL PORT DEFAULTS
    # =========================================================
    sec = create_section(
        "SERIAL PORT DEFAULTS",
        "Automatically remembered the last time you successfully connected each device — "
        "shown here for reference. Forget one if you've switched hardware/cables."
    )

    serial_state = {}

    def _serial_row(dev_label, setting_key):
        row = tk.Frame(sec, bg=BG_CARD)
        row.pack(fill="x", pady=3)
        tk.Label(row, text=dev_label, fg="#9ca3af", bg=BG_CARD,
                 font=("Segoe UI", 9), width=16, anchor="w").pack(side="left")
        val_lbl = tk.Label(row, text="", fg=TEXT, bg=BG_CARD, font=("Segoe UI", 9, "bold"))
        val_lbl.pack(side="left", padx=(0, 12))

        def _refresh():
            port = settings_store.get("serial", setting_key, default="")
            val_lbl.config(text=port if port else "(none saved)")

        def _forget():
            settings_store.set_value(("serial", setting_key), "")
            settings_store.save()
            _refresh()

        tk.Button(row, text="Forget", bg="#7f1d1d", fg="white", relief="flat",
                 font=("Segoe UI", 8), command=_forget).pack(side="left")
        _refresh()
        serial_state[setting_key] = _refresh

    _serial_row("Button Box", "button_box_port")
    _serial_row("SBG IMU", "sbg_port")

    # =========================================================
    # SECTION 5 — ALARMS BEHAVIOR
    # =========================================================
    sec = create_section("ALARMS BEHAVIOR")

    sev_row = tk.Frame(sec, bg=BG_CARD)
    sev_row.pack(fill="x", pady=4)
    tk.Label(sev_row, text="Default manual alarm severity", fg="#9ca3af", bg=BG_CARD,
             font=("Segoe UI", 9), width=26, anchor="w").pack(side="left")
    manual_sev_var = tk.StringVar(
        value=settings_store.get("alarms", "manual_default_severity", default="warning"))
    ttk.Combobox(sev_row, textvariable=manual_sev_var,
                values=["critical", "warning", "info"], state="readonly", width=14
    ).pack(side="left")

    cap_row = tk.Frame(sec, bg=BG_CARD)
    cap_row.pack(fill="x", pady=4)
    tk.Label(cap_row, text="Comms/Control log line cap", fg="#9ca3af", bg=BG_CARD,
             font=("Segoe UI", 9), width=26, anchor="w").pack(side="left")
    log_cap_var = tk.StringVar(
        value=str(settings_store.get("alarms", "log_max_lines", default=500)))
    tk.Entry(cap_row, textvariable=log_cap_var, width=10).pack(side="left")

    auto_row = tk.Frame(sec, bg=BG_CARD)
    auto_row.pack(fill="x", pady=4)
    tk.Label(auto_row, text="Auto-resolve info alarms after (min)", fg="#9ca3af", bg=BG_CARD,
             font=("Segoe UI", 9), width=26, anchor="w").pack(side="left")
    auto_resolve_var = tk.StringVar(
        value=str(settings_store.get("alarms", "info_auto_resolve_minutes", default=0)))
    tk.Entry(auto_row, textvariable=auto_resolve_var, width=10).pack(side="left")
    tk.Label(sec, text="0 = never auto-resolve (default). Only applies to 'info' severity.",
             fg="#4b5563", bg=BG_CARD, font=("Segoe UI", 8)).pack(anchor="w", pady=(2, 0))

    # =========================================================
    # SECTION 6 — OPERATOR / SESSION
    # =========================================================
    sec = create_section(
        "OPERATOR / SESSION",
        "Used as the default 'source' when logging a manual alarm."
    )
    op_row = tk.Frame(sec, bg=BG_CARD)
    op_row.pack(fill="x", pady=4)
    tk.Label(op_row, text="Operator name", fg="#9ca3af", bg=BG_CARD,
             font=("Segoe UI", 9), width=16, anchor="w").pack(side="left")
    operator_var = tk.StringVar(value=str(settings_store.get("operator", "name", default="")))
    tk.Entry(op_row, textvariable=operator_var, width=24).pack(side="left")

    # =========================================================
    # SECTION 7 — DISPLAY
    # =========================================================
    sec = create_section(
        "DISPLAY",
        "Splash background applies immediately after Save — no restart needed."
    )

    tk.Label(sec, text="Splash Background", fg="#9ca3af", bg=BG_CARD,
             font=("Segoe UI", 9)).pack(anchor="w", pady=(0, 6))

    splash_bg_var = tk.StringVar(
        value=settings_store.get("display", "splash_background", default=splash_panel.DEFAULT_PRESET))

    swatch_area = tk.Frame(sec, bg=BG_CARD)
    swatch_area.pack(fill="x", pady=(0, 12))

    swatch_widgets = {}

    def _refresh_swatches():
        for name, sw in swatch_widgets.items():
            selected = (name == splash_bg_var.get())
            sw.config(highlightbackground=ACCENT if selected else BG_PANEL,
                     highlightthickness=3 if selected else 1)

    def _select_preset(name):
        splash_bg_var.set(name)
        _refresh_swatches()

    for name in splash_panel.PRESET_NAMES:
        colors = splash_panel.BACKGROUND_PRESETS[name]
        short_name = name.split(" ")[0]   # "Navy (Default)" -> "Navy"

        swatch = tk.Frame(swatch_area, bg=colors["bg"], width=76, height=48,
                          highlightbackground=BG_PANEL, highlightthickness=1, cursor="hand2")
        swatch.pack(side="left", padx=6)
        swatch.pack_propagate(False)

        lbl = tk.Label(swatch, text=short_name, bg=colors["bg"], fg=colors["heading"],
                       font=("Segoe UI", 8, "bold"))
        lbl.pack(expand=True)

        # Both the frame and its label need the click binding — clicking
        # the text shouldn't miss the swatch underneath it.
        swatch.bind("<Button-1>", lambda e, n=name: _select_preset(n))
        lbl.bind("<Button-1>", lambda e, n=name: _select_preset(n))

        swatch_widgets[name] = swatch

    _refresh_swatches()

    tk.Label(sec, text="⚠ Accent color / auto-rotate below are saved for future use — not yet "
                       "wired up to repaint the running UI.",
             fg="#4b5563", bg=BG_CARD, font=("Segoe UI", 8), wraplength=800,
             justify="left").pack(anchor="w", pady=(0, 6))

    accent_row = tk.Frame(sec, bg=BG_CARD)
    accent_row.pack(fill="x", pady=4)
    tk.Label(accent_row, text="Accent color (hex)", fg="#9ca3af", bg=BG_CARD,
             font=("Segoe UI", 9), width=18, anchor="w").pack(side="left")
    accent_var = tk.StringVar(value=str(settings_store.get("display", "accent_color", default=ACCENT)))
    tk.Entry(accent_row, textvariable=accent_var, width=12).pack(side="left")

    autorotate_var = tk.BooleanVar(value=settings_store.get("display", "splash_autorotate", default=False))
    tk.Checkbutton(sec, text="Auto-rotate sponsor splash", variable=autorotate_var,
                  fg=TEXT, bg=BG_CARD, selectcolor=BG_MAIN, activebackground=BG_CARD,
                  font=("Segoe UI", 9)).pack(anchor="w", pady=(6, 0))

    # =========================================================
    # SAVE ALL
    # =========================================================
    def _save_all():
        errors = []

        # ---- thresholds ----
        for key, (warn_var, crit_var) in threshold_vars.items():
            try:
                warn = float(warn_var.get())
                crit = float(crit_var.get())
            except ValueError:
                errors.append(f"Threshold for {key} — must be numbers, not saved.")
                continue
            monitoring_panel.set_threshold(key, warn, crit)
            settings_store.set_value(("thresholds", key), {"warn": warn, "crit": crit})

        # ---- network (values only — no forced reconnect here) ----
        try:
            port_val = int(port_var.get())
            settings_store.set_value(("network", "broker"), broker_var.get().strip())
            settings_store.set_value(("network", "port"), port_val)
        except ValueError:
            errors.append("Network port must be a whole number — not saved.")

        # ---- safety ----
        new_pw = shutdown_pw_entry.get_value()
        confirm_pw = shutdown_pw_confirm_entry.get_value()
        if new_pw or confirm_pw:
            if new_pw != confirm_pw:
                errors.append("Shutdown password fields didn't match — not changed.")
            else:
                settings_store.set_value(("safety", "shutdown_password"), new_pw)
                shutdown_pw_entry.reset(
                    "Default: 0000" if new_pw == "0000" else "Custom password set — enter to change")
                shutdown_pw_confirm_entry.reset("Re-enter to confirm")

        settings_store.set_value(("safety", "estop_reset_password_enabled"), estop_pw_enabled_var.get())
        estop_new_pw = estop_pw_entry.get_value()
        if estop_new_pw:
            settings_store.set_value(("safety", "estop_reset_password"), estop_new_pw)
            estop_pw_entry.reset("Custom password set — enter to change")

        # ---- alarms behavior ----
        settings_store.set_value(("alarms", "manual_default_severity"), manual_sev_var.get())
        try:
            cap = int(log_cap_var.get())
            settings_store.set_value(("alarms", "log_max_lines"), cap)
            dashboard_panel.set_max_log_lines(cap)
        except ValueError:
            errors.append("Log line cap must be a whole number — not saved.")
        try:
            minutes = int(auto_resolve_var.get())
            settings_store.set_value(("alarms", "info_auto_resolve_minutes"), minutes)
        except ValueError:
            errors.append("Info auto-resolve minutes must be a whole number — not saved.")

        # ---- operator ----
        settings_store.set_value(("operator", "name"), operator_var.get().strip())

        # ---- display (splash background is live; accent/autorotate stored only) ----
        settings_store.set_value(("display", "splash_background"), splash_bg_var.get())
        settings_store.set_value(("display", "accent_color"), accent_var.get().strip())
        settings_store.set_value(("display", "splash_autorotate"), autorotate_var.get())

        ok = settings_store.save()
        splash_panel.refresh_splash()

        # refresh the serial port "remembered" labels in case something changed elsewhere
        for refresh in serial_state.values():
            refresh()

        if errors:
            messagebox.showwarning("Some settings weren't saved",
                                   "\n".join(errors))
        if ok:
            saved_lbl.config(text="✓ Saved")
            panel.after(2000, lambda: saved_lbl.config(text=""))
        else:
            messagebox.showerror("Save Failed", f"Could not write to {settings_store.SETTINGS_PATH}")

    save_bar = tk.Frame(body, bg=BG_MAIN)
    save_bar.pack(fill="x", padx=15, pady=(4, 20))
    tk.Button(save_bar, text="Save All Settings", bg=ACCENT, fg="black", relief="flat",
             font=("Segoe UI", 11, "bold"), command=_save_all
    ).pack(anchor="e")