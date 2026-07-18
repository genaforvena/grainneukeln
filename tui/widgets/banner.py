"""Animated masthead for the grainneukeln TUI.

Three lines of a block-font wordmark (pyfiglet "pagga") painted with a violet→cyan→amber
gradient, over one live waveform strip that ripples left-to-right — a granular grinder should
*look* like it's moving. The wave is two summed sines advanced on a timer; cheap enough to run
over SSH (~8 fps, one thin row).
"""

import math

from rich.console import Group
from rich.text import Text
from textual.widgets import Static

import pyfiglet

from tui.theme import gradient

# Rendered once at import — the wordmark never changes, only its colours are re-applied per frame.
_WORDMARK = [ln for ln in pyfiglet.figlet_format("grainneukeln", font="pagga").split("\n") if ln.strip()]
_MARK_W = max((len(ln) for ln in _WORDMARK), default=1)

_BLOCKS = " ▁▂▃▄▅▆▇█"
_TAGLINE = " ⟩ granular grinder "

_MARK_STOPS = ["#bb9af7", "#7dcfff", "#ff9e64"]          # violet → cyan → amber
_WAVE_STOPS = ["#565f89", "#7dcfff", "#bb9af7", "#7dcfff", "#565f89"]


class Banner(Static):
    """A self-animating masthead. Height is fixed in CSS (wordmark rows + 1 wave row)."""

    def __init__(self):
        super().__init__()
        self._t = 0.0
        self._mark_cols = gradient(_MARK_W, _MARK_STOPS)

    def on_mount(self):
        self.set_interval(0.12, self._tick)

    def _tick(self):
        self._t += 1.0
        self.refresh()

    def render(self):
        lines = [self._paint_mark(row) for row in _WORDMARK]
        lines.append(self._wave(max(self.size.width, len(_TAGLINE) + 1)))
        return Group(*lines)

    def _paint_mark(self, row):
        t = Text(no_wrap=True)
        for i, ch in enumerate(row):
            if ch == " ":
                t.append(" ")
            else:
                t.append(ch, style=self._mark_cols[min(i, _MARK_W - 1)])
        return t

    def _wave(self, width):
        t = Text(no_wrap=True)
        t.append(_TAGLINE, style="italic #565f89")
        n = max(width - len(_TAGLINE), 1)
        cols = gradient(n, _WAVE_STOPS)
        top = len(_BLOCKS) - 1
        for x in range(n):
            v = (math.sin(x * 0.28 + self._t * 0.30) + math.sin(x * 0.13 - self._t * 0.21)) / 2
            idx = int((v + 1) / 2 * top)
            t.append(_BLOCKS[max(0, min(top, idx))], style=cols[x])
        return t
