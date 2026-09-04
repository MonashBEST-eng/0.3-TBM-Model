# alarms_panel.py
# Central alarm system for the TBM GUI.
#
# Two ways alarms get created:
#   1. Auto-generated — sensor thresholds (monitoring_panel.py) and system
#      events (MQTT/button-box connection loss, emergency stop, safe mode)
#      call raise_alarm(key, ...) when a condition starts and clear_alarm(key)
#      when it ends. Because they're keyed by a stable condition id, raising
#      the same condition repeatedly just refreshes it — no duplicates — and
#      clearing auto-resolves it the moment the condition goes away.
#   2. Manual — add_manual_alarm(severity, message) lets an operator log
#      something by hand from the Alarms panel. Manual alarms have no
#      "condition" behind them, so they only go away when dismissed.
#
# Workflow: an active alarm can be ACKNOWLEDGED (seen, but the underlying
# condition hasn't cleared yet) and/or RESOLVED (condition cleared, or it was
# DISMISSED by hand). Every alarm — auto or manual — stays in history after
# it resolves, so nothing gets lost.
#
# Public API (safe to call whether or not the panel is open):
#   raise_alarm(key, severity, source, message)
#   clear_alarm(key)
#   acknowledge_alarm(key)
#   dismiss_alarm(key)
#   add_manual_alarm(severity, message, source="Operator") -> key
#   get_active_count() / get_unacknowledged_count()
#   register_change_callback(cb)   # cb() fires whenever alarms change,
#                                   # e.g. to refresh a sidebar badge

import time
import tkinter as tk
from tkinter import ttk
import GUI_menus.settings_store as settings_store

# =========================
# THEME — matches main GUI
# =========================
BG_MAIN  = "#0f172a"
BG_PANEL = "#111827"
BG_CARD  = "#1f2937"
ACCENT   = "#22c55e"
TEXT     = "#e5e7eb"

SEVERITY_COLORS = {"critical": "#ef4444", "warning": "#f97316", "info": "#38bdf8"}
SEVERITY_ORDER  = {"critical": 0, "warning": 1, "info": 2}
MAX_HISTORY = 500

# =========================
# DATA STATE
# _active and _history entries for the same alarm are the SAME dict object,
# so resolving/acknowledging updates both places at once — no syncing needed.
# =========================
_active: dict[str, dict] = {}
_history: list[dict] = []

_on_change_callback = None

# =========================
# MODULE-LEVEL WIDGET REFS — set while the panel is open, cleared on close
# =========================
_panel_ref: tk.Toplevel | None = None
_active_container: tk.Frame | None = None
_history_container: tk.Frame | None = None


# =========================
# PUBLIC API
# =========================
def register_change_callback(cb):
    """cb() is called with no args whenever an alarm is raised/cleared/
    acknowledged/dismissed — use it to refresh a sidebar badge."""
    global _on_change_callback
    _on_change_callback = cb


def _notify():
    if _on_change_callback is not None:
        try:
            _on_change_callback()
        except Exception:
            pass
    _refresh_if_open()


def raise_alarm(key, severity, source, message):
    """Start (or refresh) a condition-based alarm. Calling this repeatedly
    for the same key while the condition persists does NOT duplicate it."""
    now = time.strftime("%H:%M:%S")
    existing = _active.get(key)
    if existing is not None and not existing["resolved"]:
        existing["severity"] = severity
        existing["message"] = message
        existing["last_seen"] = now
    else:
        alarm = {
            "key": key, "severity": severity, "source": source,
            "message": message, "raised_at": now, "raised_ts": time.time(), "last_seen": now,
            "acknowledged": False, "resolved": False, "resolved_at": None,
        }
        _active[key] = alarm
        _history.insert(0, alarm)
        del _history[MAX_HISTORY:]
    _notify()


def clear_alarm(key):
    """Auto-resolve a condition-based alarm once it's no longer true.
    Safe to call even if the key was never raised."""
    alarm = _active.pop(key, None)
    if alarm is not None and not alarm["resolved"]:
        alarm["resolved"] = True
        alarm["resolved_at"] = time.strftime("%H:%M:%S")
        _notify()


