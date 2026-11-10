"""The Middle East live viewer and console in a real browser (Trevor, 2026-11-09: "a single viewer from the
main console ... arrows to switch from cam to cam ... a new tab with multiple feeds at the same time").

The store holds the saved real oEmbed answers for the cams, the listed news channels, FIRMS's saved
Middle East heat, and hostile rows written straight into SQLite. Each test opens the real page from a
real Board server in headless Edge, with the page's own CSP. YouTube is blocked in the browser, so the
tests read the frames the pages make (address, sandbox, referrer policy) without reaching the internet.
"""

import gzip
import json
import unittest
from datetime import datetime, timezone

from tests.browser import Browser, find_browser
from tests.helpers import fixture, temp_dir
from tests.test_board import HOSTILE, get_json, raw_insert, start
from worldwatch.collectors import all_collectors, firms, live_streams as L
from worldwatch.item import iso_utc
from worldwatch.store import Store

EXE = find_browser()
NOW = datetime(2026, 11, 9, 23, 0, tzinfo=timezone.utc)
N_STREAMS = len(L.VIDEOS) + len(L.CHANNELS) + 1  # the hostile-titled stream has a good link: it shows, as text
SANDBOX = "allow-scripts allow-same-origin allow-presentation allow-popups allow-popups-to-escape-sandbox"
BLOCKED = ["*youtube-nocookie.com*", "*youtube.com*", "*ytimg.com*", "*googlevideo.com*", "*google.com*"]
READY = ("window.WWViewer && WWViewer.current && WWViewer.current.state.entries.length > 0 && "
         "WWMap.current && WWMap.current.marks().some((m) => m.layer === 'live-cams')")
LIVE_READY = "window.WWLive && document.querySelectorAll('#grid .tile').length > 0"
FRAMES = "[...document.querySelectorAll('iframe')].map((f) => ({src: f.src, sandbox: f.getAttribute('sandbox'), " \
         "referrer: f.referrerPolicy, allow: f.getAttribute('allow')}))"


def live_store():
    path = temp_dir() / "worldwatch.sqlite3"
    store = Store(path)
    for s in L.VIDEOS:
        store.save_items(L.CAMS_COLLECTOR.parse(fixture(f"youtube/oembed_{s.video}_2026-11-09.json"), NOW))
    store.save_items(L.list_news(None, NOW))
    store.save_items(firms.MIDEAST_COLLECTOR.parse(
        gzip.decompress(fixture("firms_j1_russia_asia_24h_2026-11-09_mideast.csv.gz")), NOW))
    for source in ("mideast-cams", "mideast-news", "nasa-firms-mideast"):
        store.record_run(source, NOW, NOW, ok=True, n_items=1, error=None, next_due=iso_utc(NOW), fail_count=0)
    store.close()
    # Past make_item, as a bug or an old row could leave them: none may become a frame or a link.
    hostile = dict(source="mideast-cams", channel="world", severity="cam", lat=31.0, lon=35.0,
                   happened_at=iso_utc(NOW), fetched_at=iso_utc(NOW), summary="x · y. z")
    raw_insert(path, id="bad-js", title="js", url="javascript:alert(1)", **hostile)
    raw_insert(path, id="bad-host", title="evil host", url="https://evil.example/watch?v=LMHUcDktP-w", **hostile)
    raw_insert(path, id="bad-suffix", title="suffix", url="https://www.youtube.com/watch?v=LMHUcDktP-w&x=<b>", **hostile)
    raw_insert(path, id="hostile-title", title=HOSTILE, url="https://www.youtube.com/watch?v=AAAAAAAAAAA",
               **{**hostile, "summary": HOSTILE, "severity": "news", "lat": None, "lon": None})
    return path


@unittest.skipUnless(EXE, "no Edge or Chrome on this machine")
class LiveCase(unittest.TestCase):
    @classmethod
    def setUpClass(cls):
        cls.srv = start(live_store(), all_collectors(temp_dir()), now=NOW)
        cls.addClassCleanup(cls.srv.server_close)
        cls.addClassCleanup(cls.srv.shutdown)
        cls.base = f"http://127.0.0.1:{cls.srv.server_port}"
        entries = get_json(cls.srv, "/api/panels/live-cams")["entries"] + get_json(cls.srv, "/api/panels/live-news")["entries"]
        cls.ids = {e["title"]: e["id"] for e in entries}
        cls.b = Browser(EXE)
        cls.addClassCleanup(cls.b.close)
        cls.b.call("Network.enable")
        cls.b.call("Network.setBlockedURLs", urls=BLOCKED)
        cls.b.size(1280, 900)

    def frames(self):
        return self.b.run(FRAMES)


