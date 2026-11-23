# splash_panel.py
# Sponsor splash screen shown in the main window's content area by default.
# Sidebar (nav buttons, indicators, status card) stays visible around it --
# this just fills the content pane that used to hold the live dashboard.
#
# Drop sponsor logo images into GUI_images/sponsors/ and they'll show up
# here automatically -- no code changes needed. Supports .png, .jpg, .jpeg,
# .gif, .bmp. Logos are scaled down to fit the tile while keeping their
# aspect ratio (never stretched/cropped).
#
# Background is one of BACKGROUND_PRESETS below, chosen in Settings ->
# Display -> Splash Background. refresh_splash() re-renders it live from
# whatever's currently saved, so picking a new one in Settings takes effect
# immediately -- no app restart needed.

import os
import sys

try:
    from PIL import Image, ImageTk
    PIL_AVAILABLE = True
except ImportError:
    PIL_AVAILABLE = False

import tkinter as tk
import GUI_menus.settings_store as settings_store

SPONSOR_FOLDER    = "GUI_images/sponsors"
SPONSOR_COLS      = 4
SPONSOR_TILE_SIZE = (220, 120)   # (w, h) box each logo is scaled to fit inside

# Sponsor tiles are always white, regardless of splash background preset —
# most logo files assume a light background (or have transparent edges that
# should read as white, not whatever theme color happens to be selected).
SPONSOR_TILE_BG     = "#ffffff"
SPONSOR_TILE_BORDER = "#d1d5db"

# =========================
# BACKGROUND PRESETS
# Each preset supplies every color the splash needs, chosen as a set so
# text stays readable regardless of how light/dark the background is --
# rather than trying to derive readable colors from just one bg value.
# =========================
BACKGROUND_PRESETS = {
    "Navy (Default)": {
        "bg": "#0f172a", "card_bg": "#1f2937",
        "heading": "#ffffff", "accent": "#22c55e",
        "subtext": "#9ca3af", "muted": "#4b5563",
    },
    "White": {
        "bg": "#ffffff", "card_bg": "#f3f4f6",
        "heading": "#111827", "accent": "#16a34a",
        "subtext": "#6b7280", "muted": "#9ca3af",
    },
    "Teal": {
        "bg": "#0f3d3a", "card_bg": "#115e59",
        "heading": "#ecfeff", "accent": "#5eead4",
        "subtext": "#99f6e4", "muted": "#5eead4",
    },
    "Charcoal": {
        "bg": "#18181b", "card_bg": "#27272a",
        "heading": "#f4f4f5", "accent": "#a78bfa",
        "subtext": "#a1a1aa", "muted": "#71717a",
    },
    "Slate": {
        "bg": "#1e293b", "card_bg": "#334155",
        "heading": "#f1f5f9", "accent": "#38bdf8",
        "subtext": "#94a3b8", "muted": "#64748b",
    },
    "Forest": {
        "bg": "#052e16", "card_bg": "#14532d",
        "heading": "#f0fdf4", "accent": "#4ade80",
        "subtext": "#86efac", "muted": "#4d7c5f",
    },
}
PRESET_NAMES = list(BACKGROUND_PRESETS.keys())
DEFAULT_PRESET = "Navy (Default)"

# Keep references to PhotoImage objects alive for the life of the widget
_image_refs = []

# Remembers the last parent passed to build_splash() so Settings can
# trigger a live re-render without the main GUI needing to know about it.
_last_parent = None


def _resource_path(relative_path):
    try:
        base_path = sys._MEIPASS   # PyInstaller temp folder
    except AttributeError:
        base_path = os.path.abspath(".")
    return os.path.join(base_path, relative_path)


def _current_colors():
    name = settings_store.get("display", "splash_background", default=DEFAULT_PRESET)
    return BACKGROUND_PRESETS.get(name, BACKGROUND_PRESETS[DEFAULT_PRESET])


def _load_sponsor_images(folder=SPONSOR_FOLDER, box=SPONSOR_TILE_SIZE):
    """Scan `folder` for image files and return [(display_name, PhotoImage), ...]."""
    images = []
    if not PIL_AVAILABLE:
        return images

    path = _resource_path(folder)
    if not os.path.isdir(path):
        return images

    valid_ext = (".png", ".jpg", ".jpeg", ".gif", ".bmp")
    for fname in sorted(os.listdir(path)):
        if not fname.lower().endswith(valid_ext):
            continue
        try:
            img = Image.open(os.path.join(path, fname)).convert("RGBA")
            img.thumbnail(box, Image.LANCZOS)   # preserves aspect ratio
            photo = ImageTk.PhotoImage(img)
            name = os.path.splitext(fname)[0].replace("_", " ").replace("-", " ").title()
            images.append((name, photo))
        except Exception:
            continue

    return images