def acknowledge_alarm(key):
    """Mark an active alarm as seen. It stays active until its condition
    clears (or it's dismissed) — acknowledging just silences it."""
    alarm = _active.get(key)
    if alarm is not None:
        alarm["acknowledged"] = True
        _notify()


def dismiss_alarm(key):
    """Manually resolve an alarm regardless of its underlying condition —
    the only way manual alarms ever go away."""
    alarm = _active.pop(key, None)
    if alarm is not None:
        alarm["resolved"] = True
        alarm["resolved_at"] = time.strftime("%H:%M:%S")
        alarm["acknowledged"] = True
        _notify()


def add_manual_alarm(severity, message, source="Operator"):
    """Log a one-off alarm by hand. Returns its key (only useful if you want
    to dismiss it programmatically later — normally just let the operator
    dismiss it from the panel)."""
    key = f"MANUAL_{int(time.time() * 1000)}"
    raise_alarm(key, severity, source, message)
    return key


def get_active_count() -> int:
    return len(_active)


def get_unacknowledged_count() -> int:
    return sum(1 for a in _active.values() if not a["acknowledged"])


def start_auto_resolve_timer(root, interval_ms: int = 30000):
    """Periodically auto-resolves 'info' severity alarms once they've been
    active longer than settings_store's alarms.info_auto_resolve_minutes
    (0 = disabled, the default). Call this once from the main GUI after
    the root window exists."""

    def _tick():
        minutes = settings_store.get("alarms", "info_auto_resolve_minutes", default=0)
        if minutes and minutes > 0:
            cutoff = time.time() - (minutes * 60)
            for key, alarm in list(_active.items()):
                if alarm["severity"] == "info" and alarm["raised_ts"] <= cutoff:
                    clear_alarm(key)
        root.after(interval_ms, _tick)

    root.after(interval_ms, _tick)


# =========================
# RENDERING HELPERS
# =========================
def _refresh_if_open():
    if _panel_ref is not None and _panel_ref.winfo_exists():
        _render_active()
        _render_history()


def _severity_badge(parent, severity):
    color = SEVERITY_COLORS.get(severity, TEXT)
    return tk.Label(parent, text=severity.upper(), fg="white", bg=color,
                    font=("Segoe UI", 8, "bold"), padx=6, pady=1)


def _render_active():
    if _active_container is None:
        return
    for w in _active_container.winfo_children():
        w.destroy()

    if not _active:
        tk.Label(_active_container, text="No active alarms — all clear.",
                 fg="#4b5563", bg=BG_CARD, font=("Segoe UI", 9)
        ).pack(anchor="w", padx=8, pady=10)
        return

    ordered = sorted(
        _active.values(),
        key=lambda a: (a["acknowledged"], SEVERITY_ORDER.get(a["severity"], 9), a["raised_at"])
    )

    for alarm in ordered:
        row = tk.Frame(_active_container, bg=BG_MAIN)
        row.pack(fill="x", padx=8, pady=3)

        _severity_badge(row, alarm["severity"]).pack(side="left", padx=(6, 10), pady=6)

        text_col = tk.Frame(row, bg=BG_MAIN)
        text_col.pack(side="left", fill="x", expand=True, pady=6)
        tk.Label(text_col, text=f'{alarm["source"]}  •  {alarm["raised_at"]}',
                 fg="#6b7280", bg=BG_MAIN, font=("Segoe UI", 7)).pack(anchor="w")
        tk.Label(text_col, text=alarm["message"], fg=TEXT, bg=BG_MAIN,
                 font=("Segoe UI", 9), wraplength=520, justify="left").pack(anchor="w")

        btn_col = tk.Frame(row, bg=BG_MAIN)
        btn_col.pack(side="right", padx=8)

        if not alarm["acknowledged"]:
            tk.Button(btn_col, text="Acknowledge", bg="#374151", fg="white", relief="flat",
                     font=("Segoe UI", 8),
                     command=lambda k=alarm["key"]: acknowledge_alarm(k)).pack(side="left", padx=3)
        else:
            tk.Label(btn_col, text="ACK'D", fg="#6b7280", bg=BG_MAIN,
                    font=("Segoe UI", 8)).pack(side="left", padx=3)

        tk.Button(btn_col, text="Dismiss", bg="#7f1d1d", fg="white", relief="flat",
                 font=("Segoe UI", 8),
                 command=lambda k=alarm["key"]: dismiss_alarm(k)).pack(side="left", padx=3)


