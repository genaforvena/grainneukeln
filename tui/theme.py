"""Visual identity for the grainneukeln TUI.

A single Textual theme ("grain") + a couple of colour helpers the banner uses to paint
gradients. Palette is a tokyonight-derived modular-synth look: neon violet/cyan/amber on
near-black. Every panel border, button, cursor and progress bar reads from these theme
variables, so re-tinting the whole app is a one-line palette edit here.
"""

from textual.theme import Theme

# --- palette (single source of truth) ---
BG      = "#15161e"   # screen
SURFACE = "#1a1b26"   # inputs / logs
PANEL   = "#24283b"   # raised chrome (table header, footer)
FG      = "#c0caf5"   # body text
DIM     = "#565f89"   # helper / captions

VIOLET  = "#bb9af7"
CYAN    = "#7dcfff"
BLUE    = "#7aa2f7"
TEAL    = "#73daca"
AMBER   = "#ff9e64"
GREEN   = "#9ece6a"
YELLOW  = "#e0af68"
RED     = "#f7768e"

grain_theme = Theme(
    name="grain",
    primary=VIOLET,
    secondary=CYAN,
    accent=AMBER,
    foreground=FG,
    background=BG,
    surface=SURFACE,
    panel=PANEL,
    success=GREEN,
    warning=YELLOW,
    error=RED,
    dark=True,
    variables={
        "block-cursor-foreground": BG,
        "block-cursor-background": VIOLET,
        "block-cursor-text-style": "bold",
        "input-cursor-background": CYAN,
        "input-selection-background": f"{VIOLET} 35%",
        "footer-key-foreground": CYAN,
        "footer-description-foreground": FG,
        "scrollbar": PANEL,
        "scrollbar-hover": VIOLET,
        "scrollbar-active": CYAN,
        "border": VIOLET,
    },
)


# --- gradient helpers (used by the banner to paint the wordmark + waveform) ---
def _rgb(h):
    h = h.lstrip("#")
    return tuple(int(h[i:i + 2], 16) for i in (0, 2, 4))


def _hex(rgb):
    return "#%02x%02x%02x" % tuple(max(0, min(255, int(round(c)))) for c in rgb)


def gradient(n, stops):
    """Return `n` hex colours interpolated evenly across the list of `stops` (hex strings)."""
    if n <= 0:
        return []
    cols = [_rgb(s) for s in stops]
    if n == 1 or len(cols) == 1:
        return [_hex(cols[0])] * n
    segs = len(cols) - 1
    out = []
    for i in range(n):
        p = i / (n - 1) * segs
        j = min(int(p), segs - 1)
        f = p - j
        a, b = cols[j], cols[j + 1]
        out.append(_hex(tuple(a[k] + (b[k] - a[k]) * f for k in range(3))))
    return out
