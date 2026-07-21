"""Offline tests for the YouTube search ranker.

These exercise the *ranking logic* only — no network. ``rank_entries`` takes raw
yt_dlp-shaped dicts and re-orders them, so we synthesize the failure modes the
ranker exists to fix:
  - Topic channel (the canonical official upload) buried under covers
  - VEVO / OAC channels outranking fan uploads with higher view counts
  - "Live" / "Acoustic" / "Remix" versions demoted unless the query asked for them
  - 90-minute compilation / 30-second snippet demoted on duration
  - Query parsing for the operator's likely forms (dash, plus, "by")

The doctrine (CLAUDE.md): a gate you have not seen FAIL is not a gate. Each test
asserts the ranker ACTUALLY moves the right entry to #1 against a deliberately
adversarial ordering — YouTube-relevance-#1 is the wrong answer in every case.
"""
import unittest

import youtube.search as s


def _entry(title, channel="Someone", duration=240, views=100_000, url=None, uploader=None):
    """Build a minimal yt_dlp flat-search entry. ``url`` defaults to a synthesized
    video id so dedup works."""
    if url is None:
        vid_num = abs(hash(title)) % 999999
        url = f"https://www.youtube.com/watch?v=vid{vid_num:06d}"
    return {
        "title": title,
        "channel": channel,
        "uploader": uploader if uploader is not None else channel,
        "duration": duration,
        "view_count": views,
        "url": url,
    }


class ParseQueryTest(unittest.TestCase):
    def test_dash_separator(self):
        self.assertEqual(s.parse_query("Radiohead - Karma Police"),
                         ("Radiohead", "Karma Police"))

    def test_em_dash_pasted_from_youtube_title(self):
        self.assertEqual(s.parse_query("Radiohead — Karma Police"),
                         ("Radiohead", "Karma Police"))

    def test_plus_operator_no_spaces(self):
        self.assertEqual(s.parse_query("radiohead+karma police"),
                         ("radiohead", "karma police"))

    def test_plus_operator_with_spaces(self):
        self.assertEqual(s.parse_query("radiohead + karma police"),
                         ("radiohead", "karma police"))

    def test_by_reversed(self):
        self.assertEqual(s.parse_query("karma police by radiohead"),
                         ("radiohead", "karma police"))

    def test_no_separator_returns_none_artist(self):
        # Whole string becomes the title-match target; no channel bias attempted.
        artist, title = s.parse_query("karma police")
        self.assertIsNone(artist)
        self.assertEqual(title, "karma police")

    def test_empty(self):
        self.assertEqual(s.parse_query(""), (None, None))
        self.assertEqual(s.parse_query("   "), (None, None))


class ClassifyInputTest(unittest.TestCase):
    def test_url_detected(self):
        for u in ("http://x", "https://youtube.com/watch?v=abc",
                  "https://youtu.be/abc"):
            self.assertTrue(s.is_url(u), u)

    def test_path_detected(self):
        for p in ("/tmp/x.wav", "./audio.mp3", "../music/song.flac",
                  "~/song.m4a", "song.ogg", "C:/x.mp3"):
            self.assertTrue(s.is_local_path(p), p)

    def test_query_not_misclassified(self):
        # The whole point: free-text artist+track must NOT be treated as a path.
        for q in ("Radiohead Karma Police", "radiohead - karma police",
                  "karma police", "radiohead+karma police"):
            self.assertFalse(s.is_url(q), q)
            self.assertFalse(s.is_local_path(q), q)