class Viewer(LiveCase):
    def setUp(self):
        self.url = self.base + "/"
        if not self.b.run(f"location.href === {json.dumps(self.url)}"):
            self.b.open(self.url, READY)
        self.b.run("localStorage.clear()")
        self.b.open(self.url, READY)

    def click(self, element_id):
        self.b.run(f"document.getElementById({json.dumps(element_id)}).click()")

    def current_title(self):
        return self.b.run("document.querySelector('#live-title').textContent")

    def test_the_viewer_shows_every_stream_and_nothing_plays_before_a_click(self):
        self.assertFalse(self.b.run("document.querySelector('#live-box').hidden"))
        self.assertEqual(self.b.run("document.querySelector('#live-count').textContent"), f"1 / {N_STREAMS}")
        self.assertEqual(self.current_title(), "Western Wall 1 · Main Plaza")  # cams first, by name
        self.assertEqual(self.frames(), [])  # D-24: no frame, so no request to YouTube, until Play
        self.assertTrue(self.b.run("!!document.querySelector('#live-stage .live-play')"))
        self.assertIn("Live cam · Western Wall Heritage Foundation · Jerusalem · checked",
                      self.b.run("document.querySelector('#live-meta').textContent"))

    def test_play_makes_one_sandboxed_privacy_enhanced_frame(self):
        self.b.run("document.querySelector('#live-stage .live-play').click()")
        (frame,) = self.frames()
        self.assertEqual(frame["src"], "https://www.youtube-nocookie.com/embed/LMHUcDktP-w?autoplay=1&mute=1&playsinline=1&rel=0")
        self.assertEqual(frame["sandbox"], SANDBOX)
        self.assertNotIn("top-navigation", frame["sandbox"])  # the player can never move the Board
        self.assertEqual(frame["referrer"], "strict-origin")  # YouTube is told the origin only

    def test_the_arrows_step_through_the_streams_and_wrap(self):
        self.b.run("document.querySelector('#live-stage .live-play').click()")
        self.click("live-next")
        self.assertEqual(self.current_title(), "Western Wall 2")
        self.assertIn("/embed/gJsZdfSyPrM?autoplay=1", self.frames()[0]["src"])
        self.click("live-prev")
        self.click("live-prev")  # from the first, round to the last: a news channel's live stream
        self.assertEqual(self.b.run("document.querySelector('#live-count').textContent"), f"{N_STREAMS} / {N_STREAMS}")
        self.assertRegex(self.frames()[0]["src"], r"/embed/live_stream\?channel=UC[\w-]{22}&autoplay=1&mute=1")
        self.assertIn("Live news ·", self.b.run("document.querySelector('#live-meta').textContent"))
        self.assertIn("listed", self.b.run("document.querySelector('#live-meta').textContent"))

    def test_before_play_the_arrows_change_the_stream_but_fetch_nothing(self):
        self.click("live-next")
        self.assertEqual(self.current_title(), "Western Wall 2")
        self.assertEqual(self.frames(), [])

    def test_a_refresh_never_reloads_the_playing_frame(self):
        self.b.run("document.querySelector('#live-stage .live-play').click()")
        self.b.run("document.querySelector('#live-stage iframe').__kept = true")
        self.b.run("WWViewer.current.update(WWViewer.current.state.entries.slice())")
        self.assertTrue(self.b.run("document.querySelector('#live-stage iframe').__kept === true"))
        self.assertEqual(len(self.frames()), 1)

    def test_the_stream_on_screen_is_kept_in_this_browser(self):
        self.click("live-next")
        self.b.open(self.url, READY)
        self.assertEqual(self.current_title(), "Western Wall 2")

    def test_hostile_rows_never_become_a_frame_or_a_link(self):
        titles = self.b.run("WWViewer.current.state.entries.map((e) => e.title)")
        for bad in ("js", "evil host", "suffix"):
            self.assertNotIn(bad, titles)
        self.b.run(f"WWViewer.current.show({json.dumps(self.ids[HOSTILE])})")
        self.assertEqual(self.current_title(), HOSTILE)  # as text
        self.assertFalse(self.b.run("!!document.querySelector('#live-box img, #live-box script')"))

    def test_the_console_button_opens_the_console_on_this_stream(self):
        self.b.run("window.__opened = []; window.open = (...a) => { window.__opened.push(a); return null; }")
        self.click("live-next")
        self.click("live-console")
        self.assertEqual(self.b.run("window.__opened"), [[f"/live#{self.ids['Western Wall 2']}", "_blank", "noopener"]])

    def test_a_cam_on_the_map_puts_it_in_the_viewer(self):
        self.click("live-next")  # away from the first cam, so the click has something to change
        self.click("go-mideast")
        self.b.run("new Promise((r) => requestAnimationFrame(() => requestAnimationFrame(r)))")
        mark = self.b.run("WWMap.current.marks().find((m) => m.layer === 'live-cams' && m.kind === 'pin' "
                          "&& m.label === 'LIVE')")
        self.assertIsNotNone(mark)
        self.assertEqual(mark["label"], "LIVE")
        x, y = self.b.run("(() => { const r = document.querySelector('#map canvas').getBoundingClientRect();"
                          f" return [r.left + {mark['x']}, r.top + {mark['y']}]; }})()")
        self.b.mouse("mouseMoved", x, y, buttons=0)
        self.b.mouse("mousePressed", x, y)
        self.b.mouse("mouseReleased", x, y, buttons=0)
        cams = {self.ids[s.name] for s in L.VIDEOS if s.lat is not None}
        self.assertIn(self.b.run("WWViewer.current.state.current"), cams)
        self.assertEqual(self.b.run("document.querySelector('#picked .title').textContent"), self.current_title())

    def test_a_not_verified_stream_says_so_and_has_an_amber_pin(self):
        self.b.run(f"WWViewer.current.show({json.dumps(self.ids['Nablus Live'])})")
        self.assertIn("Live cam · NOT VERIFIED", self.b.run("document.querySelector('#live-meta').textContent"))
        labels = {m["label"] for m in self.b.run("WWMap.current.marks()") if m["layer"] == "live-cams" and m["kind"] == "pin"}
        self.assertEqual(labels, {"LIVE", "LIVE?"})
        titles = self.b.run("WWViewer.current.state.entries.map((e) => e.title)")
        last_official = max(titles.index(s.name) for s in L.VIDEOS + L.CHANNELS if not s.caution)
        first_other = min(titles.index(s.name) for s in L.VIDEOS + L.CHANNELS if s.caution)
        self.assertLess(last_official, first_other)  # official streams first

    def test_the_streams_are_not_shown_again_as_lists(self):
        headings = self.b.run("[...document.querySelectorAll('#panels h2')].map((h) => h.textContent)")
        self.assertFalse([h for h in headings if "live" in h.lower()], headings)

    def test_the_middle_east_button_and_the_heat_layer(self):
        self.click("go-mideast")
        self.b.run("new Promise((r) => requestAnimationFrame(() => requestAnimationFrame(r)))")
        heat = [m for m in self.b.run("WWMap.current.marks()") if m["layer"] == "heat-mideast"]
        self.assertTrue(heat)
        self.assertLessEqual({m["kind"] for m in heat}, {"speck", "cluster"})
        label = self.b.run("[...document.querySelectorAll('#layers label')].map((l) => l.textContent)"
                           ".find((t) => t.includes('Heat'))")
        self.assertIn("not strikes", label)