def _render_history():
    if _history_container is None:
        return
    for w in _history_container.winfo_children():
        w.destroy()

    if not _history:
        tk.Label(_history_container, text="No alarms logged yet.",
                 fg="#4b5563", bg=BG_CARD, font=("Segoe UI", 9)
        ).pack(anchor="w", padx=8, pady=10)
        return

    for alarm in _history:
        row = tk.Frame(_history_container, bg=BG_MAIN)
        row.pack(fill="x", padx=8, pady=2)

        _severity_badge(row, alarm["severity"]).pack(side="left", padx=(6, 10), pady=4)

        status = "RESOLVED" if alarm["resolved"] else "ACTIVE"
        status_color = "#6b7280" if alarm["resolved"] else "#ef4444"

        text_col = tk.Frame(row, bg=BG_MAIN)
        text_col.pack(side="left", fill="x", expand=True, pady=4)
        meta = f'{alarm["source"]}  •  raised {alarm["raised_at"]}'
        if alarm["resolved_at"]:
            meta += f'  •  resolved {alarm["resolved_at"]}'
        tk.Label(text_col, text=meta, fg="#6b7280", bg=BG_MAIN,
                 font=("Segoe UI", 7)).pack(anchor="w")
        tk.Label(text_col, text=alarm["message"], fg=TEXT, bg=BG_MAIN,
                 font=("Segoe UI", 9), wraplength=600, justify="left").pack(anchor="w")

        tk.Label(row, text=status, fg=status_color, bg=BG_MAIN,
                font=("Segoe UI", 8, "bold")).pack(side="right", padx=10)


# =========================
# MANUAL ALARM DIALOG
# =========================
def _open_manual_alarm_dialog(parent):
    dlg = tk.Toplevel(parent)
    dlg.title("Log Manual Alarm")
    dlg.configure(bg=BG_MAIN)
    dlg.geometry("420x300")
    dlg.resizable(False, False)

    tk.Label(dlg, text="LOG MANUAL ALARM", fg="white", bg=BG_MAIN,
             font=("Segoe UI", 12, "bold")).pack(pady=(16, 12))

    form = tk.Frame(dlg, bg=BG_MAIN)
    form.pack(fill="x", padx=20)
    form.columnconfigure(1, weight=1)

    tk.Label(form, text="Severity", fg="#9ca3af", bg=BG_MAIN,
             font=("Segoe UI", 9)).grid(row=0, column=0, sticky="w", pady=6)
    default_severity = settings_store.get("alarms", "manual_default_severity", default="warning")
    sev_var = tk.StringVar(value=default_severity)
    ttk.Combobox(form, textvariable=sev_var, values=["critical", "warning", "info"],
                state="readonly", width=18).grid(row=0, column=1, sticky="w", pady=6)

    tk.Label(form, text="Source", fg="#9ca3af", bg=BG_MAIN,
             font=("Segoe UI", 9)).grid(row=1, column=0, sticky="w", pady=6)
    default_source = settings_store.get("operator", "name", default="") or "Operator"
    source_var = tk.StringVar(value=default_source)
    tk.Entry(form, textvariable=source_var, width=24).grid(row=1, column=1, sticky="w", pady=6)

    tk.Label(form, text="Message", fg="#9ca3af", bg=BG_MAIN,
             font=("Segoe UI", 9)).grid(row=2, column=0, sticky="nw", pady=6)
    msg_text = tk.Text(form, width=26, height=5)
    msg_text.grid(row=2, column=1, sticky="w", pady=6)

    def _submit():
        msg = msg_text.get("1.0", "end").strip()
        if not msg:
            return
        add_manual_alarm(sev_var.get(), msg, source=source_var.get().strip() or "Operator")
        dlg.destroy()

    tk.Button(dlg, text="Log Alarm", bg=ACCENT, fg="black", relief="flat",
             font=("Segoe UI", 10, "bold"), command=_submit).pack(pady=16)


