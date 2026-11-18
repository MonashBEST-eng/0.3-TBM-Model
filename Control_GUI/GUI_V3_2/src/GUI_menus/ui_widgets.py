# ui_widgets.py
# Reusable "industrial pushbutton" widget — a round, backlit-look button
# drawn on a Canvas, same visual family as the dashboard's E-STOP mushroom
# button. Used throughout the Control Panel so every command button looks
# like a real physical control instead of a flat Tk button.

import tkinter as tk


def _clamp(v) -> int:
    return max(0, min(255, int(v)))


def _shade(hex_color: str, factor: float) -> str:
    """Darken a hex color by multiplying each channel by `factor` (<1)."""
    hex_color = hex_color.lstrip("#")
    r, g, b = int(hex_color[0:2], 16), int(hex_color[2:4], 16), int(hex_color[4:6], 16)
    return f"#{_clamp(r * factor):02x}{_clamp(g * factor):02x}{_clamp(b * factor):02x}"


def _lighten(hex_color: str, amount: float) -> str:
    """Lighten a hex color toward white by `amount` (0-1)."""
    hex_color = hex_color.lstrip("#")
    r, g, b = int(hex_color[0:2], 16), int(hex_color[2:4], 16), int(hex_color[4:6], 16)
    r = _clamp(r + (255 - r) * amount)
    g = _clamp(g + (255 - g) * amount)
    b = _clamp(b + (255 - b) * amount)
    return f"#{r:02x}{g:02x}{b:02x}"


def make_industrial_button(parent, label, color, command=None, size=70, bg=None):
    """
    A round, backlit-look industrial pushbutton — dark metal bezel, colored
    face, glossy highlight. Fires `command` immediately on click (like a
    real momentary pushbutton), with a brief pressed-in flash for tactile
    feedback rather than waiting for release.

    label: button text, use "\\n" for a second line on tight buttons.
    color: hex color for the face, e.g. "#ef4444".
    size:  diameter in pixels.
    """
    try:
        bg = bg or parent["bg"]
    except Exception:
        bg = bg or "#1f2937"

    dark = _shade(color, 0.55)
    light = _lighten(color, 0.35)

    canvas = tk.Canvas(parent, width=size, height=size, bg=bg, highlightthickness=0)

    def _draw(pressed=False):
        canvas.delete("all")
        cx, cy = size // 2, size // 2
        r = size // 2 - 5

        # Outer bezel ring (dark metal housing)
        canvas.create_oval(cx - r - 5, cy - r - 5, cx + r + 5, cy + r + 5,
                           fill="#111827", outline="#374151", width=2)

        face = dark if pressed else color
        rr = r - 3 if pressed else r
        canvas.create_oval(cx - rr, cy - rr, cx + rr, cy + rr,
                           fill=face, outline=_shade(color, 0.35), width=1)

        # Glossy highlight — the same trick used on the E-STOP mushroom
        hl_r = rr * 0.55
        canvas.create_oval(cx - hl_r, cy - rr * 0.55, cx + hl_r, cy - rr * 0.55 + hl_r * 0.85,
                           fill=light, outline="")

        canvas.create_text(cx, cy + rr * 0.15, text=label, fill="white",
                           font=("Segoe UI", 8, "bold"), justify="center")

    def _on_click(event=None):
        _draw(pressed=True)
        if command:
            command()
        canvas.after(120, lambda: _draw(pressed=False))

    canvas.bind("<Button-1>", _on_click)
    _draw()
    return canvas


def make_placeholder_slot(parent, size=70, text="+"):
    """A dashed-outline empty slot — used inside category cards for control
    positions reserved for a future button, and for whole future category
    cards on the Control Panel grid."""
    canvas = tk.Canvas(parent, width=size, height=size, highlightthickness=0)
    canvas.configure(bg=parent["bg"] if "bg" in parent.keys() else "#0f172a")
    canvas.create_oval(4, 4, size - 4, size - 4, outline="#374151", width=2, dash=(5, 3))
    canvas.create_text(size // 2, size // 2, text=text, fill="#374151",
                       font=("Segoe UI", int(size * 0.28), "bold"))
    return canvas