def build_splash(parent):
    """
    Populate `parent` (a Frame) with the sponsor splash screen, using
    whichever background preset is currently saved in Settings.
    Safe to call more than once on the same parent (e.g. from
    refresh_splash()) -- clears out the previous render first.
    """
    global _last_parent
    _last_parent = parent

    for child in parent.winfo_children():
        child.destroy()
    _image_refs.clear()

    c = _current_colors()

    splash = tk.Frame(parent, bg=c["bg"])
    splash.pack(fill="both", expand=True)

    # ---- Main logo ----
    logo_photo = None
    if PIL_AVAILABLE:
        logo_path = _resource_path("GUI_images/logo.png")
        if os.path.exists(logo_path):
            try:
                img = Image.open(logo_path).resize((140, 140), Image.LANCZOS)
                logo_photo = ImageTk.PhotoImage(img)
            except Exception:
                logo_photo = None

    if logo_photo:
        _image_refs.append(logo_photo)
        tk.Label(splash, image=logo_photo, bg=c["bg"]).pack(pady=(50, 10))
    else:
        tk.Frame(splash, bg=c["bg"], height=30).pack()

    # ---- Welcome text ----
    tk.Label(splash, text="MONASH BEST",
             fg=c["heading"], bg=c["bg"],
             font=("Segoe UI", 30, "bold")).pack()

    tk.Label(splash, text="TBM CONTROL SYSTEM",
             fg=c["accent"], bg=c["bg"],
             font=("Segoe UI", 14, "bold")).pack(pady=(0, 6))

    tk.Label(splash,
             text="Use the sidebar to open Dashboard, Monitoring, Control Panel and more.",
             fg=c["subtext"], bg=c["bg"],
             font=("Segoe UI", 10)).pack(pady=(0, 30))

    # ---- Sponsors ----
    tk.Label(splash, text="WITH THANKS TO OUR SPONSORS",
             fg=c["accent"], bg=c["bg"],
             font=("Segoe UI", 11, "bold")).pack(pady=(0, 14))

    sponsor_images = _load_sponsor_images()

    # ---- ONE large white panel that every sponsor logo sits inside,
    # instead of each logo getting its own separate bordered box ----
    sponsor_panel = tk.Frame(splash, bg=SPONSOR_TILE_BG,
                             highlightbackground=SPONSOR_TILE_BORDER, highlightthickness=2)
    sponsor_panel.pack(pady=(0, 30))

    grid_outer = tk.Frame(sponsor_panel, bg=SPONSOR_TILE_BG)
    grid_outer.pack(padx=36, pady=32)

    if sponsor_images:
        for i, (name, photo) in enumerate(sponsor_images):
            _image_refs.append(photo)
            row, col = divmod(i, SPONSOR_COLS)

            # Each logo gets its own fixed-size cell so mismatched aspect
            # ratios don't throw off row alignment, but no border/fill of
            # its own — it's just part of the one big white panel.
            cell = tk.Frame(grid_outer, bg=SPONSOR_TILE_BG,
                            width=SPONSOR_TILE_SIZE[0], height=SPONSOR_TILE_SIZE[1])
            cell.grid(row=row, column=col, padx=18, pady=18)
            cell.grid_propagate(False)

            img_lbl = tk.Label(cell, image=photo, bg=SPONSOR_TILE_BG)
            img_lbl.pack(expand=True)
    else:
        # Panel is always white now, so this message needs a fixed color
        # too rather than the splash preset's muted text color.
        tk.Label(grid_outer,
                 text=f"Drop sponsor logo files into  {SPONSOR_FOLDER}/\n"
                      "to have them appear here automatically.",
                 fg="#6b7280", bg=SPONSOR_TILE_BG,
                 font=("Segoe UI", 9), justify="center").pack(padx=40, pady=40)

    return splash


def refresh_splash():
    """Re-render the splash using whatever background preset is currently
    saved. Called by the Settings panel after Save so a new choice shows up
    immediately -- no app restart required. No-op if the splash isn't
    currently on screen (e.g. another panel is focused)."""
    if _last_parent is not None and _last_parent.winfo_exists():
        build_splash(_last_parent)