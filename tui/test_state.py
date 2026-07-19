import json
import os
import tempfile
import unittest
from tui.state import TrackSpec, SessionState


class TrackSpecTest(unittest.TestCase):
    def test_valid_range(self):
        self.assertTrue(TrackSpec(0, 15000).valid())
        self.assertTrue(TrackSpec(200, 400).valid())

    def test_invalid_range(self):
        self.assertFalse(TrackSpec(400, 200).valid())   # low >= high
        self.assertFalse(TrackSpec(-1, 100).valid())    # negative
        self.assertFalse(TrackSpec(100, 100).valid())   # equal


class SessionStateTest(unittest.TestCase):
    def test_defaults(self):
        s = SessionState()
        self.assertEqual(s.speed, 1.0)
        self.assertEqual(s.window_divider, 2)
        self.assertEqual(len(s.tracks), 1)
        self.assertEqual((s.tracks[0].low, s.tracks[0].high), (0, 15000))

    def test_not_runnable_without_cutter(self):
        ok, reason = SessionState(sample_length_ms=500).is_runnable()
        self.assertFalse(ok)
        self.assertIn("source", reason.lower())

    def test_not_runnable_without_length(self):
        ok, reason = SessionState(cutter=object(), sample_length_ms=0).is_runnable()
        self.assertFalse(ok)
        self.assertIn("length", reason.lower())

    def test_not_runnable_with_bad_track(self):
        ok, reason = SessionState(
            cutter=object(), sample_length_ms=500, tracks=[TrackSpec(400, 200)]
        ).is_runnable()
        self.assertFalse(ok)
        self.assertIn("track", reason.lower())

    def test_runnable(self):
        ok, reason = SessionState(cutter=object(), sample_length_ms=500).is_runnable()
        self.assertTrue(ok)
        self.assertEqual(reason, "")


class SessionStatePersistenceTest(unittest.TestCase):
    """Crash-tolerance contract (operator 2026-07-19: 'don't lose session/data'). Every scalar the
    operator typed must round-trip through JSON. ``cutter`` is the only non-serializable field
    (megabytes of in-memory audio) and must be dropped — ``source_path`` carries its reload key."""

    def test_to_dict_excludes_cutter_and_includes_source_path(self):
        cutter = object()  # not JSON-serializable — must be excluded
        s = SessionState(cutter=cutter, speed=2.5, mode="q", euclid_k=5,
                         sample_length_ms=400, source_path="/tmp/foo.wav")
        d = s.to_dict()
        self.assertNotIn("cutter", d, "cutter (in-memory audio) must never be persisted")
        self.assertEqual(d["speed"], 2.5)
        self.assertEqual(d["mode"], "q")
        self.assertEqual(d["euclid_k"], 5)
        self.assertEqual(d["sample_length_ms"], 400)
        self.assertEqual(d["source_path"], "/tmp/foo.wav")

    def test_tracks_serialize_as_list_of_dicts(self):
        s = SessionState(tracks=[TrackSpec(80, 2000), TrackSpec(2000, 12000)])
        d = s.to_dict()
        self.assertEqual(d["tracks"], [{"low": 80, "high": 2000}, {"low": 2000, "high": 12000}])

    def test_roundtrip_preserves_every_persisted_field(self):
        original = SessionState(
            speed=1.5, sample_speed=0.75, window_divider=6, sample_length_ms=490,
            tracks=[TrackSpec(80, 2000)], output_dir="/tmp/out", mode="poly",
            euclid_k=7, euclid_n=11, streams_spec="4;3", lib_policy="contrast",
            lib_clusters=4, snap=True, swing=66.0, fill=False, fill_gain_db=-3.0,
            wav_export=True, verbose=True, self_feed=True, source_path="/tmp/x.wav",
        )
        restored = SessionState.from_dict(original.to_dict())
        for field in SessionState.SERIAL_FIELDS:
            self.assertEqual(getattr(original, field), getattr(restored, field),
                             f"roundtrip drift on {field}")
        self.assertIsNone(restored.cutter, "cutter must NOT be restored from JSON")

    def test_unknown_keys_ignored_on_load(self):
        """A future field added to SessionState appears in JSONs written by newer code; an older
        binary loading that JSON must not crash on the unknown key."""
        d = {"speed": 2.0, "future_field_we_dont_have_yet": "ignored"}
        s = SessionState.from_dict(d)
        self.assertEqual(s.speed, 2.0)

    def test_missing_fields_default_on_load(self):
        """A field REMOVED from SessionState in a future version is silently absent in old JSONs;
        loading must use the dataclass default rather than crashing."""
        d = {"speed": 2.0}
        s = SessionState.from_dict(d)
        self.assertEqual(s.speed, 2.0)
        self.assertEqual(s.mode, "rw")  # default

    def test_save_load_roundtrip_through_file(self):
        with tempfile.TemporaryDirectory() as td:
            path = os.path.join(td, "session.json")
            original = SessionState(speed=3.0, mode="lib", source_path="/tmp/bar.mp3")
            self.assertTrue(original.save(path))
            restored = SessionState.load(path)
            self.assertIsNotNone(restored)
            self.assertEqual(restored.speed, 3.0)
            self.assertEqual(restored.mode, "lib")
            self.assertEqual(restored.source_path, "/tmp/bar.mp3")

    def test_save_is_atomic_via_temp_rename(self):
        """A crash mid-save must not corrupt the prior session — save writes to .tmp then renames.
        Verified by the absence of a stale .tmp after save returns."""
        with tempfile.TemporaryDirectory() as td:
            path = os.path.join(td, "session.json")
            SessionState(speed=1.0).save(path)
            self.assertFalse(os.path.exists(path + ".tmp"),
                             "save must clean up its .tmp on success (atomic rename)")

    def test_load_returns_none_on_missing_file(self):
        """First-run case: no prior session. None (not a default state) so the caller distinguishes
        'first run' from 'prior session happened to match defaults'."""
        self.assertIsNone(SessionState.load("/nonexistent/grainneukeln-session.json"))

    def test_load_returns_none_on_corrupt_json(self):
        """A truncated/corrupt session file must not crash the TUI on startup."""
        with tempfile.TemporaryDirectory() as td:
            path = os.path.join(td, "broken.json")
            with open(path, "w") as f:
                f.write("{ this is not json")
            self.assertIsNone(SessionState.load(path))

    def test_save_returns_false_on_unwritable_path(self):
        """A write failure (permissions, full disk) must not crash the TUI — return False."""
        s = SessionState()
        self.assertFalse(s.save("/nonexistent/dir/deep/session.json"))

