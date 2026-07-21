import gc
import os
import tempfile
import traceback
from datetime import datetime

from automixer.config import AutoMixerConfig, ChannelConfig, parse_stream_spec
from automixer.runner import AutoMixerRunner
from cutter.sample_cut_tool import normalize_loudness

# Crash-tolerance (operator 2026-07-19: "let it crash, but record what caused it — what setting").
# This is the SINGLE place a grind crash is recorded. The TUI's worker thread catches the
# exception for display, but a crash that takes the process with it (OOM/SIGKILL, segfault) leaves
# NO trace unless we wrote one BEFORE re-raising. Append-only: a stack of crash records, not just
# the last one — the operator scans the recent few for a pattern (e.g. "always l=160 c=100,8000").
from tui.state import CRASH_LOG


def _config_to_recipe(config):
    """One-line human recipe of an AutoMixerConfig — the amc-string equivalent. Written to the
    crash log so the operator can read WHICH setting bombed without grepping a traceback.

    Mode-aware: only emits the params that apply to the active mixer (euclid for q, streams for
    poly, lib-* for lib) so a rw-mode crash doesn't drown the line in irrelevant defaults."""
    cfg = config
    parts = [f"m-{cfg.mode}", f"l{int(cfg.sample_length)}"]
    if cfg.window_divider != 1:
        parts.append(f"w{cfg.window_divider}")
    if cfg.sample_speed != 1.0:
        parts.append(f"ss{cfg.sample_speed}")
    if cfg.speed != 1.0:
        parts.append(f"s{cfg.speed}")
    if cfg.channels_config and any(
        getattr(ch, "low_pass", 0) > 0 or getattr(ch, "high_pass", 25000) < 25000
        for ch in cfg.channels_config
    ):
        parts.append("c" + "_".join(f"{ch.low_pass}-{ch.high_pass}" for ch in cfg.channels_config))
    # mode-scoped params — defaults exist for the others but they don't apply, so suppress them
    # (the operator reads the line for the mixer that actually bombed, not a kitchen-sink dump).
    if cfg.mode == "q":
        if cfg.euclid_k:
            parts.append(f"k{cfg.euclid_k}")
        if cfg.euclid_n:
            parts.append(f"n{cfg.euclid_n}")
        if not cfg.fill:
            parts.append("no-fill")
        if cfg.fill_gain_db != -6.0:
            parts.append(f"filldb{cfg.fill_gain_db}")
    if cfg.mode == "poly" and getattr(cfg, "streams", None):
        parts.append(f"st{cfg.streams}")
    if cfg.mode == "lib":
        parts.append(f"pol-{cfg.lib_policy}")
        parts.append(f"clu{cfg.lib_clusters}")
    # placement effects are mode-composable
    if cfg.snap:
        parts.append("snap")
    if cfg.swing:
        parts.append(f"sw{cfg.swing}")
    if getattr(cfg, "seed", None) is not None:
        parts.append(f"seed{cfg.seed}")
    return " ".join(parts)


def _record_crash(config, source_path, exc_type, exc_msg, tb):
    """Append the recipe + source + traceback to the crash log. Best-effort: a write failure here
    must NOT mask the original exception — wrap in try/except and return silently.

    NOTE: ``beats`` is a numpy array — never ``beats or []`` (ambiguous-truth-value crash on a
    multi-element array). ``len(x) if x is not None else 0`` is the safe form."""
    try:
        os.makedirs(os.path.dirname(CRASH_LOG) or ".", exist_ok=True)
        stamp = datetime.now().strftime("%Y-%m-%dT%H:%M:%S")
        recipe = _config_to_recipe(config)
        tb_text = "".join(traceback.format_exception(exc_type, exc_msg, tb))
        # numpy-safe length reads — getattr returns None if absent, never use `or` on a numpy array.
        audio = getattr(config, "audio", None)
        beats = getattr(config, "beats", None)
        n_audio = len(audio) if audio is not None else 0
        n_beats = len(beats) if beats is not None else 0
        with open(CRASH_LOG, "a") as f:
            f.write(
                f"\n[{stamp}] CRASH\n"
                f"  recipe: {recipe}\n"
                f"  source: {source_path or '(unknown)'}\n"
                f"  audio_samples: {n_audio}\n"
                f"  beats: {n_beats}\n"
                f"  exception: {exc_type.__name__}: {exc_msg}\n"
                f"  traceback:\n{tb_text}\n"
            )
    except Exception:
        pass