class RankerTest(unittest.TestCase):
    def _top(self, entries, query):
        return s.rank_entries(entries, query)[0]

    def test_topic_channel_beats_higher_view_cover(self):
        """The canonical case. A Topic-channel studio upload must surface as #1
        even when a fan cover with 50× the views sits at YouTube-relevance #1."""
        query = "Radiohead - Karma Police"
        cover = _entry("Radiohead - Karma Police (COVER)",
                       channel="Fan Covers", duration=240, views=5_000_000)
        topic = _entry("Karma Police",
                       channel="Radiohead - Topic", duration=262, views=120_000)
        # YouTube-relevance order: cover first.
        top = self._top([cover, topic], query)
        self.assertIn("Topic", top["channel"], "Topic channel should win")
        self.assertNotIn("COVER", top["title"].upper())

    def test_vevo_beats_unofficial_with_more_views(self):
        query = "Adele - Hello"
        unofficial = _entry("Adele - Hello (Official Music Video)",
                            channel="SomeChannel", duration=360, views=10_000_000)
        vevo = _entry("Adele - Hello",
                      channel="AdeleVEVO", duration=366, views=8_000_000)
        top = self._top([unofficial, vevo], query)
        self.assertIn("VEVO", top["channel"])

    def test_exact_title_match_beats_loose_match(self):
        query = "Daft Punk - Get Lucky"
        wrong = _entry("Daft Punk - Get Lucky (Full Album Stream)",
                       channel="Fan Upload", duration=3600, views=2_000_000)
        right = _entry("Daft Punk - Get Lucky",
                       channel="DaftPunkVEVO", duration=248, views=500_000)
        top = self._top([wrong, right], query)
        self.assertEqual(top["title"], "Daft Punk - Get Lucky")

    def test_cover_demoted_even_without_topic_in_results(self):
        """When the official upload is absent, the ranker still shouldn't surface
        a cover as #1 if a non-cover alternative exists."""
        query = "Pixies - Where Is My Mind"
        cover = _entry("Where Is My Mind - Pixies (Acoustic Cover)",
                       channel="Cover Artist", duration=240, views=900_000)
        alt = _entry("Pixies - Where Is My Mind (Album Version)",
                     channel="Pixies", duration=233, views=400_000)
        top = self._top([cover, alt], query)
        self.assertNotIn("Cover", top["title"])

    def test_remix_demoted_unless_query_asks_for_it(self):
        query = "Daft Punk - Around the World"
        remix = _entry("Daft Punk - Around the World (50 Min Remix)",
                       channel="Remixer", duration=3000, views=4_000_000)
        original = _entry("Around the World",
                          channel="Daft Punk - Topic", duration=426, views=80_000)
        top = self._top([remix, original], query)
        self.assertNotIn("Remix", top["title"])

        # …but when the operator types "remix", the remix is NOT demoted.
        q2 = "Daft Punk - Around the World remix"
        # Rebuild the remix with a higher title similarity to the query.
        remix2 = _entry("Daft Punk - Around the World (Remix)",
                        channel="Remixer", duration=300, views=4_000_000)
        original2 = _entry("Around the World",
                           channel="Daft Punk - Topic", duration=426, views=80_000)
        top2 = self._top([original2, remix2], q2)
        # Both have strong title matches now; "remix" is no longer penalized so
        # the much-higher view count is free to push the remix to the top.
        self.assertIn("Remix", top2["title"])

    def test_live_demoted(self):
        query = "Pink Floyd - Wish You Were Here"
        live = _entry("Pink Floyd - Wish You Were Here (Live 1994)",
                      channel="Concert Footage", duration=420, views=3_000_000)
        studio = _entry("Wish You Were Here",
                        channel="Pink Floyd - Topic", duration=334, views=150_000)
        top = self._top([live, studio], query)
        self.assertNotIn("Live", top["title"])

    def test_short_duration_demoted(self):
        """A 20-second preview/snippet is almost never what the operator wants."""
        query = "Metallica - Enter Sandman"
        snippet = _entry("Metallica - Enter Sandman (Preview)",
                         channel="Metallica", duration=18, views=1_000_000)
        full = _entry("Enter Sandman",
                      channel="Metallica - Topic", duration=332, views=900_000)
        top = self._top([snippet, full], query)
        self.assertNotIn("Preview", top["title"])

    def test_long_compilation_demoted(self):
        """A 90-minute 'best of' compilation is not the track."""
        query = "Queen - Bohemian Rhapsody"
        comp = _entry("Queen - Best Of (Full Album)",
                      channel="Queen Official", duration=5400, views=8_000_000)
        track = _entry("Bohemian Rhapsody",
                       channel="Queen - Topic", duration=354, views=2_000_000)
        top = self._top([comp, track], query)
        self.assertEqual(top["title"], "Bohemian Rhapsody")

    def test_dedup_by_video_id(self):
        """The same video can appear twice in a search (e.g. once as youtu.be,
        once as watch?v=). Dedup must collapse them so the picker doesn't show
        the same upload twice."""
        query = "Radiohead - Karma Police"
        e1 = _entry("Karma Police", channel="Radiohead - Topic",
                    url="https://www.youtube.com/watch?v=ABCD1234")
        e2 = _entry("Karma Police", channel="Radiohead - Topic",
                    url="https://youtu.be/ABCD1234")
        results = s.rank_entries([e1, e2], query)
        self.assertEqual(len(results), 1)

    def test_empty_and_noisy_input(self):
        # Empty query, no results — never raises on the ranker.
        self.assertEqual(s.rank_entries([], "anything"), [])
        # Entries with missing fields don't crash the scorer.
        sparse = [{"title": "x", "url": "https://www.youtube.com/watch?v=zzz"}]
        r = s.rank_entries(sparse, "artist - title")
        self.assertEqual(len(r), 1)

    def test_query_without_dash_still_finds_canonical(self):
        """Operator types just words. No artist separator → no channel bias, but
        title similarity alone should still bring the matching track to the top
        over irrelevant stuff."""
        query = "karma police"
        irrelevant = _entry("Radiohead Live Full Concert",
                            channel="Concerts", duration=5400, views=5_000_000)
        right = _entry("Radiohead - Karma Police",
                       channel="Radiohead", duration=262, views=400_000)
        top = self._top([irrelevant, right], query)
        self.assertIn("Karma Police", top["title"])

    def test_fan_lyrics_upload_demoted_below_official_channel(self):
        """Regression (verified against live YouTube 2026-07-19): a fan upload
        titled "<Artist> - <Track> lyrics" was outranking the Official Video on
        the artist's own channel, because the standalone word 'lyrics' wasn't in
        the negative-keyword list (only the multi-word 'lyric video' / 'with
        lyrics' forms were). A grinder wants the studio track, not a fan lyrics
        video — the official channel must win."""
        query = "Massive Attack Teardrop"
        fan_lyrics = _entry("Massive Attack - Teardrop lyrics",
                            channel="KuroMizunoAriana", duration=278, views=2_500_000)
        official = _entry("Massive Attack - Teardrop (Official Video)",
                          channel="Massive Attack", duration=285, views=116_700_000)
        top = self._top([fan_lyrics, official], query)
        self.assertIn("Official Video", top["title"],
                      "fan 'lyrics' upload must not outrank the official channel upload")


if __name__ == "__main__":
    unittest.main()
