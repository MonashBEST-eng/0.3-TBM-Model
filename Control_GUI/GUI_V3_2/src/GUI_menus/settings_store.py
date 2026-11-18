# settings_store.py
#
# Single source of truth for user-tunable settings, persisted to a JSON file
# in the user's home directory so they survive an app restart (this is a
# desktop Tk app, not a browser — there's no localStorage here, so we own
# the file ourselves).
#
# Usage:
#   import GUI_menus.settings_store as settings_store
#   broker = settings_store.get("network", "broker")
#   settings_store.set_value(("network", "broker"), "10.0.0.5")
#   settings_store.save()
#
# SETTINGS is loaded once at import time and kept live in memory; every
# panel reads/writes the same dict, so changes are visible everywhere
# immediately, even before save() is called. save() is what makes them
# durable across restarts.

import json
import os

SETTINGS_PATH = os.path.join(os.path.expanduser("~"), ".tbm_gui_settings.json")

# Defaults for everything except sensor thresholds — those are defined in
# monitoring_panel.SENSORS and only *overridden* here if the user changes
# one, so the two can't drift out of sync.
DEFAULTS = {
    "network": {
        "broker": "192.168.1.10",
        "port": 1883,
    },
    "safety": {
        "shutdown_password": "0000",
        "estop_reset_password_enabled": False,
        "estop_reset_password": "",
    },
    "serial": {
        "button_box_port": "",
        "sbg_port": "",
    },
    "alarms": {
        "manual_default_severity": "warning",
        "log_max_lines": 500,
        "info_auto_resolve_minutes": 0,   # 0 = never auto-resolve info alarms
    },
    "operator": {
        "name": "",
    },
    "display": {
        "accent_color": "#22c55e",
        "splash_autorotate": False,
        "splash_background": "Navy (Default)",
    },
    "thresholds": {},   # sensor_key -> {"warn": float, "crit": float}
}


def _deep_merge(defaults, overrides):
    """Recursively merge saved values onto the defaults, so new settings
    added in later versions always have a sane value even in an old file."""
    result = {}
    for k, v in defaults.items():
        if isinstance(v, dict):
            child_overrides = overrides.get(k) if isinstance(overrides.get(k), dict) else {}
            result[k] = _deep_merge(v, child_overrides)
        else:
            result[k] = overrides.get(k, v)
    return result


def load():
    saved = {}
    if os.path.exists(SETTINGS_PATH):
        try:
            with open(SETTINGS_PATH, "r") as f:
                saved = json.load(f)
        except Exception:
            saved = {}
    return _deep_merge(DEFAULTS, saved)


SETTINGS = load()


def save() -> bool:
    """Write the current in-memory SETTINGS to disk. Returns True on success."""
    try:
        with open(SETTINGS_PATH, "w") as f:
            json.dump(SETTINGS, f, indent=2)
        return True
    except Exception:
        return False


def get(*path, default=None):
    """settings_store.get('network', 'broker') -> '192.168.1.10'"""
    node = SETTINGS
    for p in path:
        if not isinstance(node, dict) or p not in node:
            return default
        node = node[p]
    return node


def set_value(path, value):
    """settings_store.set_value(('network', 'broker'), '10.0.0.5')
    Updates in-memory only — call save() to persist to disk."""
    node = SETTINGS
    for p in path[:-1]:
        node = node.setdefault(p, {})
    node[path[-1]] = value