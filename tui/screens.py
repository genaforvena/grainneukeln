"""Modal screens: help and the crash log.

Both were toasts before (``self.notify(...)``), which is the wrong container for either. A toast
truncates (the crash log was cut at 1500 chars — the traceback's tail, i.e. the actual raise site,
was the part thrown away), cannot scroll, and evaporates on a timer while you are still reading it.
Reference material needs a surface you can dwell in and dismiss deliberately.
"""

from textual.app import ComposeResult
from textual.binding import Binding
from textual.containers import VerticalScroll
from textual.screen import ModalScreen
from textual.widgets import Button, Static


class _Modal(ModalScreen):
    BINDINGS = [
        Binding("escape", "dismiss_screen", "Close"),
        Binding("q", "dismiss_screen", "Close"),
    ]

    def __init__(self, title, body, markup=True):
        super().__init__()
        self._title = title
        self._body = body
        # Crash tracebacks are arbitrary text — a stray "[y]" in a repr would raise MarkupError and
        # take the whole modal down. Only the hand-written help opts into markup.
        self._markup = markup

    def compose(self) -> ComposeResult:
        with VerticalScroll(id="modal_body"):
            yield Static(self._body, id="modal_text", markup=self._markup)
        yield Button("Close (Esc)", id="modal_close", variant="primary")

    def on_mount(self):
        self.query_one("#modal_body").border_title = self._title
        self.query_one("#modal_body").focus()

    def on_button_pressed(self, event):
        self.dismiss()

    def action_dismiss_screen(self):
        self.dismiss()


HELP_TEXT = """\
[b]grainneukeln TUI[/b] — a granular grinder. Load a source, shape the grain, press Run.

[b]THE FIVE-SECOND VERSION[/b]
  1. Ctrl+1, type a path / YouTube URL / "artist - track", press Enter.
  2. Ctrl+R.  That's a grind. Everything below is shaping.

[b]KEYS[/b] (no mouse needed)
  [b]Ctrl+1[/b] source    [b]Ctrl+2[/b] params    [b]Ctrl+3[/b] mixer     [b]Ctrl+4[/b] bands
  [b]Ctrl+5[/b] run       [b]Ctrl+6[/b] uxn       [b]Ctrl+O[/b] outputs   [b]Ctrl+E[/b] amc bar
  [b]Ctrl+R[/b] run grind      [b]i[/b] info          [b]F1 / ?[/b] this help
  [b]Ctrl+T[/b] crash log      [b]Ctrl+L[/b] jump to source     [b]q[/b] quit    (Tab also cycles)

  In [b]bands[/b] (Ctrl+4 first): [b]a[/b] add · [b]d[/b] remove · [b]t[/b] source A/B · [b]b[/b] raw⇄filtered · edit + Set
  In [b]outputs[/b] (Ctrl+O first): [b]space[/b] play/pause · [b]s[/b] stop · [b].[/b] ff 10s · [b],[/b] back 10s · [b]g[/b] refresh

[b]THE amc COMMAND BAR (Ctrl+E)[/b] — the CLI's whole vocabulary, typed
  The line above the bar is the live recipe: exactly what Run will render, in the same grammar
  the command line takes. Type a recipe to apply it — the panels move to match. ↑/↓ = history.

    [b]m[/b] rw|q|poly|lib   mixer: random-window · quantized grid · polyrhythmic · library/clusters
    [b]l[/b] <ms> | /N | *N  grain length; /2 /3 *2 transform the CURRENT value (beat-relative)
    [b]w[/b] <1-10>          window divider          [b]s[/b] <0.1-10>   whole-track speed
    [b]ss[/b] <0.1-10>       per-grain speed         [b]c[/b] <bands>    e.g. 0,250;2:900,7000 · "raw"
    [b]ek[/b]/[b]en[/b] <n>          q: euclid E(k,n)        [b]nofill[/b]/[b]fill[/b] · [b]fg[/b] <dB>  q: gap-fill
    [b]pr[/b] <spec>         poly: 4:1-2000;3:6000-15000     [b]lib[/b] sim|con · [b]lk[/b] <n>  lib mixer
    [b]snap[/b]/[b]nosnap[/b] · [b]sw[/b] <%>   placement: snap-to-slot, swing (66 = 2:1 shuffle)
    [b]env[/b] <0-50>        grain attack/release taper %     [b]rv[/b] <0-1>   per-grain reverse chance
    [b]src2[/b] <path>       Source B                [b]seed[/b] <n>     reproducible RNG

  A [b]c[/b] band is a real band-pass FILTER and costs ~27x a raw grind. "c raw" (the default) is the
  fast pass-through. The bands panel says which each row is.

[b]SERIES — render a sweep, not one file[/b]
  Bracket any value, in the amc bar or the Run panel's Series field:
    l \\[/2,/3,/4]            → 3 renders          s \\[0.8:1.2:0.2]   → 3 renders (range start:stop:step)
    l \\[/2,/3] m \\[rw,q]      → 4 renders (cartesian product)
    seed \\[1,2,3,4,5]        → 5 takes of one recipe, different RNG each — the variance pack
  Every combination's label goes in its filename, so file ↔ recipe stays correlatable.

[b]UXN ROM CONTROL (Ctrl+6)[/b] — the sequencer drives the params
  A Uxn ROM emits one amc line per tick and the grinder renders it; the ROM owns [b]l w s c ss m[/b],
  including [b]m[/b] — so a run moves through cutting ALGORITHMS (rw → q → poly → lib, changing every
  4 ticks), not just one algorithm's knobs. Everything the ROM does NOT emit (env, rv, snap, swing,
  euclid, poly/lib settings, seed) is taken from your panels.
  [b]Preview plan[/b] ticks the ROM without rendering — read the whole sequence, and smoke-test a
  hand-written ROM, before spending N grinds on it. Closed-loop feeds each tick a byte measured
  from the source's own rhythm density, so the band choice reacts to the audio.
  Per-track A/B tags and Source B do NOT apply in ROM mode — the ROM writes the band string itself.

[b]OUTPUTS[/b]
  Newest first, with size and age. Space plays; playback is non-blocking and survives navigating.

[b]CRASH-TOLERANCE[/b]
  The session is checkpointed before every grind, so a crash (even an OOM that takes the process)
  loses nothing but the render. Restart restores it. Ctrl+T shows what bombed, with the recipe.
"""


class HelpScreen(_Modal):
    def __init__(self):
        super().__init__("? · help — keys, the amc grammar, series, uxn", HELP_TEXT)


class CrashScreen(_Modal):
    """The full last crash record — recipe, source, and the WHOLE traceback."""

    def __init__(self, text):
        super().__init__("⚠ last crash (Ctrl+T)", text, markup=False)
