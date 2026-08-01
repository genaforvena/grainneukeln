"""Output-length bound for the rw mixer, and the amc rebuild that used to drop flags (2026-08-01).

Two defects, one render:

1. **rw has no length bound.** ``q``/``poly``/``lib`` all canvas at ``total_ms`` (the source
   length). ``rw`` emits ``n_windows x calculate_step(beats)`` and stops when it runs out of
   windows — and ``calculate_step`` is ``mean(beat POSITIONS)/4``, roughly an EIGHTH OF THE TRACK
   LENGTH rather than any beat quantity. Windows step by one beat, so the render is
   ``n_beats x duration/8`` — QUADRATIC in source duration. On the operator's 254.9s source
   (408 beats, real period 592ms, step 31285ms) w=5 gave 328 windows x 31.3s = **10261s of audio,
   a 2.9-hour render for a 4-minute source (40.3x)**. It never finished: cgroup-OOM-killed at a 9GB
   ceiling and again at 16GB. No memory budget fixes a quadratic. ``target_ms`` (amc ``tl``) is the
   opt-in bound; absent, nothing changes for existing consumers.

2. **``amc`` dropped ``low_memory``.** ``SampleCutter.__init__`` built the first config with
   ``low_memory=self.low_memory``; every ``amc ...`` command then REPLACED it with a fresh
   ``AutoMixerConfig`` that omitted the field, so it fell back to the default False. A render is
   always ``amc <params>`` then ``am``, so ``--low-memory`` was a **no-op on every CLI grind that
   passed an amc string** — it parsed, printed, and did nothing.

   ``test_low_memory_bit_identity`` did not catch it because it builds the config DIRECTLY. The gap
   was never the mixer; it was the rebuild between the flag and the mixer. These tests go through
   ``config_automix`` for exactly that reason.

(pytest-discoverable; collected by ``pytest tests/``.)
"""
import os
import sys

sys.path.insert(0, os.path.join(os.path.dirname(__file__), ".."))
sys.path.insert(0, os.path.dirname(__file__))

from _bit_identity import build_source, build_beats
from automixer.config import AutoMixerConfig, ChannelConfig
from automixer.runner import AutoMixerRunner


def _rw_config(target_ms=None, seed=0):
    return AutoMixerConfig(
        build_source(), build_beats(),
        sample_length=120,
        mode="rw",
        window_divider=4,
        channels_config=[ChannelConfig(0, 15000, bypass=True)],
        seed=seed,
        target_ms=target_ms,
    )


def test_rw_render_length_is_quadratic_in_source_duration():
    """The defect the bound exists to contain, asserted on the length model itself rather than on a
    render (a 3-second fixture is far too short to show it — at that size rw UNDERSHOOTS, which is
    exactly why this went unnoticed until a 4-minute source arrived).

    Hold the beat PERIOD fixed and lengthen the track. The real period is unchanged, so a sane
    per-window emit would be unchanged too — but ``calculate_step`` is ``mean(beat POSITIONS)/4``,
    so it grows linearly with track length, and the render (``n_windows x step``) grows
    QUADRATICALLY. Doubling a track's length should not quadruple its grind.

    If this test goes red because ``calculate_step`` was repaired, that is the real fix landing:
    re-derive the sound lane's expectations, then decide about the bound — do not weaken this.
    """
    import numpy as np
    from automixer.utils import calculate_step, beat_interval
    from automixer.iterators.rolling_window import rolling_window

    period, divider = 500, 4

    def model(n_beats):
        beats = np.arange(1, n_beats + 1) * period
        step = calculate_step(beats)
        windows = sum(1 for _ in rolling_window(beats, divider))
        return beat_interval(beats), step, windows * step

    period_100, step_100, render_100 = model(100)
    period_200, step_200, render_200 = model(200)

    assert period_100 == period_200 == period, "the real beat period must be unchanged by length"
    assert step_200 > 1.9 * step_100, (
        f"per-window emit should track the beat, not the track length "
        f"(step {step_100} -> {step_200} on a 2x longer track at the SAME tempo)"
    )
    assert render_200 > 3.5 * render_100, (
        f"render length is quadratic in source duration: {render_100}ms -> {render_200}ms "
        f"for a 2x longer source"
    )
    # And the absolute consequence: at any real track length the render dwarfs its source.
    src_ms_200 = 200 * period
    assert render_200 > 10 * src_ms_200, (
        f"a {src_ms_200}ms source grinds to {render_200}ms — {render_200 / src_ms_200:.0f}x"
    )