# =========================
# PANEL WINDOW
# =========================
def open_alarms_panel(root):
    global _panel_ref, _active_container, _history_container

    if _panel_ref is not None and _panel_ref.winfo_exists():
        _panel_ref.lift()
        _panel_ref.focus_force()
        return

    panel = tk.Toplevel(root)
    panel.title("TBM Alarms")
    panel.geometry("1000x820")
    panel.configure(bg=BG_MAIN)
    _panel_ref = panel

    # ---- Header ----
    hdr = tk.Frame(panel, bg=BG_PANEL)
    hdr.pack(fill="x")
    tk.Label(hdr, text="ALARMS", fg="white", bg=BG_PANEL,
             font=("Segoe UI", 16, "bold")).pack(side="left", padx=16, pady=12)
    tk.Button(hdr, text="+ Log Alarm", bg=BG_CARD, fg="white", relief="flat",
             font=("Segoe UI", 9, "bold"),
             command=lambda: _open_manual_alarm_dialog(panel)).pack(side="right", padx=16)

    # ---- ACTIVE ALARMS ----
    active_card = tk.Frame(panel, bg=BG_CARD)
    active_card.pack(fill="both", expand=True, padx=15, pady=(12, 6))
    tk.Label(active_card, text="ACTIVE ALARMS", fg="cyan", bg=BG_CARD,
             font=("Segoe UI", 11, "bold")).pack(anchor="w", padx=12, pady=(10, 4))

    active_canvas = tk.Canvas(active_card, bg=BG_CARD, highlightthickness=0, height=300)
    active_scroll = tk.Scrollbar(active_card, orient="vertical", command=active_canvas.yview)
    active_canvas.configure(yscrollcommand=active_scroll.set)
    active_canvas.pack(side="left", fill="both", expand=True, padx=(12, 0), pady=(0, 10))
    active_scroll.pack(side="right", fill="y", pady=(0, 10))

    active_container = tk.Frame(active_canvas, bg=BG_CARD)
    _awin = active_canvas.create_window((0, 0), window=active_container, anchor="nw")
    active_container.bind("<Configure>",
                          lambda e: active_canvas.configure(scrollregion=active_canvas.bbox("all")))
    active_canvas.bind("<Configure>", lambda e: active_canvas.itemconfig(_awin, width=e.width))
    _active_container = active_container

    # ---- ALARM HISTORY ----
    history_card = tk.Frame(panel, bg=BG_CARD)
    history_card.pack(fill="both", expand=True, padx=15, pady=(6, 15))
    tk.Label(history_card, text="ALARM HISTORY", fg="#a78bfa", bg=BG_CARD,
             font=("Segoe UI", 11, "bold")).pack(anchor="w", padx=12, pady=(10, 4))

    history_canvas = tk.Canvas(history_card, bg=BG_CARD, highlightthickness=0)
    history_scroll = tk.Scrollbar(history_card, orient="vertical", command=history_canvas.yview)
    history_canvas.configure(yscrollcommand=history_scroll.set)
    history_canvas.pack(side="left", fill="both", expand=True, padx=(12, 0), pady=(0, 10))
    history_scroll.pack(side="right", fill="y", pady=(0, 10))

    history_container = tk.Frame(history_canvas, bg=BG_CARD)
    _hwin = history_canvas.create_window((0, 0), window=history_container, anchor="nw")
    history_container.bind("<Configure>",
                           lambda e: history_canvas.configure(scrollregion=history_canvas.bbox("all")))
    history_canvas.bind("<Configure>", lambda e: history_canvas.itemconfig(_hwin, width=e.width))
    _history_container = history_container

    _render_active()
    _render_history()

    def _on_close():
        global _panel_ref, _active_container, _history_container
        _panel_ref = None
        _active_container = None
        _history_container = None
        panel.destroy()

    panel.protocol("WM_DELETE_WINDOW", _on_close)