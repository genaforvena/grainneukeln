import inspect
import os

from textual import work
from textual.app import ComposeResult
from textual.containers import Horizontal, Vertical
from textual.widgets import Button, Input, Label, OptionList, Select, Static
from textual.widgets.option_list import Option
from textual.message import Message

import youtube.search as yts
from capture import mic


class SourcePanel(Static):
    """Load a source. The load (YouTube download + librosa beat-detection) is SLOW, so it runs on a
    worker thread and streams progress to the status line — the UI never freezes, and the app is told
    to keep Run disabled until a real cutter has actually landed (see app.on_source_panel_loaded).
    That ordering is what makes the old "Loaded: N beats" / "Cannot run: No source loaded" race
    impossible: Run only becomes clickable AFTER the Loaded message has set state.cutter.

    Input is classified on submit:
      - ``http(s)://…``               → any yt_dlp-supported URL (YouTube, **SoundCloud**,
                                        Bandcamp, Vimeo …) — the host is not gated
      - ``/path``, ``./x``, ``*.wav`` → local file
      - anything else                 → free-text YouTube SEARCH for "artist + track"
                                        (search is YouTube-only; paste a URL for other hosts)

    **RECORD** (ctrl+g, or the ● button) is the fourth source and a peer of the other three: the
    room itself. Press to start, press again to stop; the take is measured and then handed to the
    SAME ``load()`` pipeline a file would take, so everything downstream — beat detection, the
    session checkpoint, Run — is unchanged.

    A recorded take is auto-loaded ONLY if it carries signal. A muted, unplugged, or
    already-held mic yields a perfectly well-formed wav full of zeros, and auto-loading that
    would put the operator in front of a Run button that can only produce silence — they would
    blame the grinder. So a SILENT take is kept on disk, named in the status line together with
    whatever process is holding the card, and left for the operator to load by hand if they
    want it anyway. Loud, not blocked.

    A search runs ``youtube.search.search`` (ranked for the operator's intent: the
    official Topic/VEVO upload surfaces as #1 even when a fan cover has 50× the
    views). Results land in an ``OptionList`` with #1 highlighted — Enter loads it,
    ↑↓ picks another, or retype to refine. The picker is hidden until a search
    runs so the panel reads as before for path/URL users.
    """

    class Loaded(Message):
        def __init__(self, cutter):
            self.cutter = cutter
            super().__init__()

    class Loading(Message):
        """Emitted when a load starts — the app disables Run until it resolves."""

    class Failed(Message):
        """A SOURCE failed to load — nothing runnable is left, so the app clears the cutter."""

        def __init__(self, error):
            self.error = error
            super().__init__()

    class TakeRefused(Message):
        """A recording did not become a source (it could not start, or it carried no signal).

        Deliberately NOT ``Failed``: the two are different events and sharing one message made
        pressing REC in a quiet room throw away the file the operator had already loaded, because
        the app's Failed handler clears ``state.cutter`` and disables Run. A refused take leaves
        whatever was loaded exactly as it was."""

        def __init__(self, reason):
            self.reason = reason
            super().__init__()

    # THE RECORDER AND THE PRE-FLIGHT PROBE ARE ONE SEAM, NOT TWO. The probe measures the SYSTEM's
    # default capture path; a caller holding its own recorder is not using that path, so probing it
    # would check a different thing than the one about to record — and refusing on that reading would
    # invent a fault out of an unrelated fact. Binding them in __init__ alone was not enough: four
    # callers swap ``_recorder_factory`` AFTER construction, which left a fake recorder paired with a
    # real probe and refused takes that were never going to touch a sound card. A property keeps the
    # invariant wherever the swap happens, instead of at the one moment someone remembered.
    @property
    def recorder_factory(self):
        return self._recorder_factory

    @recorder_factory.setter
    def recorder_factory(self, factory):
        self._recorder_factory = factory
        self._preflight = mic.probe_device if factory is self._system_recorder_factory else None

    def __init__(self, loader, searcher=None, state=None, recorder_factory=None):
        super().__init__()
        self._loader = loader
        # Injectable so the TUI tests never touch a sound card (and so an operator can pin an
        # exclusive-ALSA recorder on a node where PipeWire is not running).
        self._system_recorder_factory = (
            lambda out_dir, device: mic.MicRecorder(out_dir, device=device))
        self.recorder_factory = recorder_factory or self._system_recorder_factory
        # The pre-flight probes the SYSTEM's default capture path. A caller that supplies its own
        # recorder is by definition not using it, so probing the system device would be checking a
        # different thing than the one about to record — and refusing on THAT would invent a fault
        # out of an unrelated fact. So the probe is bound to the same seam as the recorder: real
        # factory -> real probe, injected factory -> injected (or absent) probe. Not a special case
        # for tests; it is the same object being real or not in both slots at once.

        self._recorder = None
        self._rec_timer = None
        self._rec_device = None
        # Source B (dual-source grinding) lives HERE, next to Source A — it was buried in the Run
        # panel between the series spec and the Uxn row, which is the one place an operator looking
        # for "where do I put the second source" would never look. ``state`` is optional so the
        # existing single-arg constructions in the tests keep working.
        self.state = state
        # ``searcher`` is injectable for tests; the real default calls yt_dlp.
        # Signature: searcher(query) -> list[result-dict] (see youtube.search.search).
        self._searcher = searcher or yts.search
        self.status_text = "No source loaded — enter a file path, a YouTube/SoundCloud URL, or artist + track"
        self._loading = False

    def compose(self) -> ComposeResult:
        with Vertical():
            yield Label("Local path · YouTube/SoundCloud URL · or artist + track → Enter")
            yield Input(placeholder="path/to/audio.wav   |   https://soundcloud.com/…   |   Radiohead - Karma Police",
                        id="source_input")
            yield OptionList(id="source_results")
            with Horizontal(id="record_row"):
                yield Button("● REC", id="record_btn", variant="error")
                yield Select(self._device_options(), id="record_device",
                             allow_blank=False, value="auto")
                yield Label("", id="record_elapsed")
            yield Label(self.status_text, id="source_status")
            yield Label("Source B (optional) — bands tagged B in the tracks panel pull from it")
            yield Input(getattr(self.state, "source2_path", "") if self.state else "",
                        id="source2_path",
                        placeholder="blank = single-source · local file path")

    def on_mount(self):
        self.border_title = "◈ 1 · source"
        self.border_subtitle = "file · url (yt/sc/…) · search · ● rec (ctrl+g)"
        # Picker is hidden until a search populates it. ``display=False`` removes
        # it from layout (no empty box on first run).
        try:
            self.query_one("#source_results", OptionList).styles.display = "none"
        except Exception:
            pass

    def on_input_changed(self, event):
        if event.input.id == "source2_path" and self.state is not None:
            self.state.source2_path = event.value

    def refresh_from_state(self):
        if self.state is None:
            return
        for wid, val in (("source_input", self.state.source_path),
                         ("source2_path", self.state.source2_path)):
            try:
                self.query_one(f"#{wid}", Input).value = val or ""
            except Exception:
                pass

    def on_input_submitted(self, event):
        # ``event.input`` is absent when a test injects a bare {value: …} stub for the primary
        # path; treat that as the source-A input (id source_input), never source2.
        inp = getattr(event, "input", None)
        if getattr(inp, "id", "source_input") == "source2_path":
            # Enter in Source B validates the path instead of falling through to the YouTube
            # search branch below — which would otherwise treat a mistyped local path as a
            # search query and start downloading something unrelated.
            path = (event.value or "").strip()
            if not path:
                self._set_status("Source B cleared — single-source grinding")
            elif os.path.isfile(path):
                self._set_status(f"Source B set → {os.path.basename(path)}")
            else:
                self._set_status(f"Source B: file not found — {path}")
            return
        value = (event.value or "").strip()
        if not value:
            self._set_status("Enter a path, URL, or artist + track, then Enter")
            return
        if yts.is_url(value) or yts.is_local_path(value):
            self._hide_results()
            self.load(value)
        else:
            self._search(value)

    # --- search path ---

    @work(thread=True, exclusive=True, group="search")
    def _search(self, query):
        def stage(text):
            self.app.call_from_thread(self._set_status, text)
        try:
            stage(f"Searching YouTube for “{query}”…")
            # Signature flexibility for tests: 1-arg (query) or 2-arg (query, n).
            try:
                arity = len(inspect.signature(self._searcher).parameters)
            except (TypeError, ValueError):
                arity = 1
            results = self._searcher(query) if arity <= 1 else self._searcher(query, 12)
        except Exception as e:
            self.app.call_from_thread(self._on_search_error, str(e) or e.__class__.__name__)
            return
        self.app.call_from_thread(self._show_results, query, results)

    def _on_search_error(self, err):
        self._set_status(f"Search failed: {err}")
        self.post_message(self.Failed(err or "search error"))

    def _show_results(self, query, results):
        if not results:
            self._set_status(f"No YouTube results for “{query}” — retype to refine")
            self._hide_results()
            return
        ol = self.query_one("#source_results", OptionList)
        ol.clear_options()
        for i, r in enumerate(results, 1):
            ol.add_option(Option(yts.format_result_line(r, idx=i), id=r["url"]))
        ol.styles.display = "block"
        # #1 is the ranker's pick (the official upload, when found). Highlight it
        # so a single Enter proceeds without forcing the operator to arrow down.
        try:
            ol.highlighted = 0
        except Exception:
            pass
        self._set_status(
            f"{len(results)} results for “{query}” — Enter loads #1 · ↑↓ to pick · retype to refine")
        try:
            ol.focus()
        except Exception:
            pass

    def _hide_results(self):
        try:
            ol = self.query_one("#source_results", OptionList)
            ol.clear_options()
            ol.styles.display = "none"
        except Exception:
            pass

    def on_option_list_option_selected(self, event):
        """Enter on a highlighted search result → load that URL through the same
        pipeline as if the operator had pasted it into the Input."""
        url = getattr(event.option, "id", None)
        if not url:
            return
        self._hide_results()
        # Reflect the pick back into the Input so the operator can see what loaded
        # (and Ctrl+L → edit-to-refine works from the chosen URL, not the query).
        try:
            self.query_one("#source_input", Input).value = url
        except Exception:
            pass
        self.load(url)

    # --- load path (unchanged shape; existing tests + app wiring) ---

    def load(self, value):
        value = (value or "").strip()
        if not value:
            self._set_status("Enter a path or URL, then Enter")
            return
        if self._loading:
            self._set_status("Still loading the previous source — one moment…")
            return
        self._loading = True
        self.post_message(self.Loading())
        self._set_status("Loading…")
        self._load_worker(value)

    @work(thread=True, exclusive=True)
    def _load_worker(self, value):
        def stage(text):
            self.app.call_from_thread(self._set_status, text)

        try:
            cutter = self._call_loader(value, stage)
        except Exception as e:  # any load failure keeps the TUI up and legible
            self.app.call_from_thread(self._finish, None, str(e) or e.__class__.__name__)
            return
        self.app.call_from_thread(self._finish, cutter, None)

    def _call_loader(self, value, stage):
        # Back-compat: test loaders are 1-arg (value); the real loader is 2-arg (value, on_stage).
        try:
            arity = len(inspect.signature(self._loader).parameters)
        except (TypeError, ValueError):
            arity = 2
        return self._loader(value, stage) if arity >= 2 else self._loader(value)

    def _finish(self, cutter, err):
        self._loading = False
        if cutter is None:
            self._set_status(f"Load failed: {err}")
            self.post_message(self.Failed(err or "unknown error"))
            return
        beats_attr = getattr(cutter, "beats", None)
        beats = len(beats_attr) if beats_attr is not None else 0   # beats may be a numpy array
        step = getattr(cutter, "step", 0)
        if beats == 0:
            self._set_status("Loaded, but 0 beats — source too steady/silent to latch a pulse")
        else:
            self._set_status(f"✓ Loaded: {beats} beats · default cut {int(step)} ms · ready to grind")
        self.post_message(self.Loaded(cutter))

    # --- record path (live mic as a first-class source) ---

    def _device_options(self):
        """Options for the capture Select. ``auto`` first — it means "let the backend pick", which
        is a different statement from naming a device, and it is the right default on a node whose
        source list changes when another process seizes a card.

        A device already held by a raw-ALSA client is ABSENT from the audio server's list, so it is
        absent here too: the picker cannot offer a device that cannot be opened."""
        options = [("auto (default input)", "auto")]
        try:
            for d in mic.list_devices():
                label = d["id"]
                if d["monitor"]:
                    # A monitor records what this node is PLAYING, not the room. Legitimate — it
                    # is how you grind whatever is coming out of the speakers — but it must never
                    # be mistaken for a mic, so the label says which it is.
                    label = f"⟲ {label}  (what this node plays)"
                options.append((label, d["id"]))
        except Exception:
            pass
        return options

    @property
    def recording(self):
        return self._recorder is not None and self._recorder.recording

    def on_select_changed(self, event):
        if getattr(event.select, "id", None) == "record_device":
            self._rec_device = None if event.value == "auto" else event.value

    def on_button_pressed(self, event):
        if getattr(event.button, "id", None) == "record_btn":
            event.stop()
            self.toggle_record()

    def toggle_record(self):
        """The RECORD button / ctrl+g. Start on the first press, stop on the second."""
        if self.recording:
            self.stop_record()
        else:
            self.start_record()

    def start_record(self):
        if self._loading:
            self._set_status("Still loading a source — one moment…")
            return
        if self.recording:
            return
        out_dir = getattr(self.state, "output_dir", None) or "output"
        # PRE-FLIGHT: refuse a DEAD source before the take, not after it. The panel used to open
        # whatever `default_device()` listed first, record for as long as the operator held it, and
        # only then report "silent — kept, not loaded". On mesh-home the first listed source is the
        # rear jack with nothing in it (measured: peak 3 of 32768), while the live mic's card is held
        # by the room ear's exclusive raw-ALSA grab and is not in the list at all. So the honest
        # answer was knowable in 0.4s and was instead delivered after the whole take was spent.
        # Skipped silently when the probe cannot run (`None`): "we could not look" is not "dead", and
        # refusing on it would invent a fault. Overridable for anyone recording deliberate silence.
        if self._preflight is not None:
            probe = self._preflight(self._rec_device or mic.default_device())
            if probe is not None and probe["dead"]:
                holders = mic.who_holds_capture()
                held = ("; the live capture card is held by "
                        + ", ".join(f"{h['command'].split()[0]}(pid {h['pid']})" for h in holders)
                        ) if holders else ""
                why = (f"Record failed to start: source "
                       f"{self._rec_device or mic.default_device() or 'default'} reads digital "
                       f"silence (peak {probe['peak']}){held} — pick another input before recording")
                self._recorder = None
                self._set_status(why)
                self.post_message(self.TakeRefused(why))
                return
        try:
            recorder = self.recorder_factory(out_dir, self._rec_device)
            path = recorder.start()
        except Exception as e:
            # Never a silent no-op: a RECORD press that does nothing and says nothing is
            # indistinguishable from a recording in progress.
            self._recorder = None
            self._set_status(f"Record failed to start: {e}")
            self.post_message(self.TakeRefused(str(e) or e.__class__.__name__))
            return
        self._recorder = recorder
        self._set_button("■ STOP", "warning")
        self._set_status(f"● Recording via {getattr(recorder, 'backend', '?')} "
                         f"→ {os.path.basename(path or 'take.wav')} — press again to stop")
        self._tick_elapsed()
        try:
            self._rec_timer = self.set_interval(0.25, self._tick_elapsed)
        except Exception:
            self._rec_timer = None

    def stop_record(self):
        recorder = self._recorder
        if recorder is None:
            return
        self._recorder = None
        self._stop_timer()
        self._set_button("● REC", "error")
        try:
            m = recorder.stop()
        except Exception as e:
            self._set_label("record_elapsed", "")
            self._set_status(f"Record failed: {e}")
            self.post_message(self.TakeRefused(str(e) or e.__class__.__name__))
            return
        self._set_label("record_elapsed", f"{m['duration_s']:.1f}s")
        line = mic.describe(m, m.get("holders"))
        if m["silent"] or m["too_short"]:
            # Kept, named, NOT loaded — see the class docstring.
            self._set_status(f"{line} · kept at {m['path']} — type that path + Enter to grind it anyway")
            self.post_message(self.TakeRefused(line))
            return
        self._set_status(f"Recorded {line} — loading…")
        self.load(m["path"])

    def on_unmount(self):
        """Stop an in-flight take when the panel goes away — the panel OWNS the recorder, so this
        is where the shutdown edge belongs. The app's own on_unmount cannot do it: by the time it
        runs, ``query_one(SourcePanel)`` no longer resolves, and the take survived the app (seen
        red, 2026-08-21). The file is kept and NOT auto-loaded: loading spawns a worker thread
        into a UI that is already tearing down."""
        recorder = self._recorder
        self._recorder = None
        self._stop_timer()
        if recorder is None:
            return
        try:
            recorder.stop()
        except Exception:
            try:
                recorder.cancel()
            except Exception:
                pass

    def _tick_elapsed(self):
        if not self.recording:
            self._stop_timer()
            return
        self._set_label("record_elapsed", f"● {self._recorder.elapsed():.1f}s")

    def _stop_timer(self):
        if self._rec_timer is not None:
            try:
                self._rec_timer.stop()
            except Exception:
                pass
            self._rec_timer = None

    def _set_button(self, label, variant):
        try:
            btn = self.query_one("#record_btn", Button)
            btn.label = label
            btn.variant = variant
        except Exception:
            pass

    def _set_label(self, wid, text):
        try:
            self.query_one(f"#{wid}", Label).update(text)
        except Exception:
            pass

    def _set_status(self, text):
        self.status_text = text
        try:
            self.query_one("#source_status", Label).update(text)
        except Exception:
            # Status widget not yet mounted (called before compose). Keep the text
            # so on_mount picks it up.
            pass
