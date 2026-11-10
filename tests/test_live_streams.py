"""The Middle East watch's sources against their real producers: YouTube's oEmbed answers and FIRMS's
Russia_Asia file, saved on 2026-11-09; and (WW_LIVE=1) the live ones."""

import gzip
import unittest
from datetime import datetime, timezone

from tests.helpers import LIVE, FIXTURES, fixture, temp_dir
from tests.test_runner import FakeFetcher
from worldwatch.collectors import ParseError, all_collectors, firms, live_streams as L
from worldwatch.http import FetchError, Fetcher
from worldwatch.runner import run_source
from worldwatch.store import Store

NOW = datetime(2026, 11, 9, 23, 0, tzinfo=timezone.utc)
MIDEAST_FILE = "firms_j1_russia_asia_24h_2026-11-09_mideast.csv.gz"


def oembed(video):
    return fixture(f"youtube/oembed_{video}_2026-11-09.json")


def saved_answers():
    """{check URL: the saved real oEmbed answer} for every cam on the list."""
    return {s.check_url: oembed(s.video) for s in L.VIDEOS}


def stored(store):
    return {r["title"]: r for r in store.db.execute("SELECT * FROM items")}


class Cams(unittest.TestCase):
    def setUp(self):
        self.items = {}
        for s in L.VIDEOS:
            (item,) = L.CAMS_COLLECTOR.parse(oembed(s.video), NOW)
            self.items[item.title] = item

    def test_every_video_has_a_saved_answer_and_matches_it(self):
        self.assertEqual(len(list((FIXTURES / "youtube").iterdir())), len(L.VIDEOS))
        self.assertEqual(set(self.items), {s.name for s in L.VIDEOS})

    def test_a_cam_is_a_fixed_video_at_its_place(self):
        main = self.items["Western Wall 1 · Main Plaza"]
        self.assertEqual(main.url, "https://www.youtube.com/watch?v=LMHUcDktP-w")
        self.assertEqual(main.severity, "cam")
        self.assertAlmostEqual(main.lat, 31.7767, places=3)
        self.assertAlmostEqual(main.lon, 35.2345, places=3)
        self.assertIn("Western Wall Heritage Foundation · Jerusalem.", main.summary)
        self.assertIn("On YouTube: The Western Wall - Main Plaza", main.summary)  # the owner's own title
        self.assertEqual(main.basis, "reported")

    def test_every_cam_says_its_source_and_both_times(self):  # D-8
        for item in self.items.values():
            self.assertEqual(item.source, "mideast-cams")
            self.assertEqual(item.happened_at, "2026-11-09T23:00:00Z")  # a stream's "when": its last check
            self.assertEqual(item.fetched_at, "2026-11-09T23:00:00Z")
            self.assertTrue(item.licence)

    def test_check_urls_are_youtube_oembed(self):
        urls = L.check_urls(None, NOW)
        self.assertEqual(len(urls), len(L.VIDEOS))
        for url in urls:
            self.assertRegex(url, r"^https://www\.youtube\.com/oembed\?format=json&url="
                                  r"https%3A%2F%2Fwww\.youtube\.com%2Fwatch%3Fv%3D[A-Za-z0-9_-]{11}$")

    def test_an_answer_for_a_video_not_on_the_list_is_refused(self):
        with self.assertRaises(ParseError):
            L.CAMS_COLLECTOR.parse(oembed("LMHUcDktP-w").replace(b"LMHUcDktP-w", b"AAAAAAAAAAA"), NOW)

    def test_only_youtube_oembed_is_read(self):
        for payload in (oembed("LMHUcDktP-w").replace(b'"provider_name":"YouTube"', b'"provider_name":"Vimeo"'),
                        b"[]", b"<html>Not Found</html>", b'{"thumbnail_url": "https://evil.example/vi/LMHUcDktP-w/x.jpg",'
                                                          b' "provider_name": "YouTube"}'):
            with self.subTest(payload=payload[:30]), self.assertRaises(ParseError):
                L.CAMS_COLLECTOR.parse(payload, NOW)


class News(unittest.TestCase):
    def setUp(self):
        self.items = {i.title: i for i in L.list_news(None, NOW)}

    def test_every_channel_is_its_current_live_stream_with_no_place(self):
        self.assertEqual(len(self.items), len(L.CHANNELS))
        aje = self.items["Al Jazeera English"]
        self.assertEqual(aje.url, "https://www.youtube.com/channel/UCNye-wNBqNL5ZzHSJj3l8Bg/live")
        self.assertEqual(aje.severity, "news")
        self.assertIsNone(aje.lat)
        self.assertIn("Doha · Qatar state-funded", aje.summary)

    def test_a_listed_channel_says_it_was_not_checked(self):  # D-8: reported vs inferred
        for item in self.items.values():
            self.assertEqual(item.source, "mideast-news")
            self.assertEqual(item.basis, "inferred")
            self.assertIn("Listed, not checked", item.summary)
            self.assertEqual(item.fetched_at, "2026-11-09T23:00:00Z")

    def test_the_bank_and_the_strip_have_their_broadcasters(self):
        self.assertIn("Ramallah, West Bank", self.items["Palestine TV"].summary)
        self.assertIn("Al Jazeera Arabic", self.items)
        self.assertIn("Bethlehem, West Bank", self.items["Hala Bethlehem TV"].summary)
        self.assertIn("covering Gaza", self.items["Al Ghad"].summary)