def test_target_ms_bounds_the_render():
    """``target_ms`` caps the output exactly — the last window is trimmed, not merely stopped at."""
    target = 1500
    out = AutoMixerRunner().run(_rw_config(target_ms=target))
    assert len(out) == target, f"expected exactly {target}ms, got {len(out)}ms"


def test_target_ms_trims_rather_than_truncating_early():
    """A bound must FILL its target, not stop short of it. Stopping one window early would also
    satisfy `len(out) <= target`, so assert the exact length against a target that is NOT a whole
    multiple of the per-window emit."""
    unbounded = len(AutoMixerRunner().run(_rw_config(target_ms=None)))
    target = unbounded // 2 + 7  # deliberately not a window boundary
    out = AutoMixerRunner().run(_rw_config(target_ms=target))
    assert len(out) == target, f"expected exactly {target}ms, got {len(out)}ms"


def test_target_ms_is_bit_identical_to_the_unbounded_prefix():
    """Bounding must only CUT — the retained audio has to be the same bytes the unbounded render
    would have produced for that span, or `tl` is a sound change masquerading as a length fix."""
    target = 1500
    unbounded = AutoMixerRunner().run(_rw_config(target_ms=None, seed=7))
    bounded = AutoMixerRunner().run(_rw_config(target_ms=target, seed=7))
    assert bounded.raw_data == unbounded[:target].raw_data, (
        "the bounded render is not a prefix of the unbounded one — `tl` changed the audio, "
        "not just its length"
    )


def test_target_ms_stops_the_work_it_does_not_just_trim_the_result():
    """THE gate for the memory fix, and the one the length assertions above do NOT cover.

    Trimming at the end (``mixed[:target_ms]``) produces the right LENGTH while still grinding every
    window — on the operator's source that is still 2.9 hours of audio built in RAM and then thrown
    away, which is precisely the OOM. Deleting the loop's ``break`` and keeping only the trim leaves
    every other test in this file green (verified by mutation, 2026-08-01), so the saving has to be
    asserted directly: count the grains actually created.
    """
    from automixer.mixers import default_mixer

    calls = {"n": 0}
    real = default_mixer._create_chunk

    def counting(config, window):
        calls["n"] += 1
        return real(config, window)

    default_mixer._create_chunk = counting
    try:
        calls["n"] = 0
        AutoMixerRunner().run(_rw_config(target_ms=None, seed=11))
        unbounded_chunks = calls["n"]

        calls["n"] = 0
        AutoMixerRunner().run(_rw_config(target_ms=600, seed=11))
        bounded_chunks = calls["n"]
    finally:
        default_mixer._create_chunk = real

    assert bounded_chunks < unbounded_chunks / 2, (
        f"the bound trimmed the output but not the WORK: {bounded_chunks} grains created vs "
        f"{unbounded_chunks} unbounded. A bound that still grinds every window still OOMs — "
        "the loop must stop, not just the result get cut."
    )


def test_amc_rebuild_preserves_low_memory():
    """REGRESSION: ``amc <params>`` must not silently drop ``--low-memory``.

    Directly asserts the field on the config the mixer will actually receive, after an amc rebuild.
    """
    from cutter.sample_cut_tool import SampleCutter
    import tempfile

    with tempfile.TemporaryDirectory() as d:
        src_path = os.path.join(d, "src.wav")
        build_source().export(src_path, format="wav")
        cutter = SampleCutter(src_path, d, low_memory=True)
        assert cutter.auto_mixer_config.low_memory is True, "flag lost before any amc command"

        cutter.config_automix("amc l 200 w 4 seed 3")
        assert cutter.auto_mixer_config.low_memory is True, (
            "amc rebuilt AutoMixerConfig without low_memory — the flag is a no-op on every "
            "CLI grind that passes an amc string"
        )


def test_amc_tl_sets_the_target():
    """``tl <seconds>`` and ``tl src`` both reach the config the mixer sees."""
    from cutter.sample_cut_tool import SampleCutter
    import tempfile

    with tempfile.TemporaryDirectory() as d:
        src_path = os.path.join(d, "src.wav")
        build_source().export(src_path, format="wav")
        cutter = SampleCutter(src_path, d)
        assert cutter.auto_mixer_config.target_ms is None, "default must stay unbounded"

        cutter.config_automix("amc l 200 tl 2.5")
        assert cutter.auto_mixer_config.target_ms == 2500

        cutter.config_automix("amc l 200 tl src")
        assert cutter.auto_mixer_config.target_ms == len(cutter.audio)