def build_config(cutter, state):
    """Map a SessionState onto the existing AutoMixerConfig. DSP untouched."""
    channels = [ChannelConfig(t.low, t.high) for t in state.tracks]
    low_memory = getattr(cutter, "low_memory", False)
    return AutoMixerConfig(
        audio=cutter.audio,
        beats=cutter.beats,
        sample_length=state.sample_length_ms,
        sample_speed=state.sample_speed,
        mode=state.mode,
        speed=state.speed,
        is_verbose_mode_enabled=state.verbose,
        window_divider=state.window_divider,
        channels_config=channels,
        euclid_k=state.euclid_k,
        euclid_n=state.euclid_n,
        streams=parse_stream_spec(state.streams_spec),
        lib_policy=state.lib_policy,
        lib_clusters=state.lib_clusters,
        snap=state.snap,
        swing=state.swing,
        fill=state.fill,
        fill_gain_db=state.fill_gain_db,
        low_memory=low_memory,
    )


def run(config, out_dir, on_progress=None, wav_export=False, source_path="", name_suffix=""):
    """Render one grind and export an audible mp3 (and optionally a WAV alongside).

    Returns the output mp3 path. WAV is written next to the mp3 when ``wav_export`` is set,
    matching the CLI's ``set_wav_enabled`` — the .mp3 is always written, the .wav is the extra.

    ``name_suffix`` is an optional short label appended to the base filename — used by the TUI's
    series runner so each combination's export is distinguishable (e.g. ``..._w2_s0.9.mp3``).
    Empty (the default) preserves the legacy ``grain_cut<N>_<stamp>`` name for single renders.

    Crash contract: if the grind raises, the recipe + source + traceback are appended to
    ``CRASH_LOG`` BEFORE the exception re-raises — so a process-killing OOM or segfault still
    leaves a "what setting caused it" record on disk. The TUI catches the re-raise for display;
    a hard process death leaves the log as the only witness.
    """
    if on_progress:
        on_progress(0.0)
    os.makedirs(out_dir, exist_ok=True)

    try:
        gc.collect()
        mix = AutoMixerRunner().run(config)

        gc.collect()
        mix = normalize_loudness(mix)

        stamp = datetime.now().strftime("%Y%m%d-%H%M%S")
        # When a series suffix is present, embed it in the filename so the operator can correlate
        # output file ↔ recipe at a glance. Sanitize: keep it short and filename-safe.
        safe_suffix = ""
        if name_suffix:
            safe = "".join(c if c.isalnum() or c in "-_." else "_" for c in name_suffix)[:80]
            safe_suffix = f"_{safe}"
        base = f"grain_cut{int(config.sample_length)}{safe_suffix}_{stamp}"
        mp3_path = os.path.join(out_dir, base + ".mp3")
        mix.export(mp3_path, format="mp3")
        if wav_export:
            mix.export(os.path.join(out_dir, base + ".wav"), format="wav")

        del mix
        gc.collect()

        if on_progress:
            on_progress(1.0)
        return mp3_path
    except BaseException as exc:
        # OOM (MemoryError), worker segfault, librosa crash — record the recipe and re-raise so
        # the caller's worker thread sees the real exception and the TUI shows the real error.
        # This is NOT a defensive swallow: it is a side-channel log on the way out.
        _record_crash(
            config, source_path, type(exc), exc,
            (exc.__traceback__ if hasattr(exc, "__traceback__") else None),
        )
        raise