class Console(LiveCase):
    def open(self, hash_=""):
        self.b.open(self.base + "/api/board", "true")  # a new document each time: a hash alone would not reload
        self.b.open(self.base + "/live" + hash_, LIVE_READY)

    def setUp(self):
        self.open()
        self.b.run("localStorage.clear()")
        self.open()

    def tiles(self):
        return self.b.run("[...document.querySelectorAll('#grid .tile')].map((t) => ({id: t.dataset.stream, "
                          "src: (t.querySelector('iframe') || {}).src, pick: t.querySelector('select').value, "
                          "options: t.querySelectorAll('option').length, "
                          "groups: [...t.querySelectorAll('optgroup')].map((g) => g.label)}))")

    def test_four_players_the_first_plays_by_itself(self):
        tiles = self.tiles()
        self.assertEqual(len(tiles), 4)
        self.assertIn("autoplay=1", tiles[0]["src"])  # YouTube's rule: one autoplaying player at a time
        self.assertTrue(all("autoplay=0" in t["src"] for t in tiles[1:]))
        self.assertEqual(len({t["id"] for t in tiles}), 4)
        for t in tiles:
            self.assertEqual(t["options"], N_STREAMS)
            self.assertEqual(t["groups"], ["Cams", "News", "Not verified"])
        for f in self.frames():
            self.assertEqual(f["sandbox"], SANDBOX)
            self.assertEqual(f["referrer"], "strict-origin")
            self.assertTrue(f["src"].startswith("https://www.youtube-nocookie.com/embed/"))

    def test_the_stream_asked_for_comes_first(self):
        aje = self.ids["Al Jazeera English"]
        self.open("#" + aje)
        tiles = self.tiles()
        self.assertEqual(tiles[0]["id"], aje)
        self.assertIn("/embed/live_stream?channel=UCNye-wNBqNL5ZzHSJj3l8Bg&autoplay=1", tiles[0]["src"])

    def test_nine_at_once_and_the_layout_is_kept(self):
        self.b.run("document.querySelector('[data-layout=\"9\"]').click()")
        self.assertEqual(len(self.tiles()), 9)
        self.open()
        self.assertEqual(len(self.tiles()), 9)
        self.assertEqual(self.b.run("document.querySelector('[data-layout=\"9\"]').getAttribute('aria-pressed')"), "true")

    def test_a_picker_changes_one_tile_and_is_kept(self):
        pal = self.ids["Palestine TV"]
        self.b.run("(() => { const s = document.querySelectorAll('#grid select')[2]; "
                   f"s.value = {json.dumps(pal)}; s.dispatchEvent(new Event('change')); }})()")
        tiles = self.tiles()
        self.assertEqual(tiles[2]["id"], pal)
        self.assertIn("/embed/live_stream?channel=UC1xAKR0vwwrHeorDesok6vw&autoplay=1", tiles[2]["src"])
        self.open()
        self.assertEqual(self.tiles()[2]["id"], pal)

    def test_hostile_rows_are_not_offered_and_titles_stay_text(self):
        texts = self.b.run("[...document.querySelectorAll('#grid option')].map((o) => o.textContent)")
        for bad in ("js", "evil host", "suffix"):
            self.assertNotIn(bad, texts)
        self.assertFalse(self.b.run("!!document.querySelector('#grid img, #grid script')"))

    def test_a_click_on_a_tile_keeps_every_player(self):  # code review: the grid's own click rebuilt them all
        self.b.run("document.querySelectorAll('#grid iframe').forEach((f) => { f.__kept = true; })")
        x, y = self.b.run("(() => { const r = document.querySelectorAll('#grid select')[1].getBoundingClientRect();"
                          " return [r.left + r.width / 2, r.top + r.height / 2]; })()")
        self.b.mouse("mousePressed", x, y)
        self.b.mouse("mouseReleased", x, y, buttons=0)
        self.b.key("Escape", "Escape", 27)
        self.assertTrue(self.b.run("[...document.querySelectorAll('#grid iframe')].every((f) => f.__kept === true)"))
        self.assertEqual(len(self.tiles()), 4)

    def test_a_malformed_address_still_draws_the_grid(self):  # code review: it retried forever
        self.open("#%E0%A4%A")
        self.assertEqual(len(self.tiles()), 4)
        self.assertEqual(self.b.run("document.querySelector('#status').textContent"), "")

    def test_a_stream_that_leaves_the_list_is_not_misnamed(self):  # code review
        gone = self.tiles()[0]["id"]
        self.b.run("(() => { const real = window.fetch; window.fetch = async (u, o) => { const r = await real(u, o);"
                   " const b = await r.json(); b.entries = b.entries.filter((e) => e.id !== " + json.dumps(gone) + ");"
                   " return new Response(JSON.stringify(b), { status: 200 }); }; })()")
        self.b.run("document.querySelector('#grid iframe').__kept = true")
        self.b.run("WWLive.refresh()")
        self.assertEqual(self.b.run("document.querySelector('#grid select').selectedOptions[0].textContent"),
                         "(no longer listed)")
        self.assertTrue(self.b.run("document.querySelector('#grid iframe').__kept === true"))

    def test_a_list_refresh_keeps_the_frames(self):
        self.b.run("document.querySelector('#grid iframe').__kept = true")
        self.b.run("WWLive.refresh()")  # what the 10-minute refresh does: new options, the same frames
        self.assertTrue(self.b.run("document.querySelector('#grid iframe').__kept === true"))
        self.assertEqual(len(self.tiles()), 4)
