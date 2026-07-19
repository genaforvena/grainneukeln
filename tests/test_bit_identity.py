"""Bit-identity contract for the perf optimization pass (2026-07-19).

Every change in this pass MUST preserve byte-identical `AudioSegment.raw_data` for a seeded config,
across all four mixers. The fixtures in ``tests/fixtures/<mode>_seed0.txt`` were captured from the
pre-refactor code (commit the regenerate alongside the first perf change so review sees the
baseline). This test fails on ANY drift, including meta drift (frame_rate/sample_width/channels/
frame_count) — a refactor that resamples or widens sample format is just as much a behaviour change
as one that touches the bytes.

The test is **fail-safe for intent**: an intentional, audible-character-checked blessed change is
made by running ``tests/_bit_identity.py regenerate`` and committing the new fixtures alongside the
code change. CI does NOT auto-regenerate — a silent re-bless would defeat the contract.

(pytest-discoverable: this file uses bare ``assert`` + the module-level ``_bit_identity`` import
below; collected by ``pytest tests/``.)
"""
import os
import sys

# Match the repo convention: every other tests/*.py inserts the repo root onto sys.path so the
# `automixer` / `cutter` packages resolve under pytest without a conftest.py / pyproject stanza.
sys.path.insert(0, os.path.join(os.path.dirname(__file__), ".."))
sys.path.insert(0, os.path.dirname(__file__))

from _bit_identity import each_mode_config, fingerprint, load_fixture
from automixer.runner import AutoMixerRunner


def test_bit_identity_each_mode():
    """Each mode's seeded render must match its committed fixture byte-for-byte — for BOTH the
    BPF-on path (explicit ``c low,high`` channels) and the BPF-off path (the bypass default that
    skips band_pass_filer for the 4-5× speedup). A drift in either path is a contract break."""
    missing = []
    drifted = []
    for bpf in (True, False):
        for label, cfg in each_mode_config(seed=0, bpf=bpf):
            fixture = load_fixture(label)
            if fixture is None:
                missing.append(label)
                continue
            actual = fingerprint(AutoMixerRunner().run(cfg))
            if actual != fixture:
                drifted.append((label, fixture, actual))

    assert not missing, (
        f"missing fixtures for labels {missing} — run "
        f"`PYTHONPATH=. .venv/bin/python tests/_bit_identity.py regenerate` to capture them"
    )
    assert not drifted, (
        "bit-identity drift detected (perf changes must preserve byte-identical seeded output):\n  "
        + "\n  ".join(f"{lab}: expected {exp}\n            got      {act}" for lab, exp, act in drifted)
        + "\n\nIf this drift is INTENTIONAL and audible-character-checked, re-bless via "
        "`PYTHONPATH=. .venv/bin/python tests/_bit_identity.py regenerate` and commit the new "
        "fixtures with the code change. Do NOT re-bless reflexively to make the test pass."
    )