class NotVerified(unittest.TestCase):
    """Trevor (2026-11-09): any source, but the ones we can't vouch for say so wherever they show."""

    def items(self):
        cams = [L.CAMS_COLLECTOR.parse(oembed(s.video), NOW)[0] for s in L.VIDEOS]
        return {i.title: i for i in cams + L.list_news(None, NOW)}

    def test_official_and_not_verified_are_told_apart(self):
        items = self.items()
        official = {s.name for s in L.VIDEOS + L.CHANNELS if not s.caution}
        self.assertEqual(len(official), 4 + 13)
        for title, item in items.items():
            if title in official:
                self.assertIn(item.severity, ("cam", "news"))
                self.assertNotIn("Not verified", item.summary)
            else:
                self.assertTrue(item.severity.endswith(" · not verified"), title)
                self.assertIn("Not verified:", item.summary)

    def test_a_not_verified_place_is_still_a_pin(self):
        nablus = self.items()["Nablus Live"]
        self.assertAlmostEqual(nablus.lat, 32.2211, places=3)
        self.assertEqual(nablus.severity, "cam · not verified")
        self.assertIsNone(self.items()["Middle East multi-cam (Intel Cams | OSINT)"].lat)  # a grid has no one place

    def test_the_run_lists_them_without_fetching(self):
        store = Store(temp_dir() / "w.sqlite3")
        fetcher = FakeFetcher()
        result = run_source(store, L.NEWS_COLLECTOR, fetcher, NOW)
        self.assertTrue(result.ok)
        self.assertEqual(fetcher.calls, [])
        self.assertEqual(len(stored(store)), len(L.CHANNELS))
        store.close()


class TheList(unittest.TestCase):
    def test_the_list_is_checked_when_loaded(self):
        good = dict(key="k", name="n", owner="o", home="h")
        bad = [dict(kind="cam", video="LMHUcDktP-w"),  # an official cam with no place
               dict(kind="cam", channel="UCNye-wNBqNL5ZzHSJj3l8Bg", lat=1.0, lon=2.0, caution="x"),  # a cam that isn't fixed
               dict(kind="news", channel="UCNye-wNBqNL5ZzHSJj3l8Bg", lat=1.0, lon=2.0),  # news with a place
               dict(kind="cam", video="LMHUcDktP-w", lat=1.0),  # half a place
               dict(kind="news", video="LMHUcDktP-w", channel="UCNye-wNBqNL5ZzHSJj3l8Bg"),  # both
               dict(kind="news"),  # neither
               dict(kind="radio", channel="UCNye-wNBqNL5ZzHSJj3l8Bg"),
               dict(kind="cam", video="javascript:", lat=1.0, lon=2.0), dict(kind="news", channel="UC<script>")]
        for extra in bad:
            with self.subTest(extra=extra), self.assertRaises(ValueError):
                L.Stream(**good, **extra)
        news = L.Stream(**good, kind="news", channel="UCNye-wNBqNL5ZzHSJj3l8Bg")
        cam = L.Stream(**good, kind="cam", video="LMHUcDktP-w", lat=1.0, lon=2.0)
        for cams, channels in (((), (news, news)), ((news,), ()), ((), (cam,))):
            with self.assertRaises(ValueError):
                L._checked_list(cams, channels)

    def test_registered_the_cams_as_a_layer_and_both_as_panels(self):
        found = {c.source: c for c in all_collectors(temp_dir()) if c.source.startswith("mideast-")}
        self.assertEqual(set(found), {"mideast-cams", "mideast-news"})
        self.assertEqual(found["mideast-cams"].layer.id, "live-cams")
        self.assertEqual(found["mideast-cams"].panel.id, "live-cams")
        self.assertIsNone(found["mideast-news"].layer)
        self.assertEqual(found["mideast-news"].panel.id, "live-news")


class OneCamGone(unittest.TestCase):
    """A cam whose owner turned embedding off (oEmbed 401) or that ended (404) is skipped; the rest count."""

    def run_with(self, broken):
        answers = saved_answers()
        for url in broken:
            answers[url] = FetchError("HTTP 404")
        store = Store(temp_dir() / "w.sqlite3")
        result = run_source(store, L.CAMS_COLLECTOR, FakeFetcher(answers), NOW)
        titles = set(stored(store))
        store.close()
        return result, titles

    def test_all_answer(self):
        result, titles = self.run_with([])
        self.assertTrue(result.ok)
        self.assertEqual(len(titles), len(L.VIDEOS))

    def test_one_gone_is_skipped(self):
        gone = next(s for s in L.VIDEOS if s.key == "kotel-3")
        result, titles = self.run_with([gone.check_url])
        self.assertTrue(result.ok)
        self.assertNotIn(gone.name, titles)
        self.assertEqual(len(titles), len(L.VIDEOS) - 1)

    def test_the_first_check_failing_skips_only_it(self):  # code review: one ended stream sank them all
        result, titles = self.run_with([L.VIDEOS[0].check_url])
        self.assertTrue(result.ok)
        self.assertEqual(len(titles), len(L.VIDEOS) - 1)
        self.assertNotIn(L.VIDEOS[0].name, titles)

    def test_no_check_answering_fails_the_run(self):
        result, titles = self.run_with([s.check_url for s in L.VIDEOS])
        self.assertFalse(result.ok)
        self.assertEqual(titles, set())

    @unittest.skipUnless(LIVE, "set WW_LIVE=1 to hit the live feed")
    def test_live(self):
        store = Store(temp_dir() / "w.sqlite3")
        result = run_source(store, L.CAMS_COLLECTOR, Fetcher(), datetime.now(timezone.utc))
        n = len(stored(store))
        store.close()
        self.assertTrue(result.ok, result.error)
        self.assertGreaterEqual(n, len(L.VIDEOS) - 3)  # a re-stream may end on any day


class FirmsMideast(unittest.TestCase):
    def setUp(self):
        self.payload = gzip.decompress(fixture(MIDEAST_FILE))
        self.items = firms.MIDEAST_COLLECTOR.parse(self.payload, NOW)

    def test_saved_file_keeps_the_middle_east_box_and_confident_detections(self):
        # 7,044 rows saved (the region's rows plus 150 from elsewhere): 1,301 confident ones in the box.
        self.assertEqual(len(self.items), 1301)
        self.assertTrue(all(firms.in_mideast(i.lat, i.lon) for i in self.items))
        rows = firms.decode_csv(self.payload, firms.MIDEAST_SOURCE)
        outside = [r for r in rows if not firms.in_mideast(float(r["latitude"]), float(r["longitude"]))]
        self.assertGreater(len(outside), 150)

    def test_heat_is_never_called_a_strike(self):
        first = self.items[0]
        self.assertEqual(first.source, "nasa-firms-mideast")
        self.assertTrue(first.title.startswith("Heat detected (VIIRS "))
        self.assertIn("a fire, a gas flare, an industrial site or a strike", first.summary)
        self.assertEqual(first.happened_at, "2026-11-08T00:43:00Z")
        for item in self.items:
            self.assertNotRegex(item.title.lower(), r"strike|attack|explosion")

    def test_the_box(self):
        inside = [(31.5, 34.45), (31.9, 35.2), (33.9, 35.5), (35.7, 51.4), (15.4, 44.2), (23.6, 58.4), (30.0, 31.2)]
        outside = [(15.6, 32.5), (15.3, 38.9), (12.6, 37.5), (45.0, 40.0), (30.0, 70.0), (8.0, 45.0), (35.0, 24.0)]
        for lat, lon in inside:  # Gaza, Jerusalem, Beirut, Tehran, Sana'a, Muscat, Cairo
            self.assertTrue(firms.in_mideast(lat, lon), (lat, lon))
        for lat, lon in outside:  # Khartoum, Asmara, Gondar, the Caucasus north, Pakistan, Somalia, Crete
            self.assertFalse(firms.in_mideast(lat, lon), (lat, lon))

    def test_mexico_keeps_its_own_file_and_box(self):
        self.assertEqual(firms.parse_mideast(firms.decode_csv(
            gzip.decompress(fixture("firms_j1_central_america_24h_2026-11-09.csv.gz")), "x"), NOW), [])
        self.assertEqual(firms.parse_records(firms.decode_csv(self.payload, "x"), NOW), [])
        self.assertNotEqual(firms.COLLECTOR.url, firms.MIDEAST_COLLECTOR.url)

    def test_registered_as_its_own_layer(self):
        found = [c for c in all_collectors(temp_dir()) if c.source == "nasa-firms-mideast"]
        self.assertEqual(len(found), 1)
        self.assertEqual(found[0].layer.id, "heat-mideast")
        self.assertIn("not strikes", found[0].layer.en)

    @unittest.skipUnless(LIVE, "set WW_LIVE=1 to hit the live feed")
    def test_live(self):
        items = firms.MIDEAST_COLLECTOR.parse(Fetcher().get(firms.MIDEAST_URL), datetime.now(timezone.utc))
        self.assertGreater(len(items), 0)
