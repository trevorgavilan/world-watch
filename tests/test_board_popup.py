"""The pop-up card for a picked pin (Trevor, 10 Nov: "all the data we can squeeze into that pop up",
with a link to the source for more): /api/items/<id> on the server, and the card in a real browser.

The store holds the saved real SSN, GDACS, EONET and FIRMS answers of 9 Nov (test_board_map's store).
"""

import json
import unittest

from tests.browser import Browser, find_browser
from tests.helpers import temp_dir
from tests.test_board import HOSTILE, get_json, raw_insert, request, start
from tests.test_board_map import MARKS, NOW, QUAKES, READY, map_store
from worldwatch.item import iso_utc
from worldwatch.board.data import RECORD_FIELDS, RECORD_TEXT, record_fields
from worldwatch.collectors import all_collectors

EXE = find_browser()
CARD = "document.querySelector('#picked')"
BODY = "document.querySelector('#picked-body').textContent"
LOADED = f"{BODY}.includes('Every field the source sent')"


def popup_store():
    """The map's store plus a quake row written straight into SQLite, past make_item's cleaning:
    what a bug or an old row could leave. Its title, summary and record are all hostile."""
    path = map_store()
    at = iso_utc(NOW)
    raw_insert(path, id="h-pop", source="usgs-quakes", channel="hazards", title=HOSTILE, summary=HOSTILE,
               raw=json.dumps({"properties": {"place": HOSTILE, HOSTILE: 1}}), lat=-30.0, lon=-120.0,
               severity="M5.5", url="https://example.org/q", happened_at=at, fetched_at=at, updated_at=at)
    raw_insert(path, id="gone-1", source="a-source-no-longer-run", channel="hazards", lat=1.0, lon=2.0,
               happened_at=at, fetched_at=at, updated_at=at)
    return path


class Record(unittest.TestCase):
    def test_a_geojson_feature_is_flattened_by_name(self):
        raw = json.dumps({"type": "Feature", "properties": {"mag": 5.1, "place": "Oaxaca", "tsunami": False,
                                                            "felt": None, "types": ",origin,"},
                          "geometry": {"coordinates": [-97.1, 16.2, 10]}})
        fields = dict(record_fields(raw))
        self.assertEqual(fields["mag"], "5.1")
        self.assertEqual(fields["place"], "Oaxaca")
        self.assertEqual(fields["tsunami"], "false")
        self.assertNotIn("felt", fields, "an empty value is left out")
        self.assertEqual(fields["geometry.coordinates"], "-97.1, 16.2, 10")

    def test_every_name_and_value_is_capped_and_so_is_the_count(self):
        raw = json.dumps({f"k{i:03d}" + "x" * 200: "v" * 5000 for i in range(500)})
        fields = record_fields(raw)
        self.assertEqual(len(fields), RECORD_FIELDS)
        self.assertTrue(all(len(k) <= 80 and len(v) <= RECORD_TEXT for k, v in fields))

    def test_deep_or_broken_records_never_fail(self):
        deep = {"a": {"b": {"c": {"d": {"e": {"f": 1}}}}}}
        self.assertEqual(len(record_fields(json.dumps(deep))), 1)
        for raw in ("", "{", "null", "[]", "nan", None):
            self.assertIsInstance(record_fields(raw), list, raw)
        self.assertEqual(record_fields('"just text"'), [["value", "just text"]])


class ItemRoute(unittest.TestCase):
    @classmethod
    def setUpClass(cls):
        cls.srv = start(popup_store(), all_collectors(temp_dir()), now=NOW)
        cls.addClassCleanup(cls.srv.server_close)
        cls.addClassCleanup(cls.srv.shutdown)
        cls.gdacs = get_json(cls.srv, "/api/layers/gdacs")["points"]

    def test_an_item_answers_with_everything_we_hold(self):
        point = self.gdacs[0]
        item = get_json(self.srv, "/api/items/" + point["id"])
        for key in ("id", "source", "title", "url", "happened_at", "fetched_at", "severity", "summary", "lat", "lon",
                    "licence", "basis", "kind", "credit", "credit_url", "record"):
            self.assertIn(key, item)
        self.assertEqual(item["title"], point["title"])
        self.assertEqual(item["kind"], "Disaster alerts (GDACS)")
        self.assertTrue(item["credit_url"].startswith("https://"))
        self.assertGreater(len(item["record"]), 10, "GDACS sends a rich record")

    def test_only_a_plain_id_of_a_source_in_the_run_answers(self):
        for path in ("/api/items/nope", "/api/items/..%2Fstore", "/api/items/" + "a" * 65, "/api/items/a%3Cb",
                     "/api/items/", "/api/items/a/b", "/api/items/gone-1"):  # gone-1: a source not in this run
            resp, _ = request(self.srv, path)
            self.assertEqual(resp.status, 404, path)

    def test_hostile_text_goes_out_escaped(self):
        resp, data = request(self.srv, "/api/items/h-pop")
        self.assertEqual(resp.status, 200)
        for raw in (b"<", b">", b"&"):
            self.assertNotIn(raw, data)
        item = json.loads(data)
        self.assertEqual(item["title"], HOSTILE)
        self.assertEqual(item["record"], [["place", HOSTILE], [HOSTILE[:80], "1"]])


@unittest.skipUnless(EXE, "no Edge or Chrome on this machine")
class Card(unittest.TestCase):
    @classmethod
    def setUpClass(cls):
        cls.srv = start(popup_store(), all_collectors(temp_dir()), now=NOW)
        cls.addClassCleanup(cls.srv.server_close)
        cls.addClassCleanup(cls.srv.shutdown)
        cls.url = f"http://127.0.0.1:{cls.srv.server_port}/"
        cls.quakes = get_json(cls.srv, "/api/layers/quakes")["points"]
        cls.qid = {name: p["id"] for name, lat, lon, _ in QUAKES for p in cls.quakes if (p["lat"], p["lon"]) == (lat, lon)}
        cls.b = Browser(EXE)
        cls.addClassCleanup(cls.b.close)

    def setUp(self):
        self.b.size(1280, 800)
        if not self.b.run(f"location.href === {json.dumps(self.url)}"):
            self.b.open(self.url, READY)
        self.b.run("localStorage.clear()")
        self.b.open(self.url, READY)

    def settle(self):
        self.b.run("new Promise((r) => requestAnimationFrame(() => requestAnimationFrame(r)))")

    def mark(self, **match):
        return next(m for m in self.b.run(MARKS) if all(m.get(k) == v for k, v in match.items()))

    def page_xy(self, x, y):
        return self.b.run("(() => { const r = document.querySelector('#map canvas').getBoundingClientRect();"
                          f" return [r.left + {x}, r.top + {y}]; }})()")

    def click_at(self, x, y):
        self.b.mouse("mouseMoved", x, y, buttons=0)
        self.b.mouse("mousePressed", x, y)
        self.b.mouse("mouseReleased", x, y, buttons=0)

    def click(self, mark):
        self.click_at(*self.page_xy(mark["x"], mark["y"]))

    def card_box(self):
        return self.b.run(f"(() => {{ const c = {CARD}.getBoundingClientRect(), s = document.querySelector('#stage')"
                          ".getBoundingClientRect(); return { left: c.left - s.left, top: c.top - s.top, right: c.right - s.left,"
                          " bottom: c.bottom - s.top, w: s.width, h: s.height }; })()")

    def open_big_quake(self):
        pin = self.mark(kind="pin", id=self.qid["q-big"])
        self.click(pin)
        self.b.wait_for(LOADED, timeout=5)
        return pin

    def test_a_click_opens_the_card_with_the_whole_record(self):
        gdacs = self.mark(layer="gdacs")
        self.click(gdacs)
        self.assertFalse(self.b.run(f"{CARD}.hidden"))
        self.b.wait_for(LOADED, timeout=5)
        body = self.b.run(BODY)
        for text in ("Disaster alerts (GDACS)", "Happened:", "Fetched:", "Where:", "Basis: Reported by the source",
                     "Licence:", "Source: GDACS"):
            self.assertIn(text, body)
        links = self.b.run(f"[...{CARD}.querySelectorAll('a')].map((a) => [a.textContent, a.href, a.target, a.rel])")
        texts = [t for t, *_ in links]
        self.assertIn("More details at the source ↗", texts)
        self.assertIn("About this source ↗", texts)
        for _, href, target, rel in links:
            self.assertTrue(href.startswith("https://"), href)
            self.assertEqual(target, "_blank")
            self.assertIn("noopener", rel)
        self.b.run(f"{CARD}.querySelector('details').open = true")
        self.assertGreater(self.b.run(f"{CARD}.querySelectorAll('dt').length"), 10)

    def test_the_card_sits_by_its_pin_and_follows_a_zoom(self):
        pin = self.mark(kind="pin", id="h-pop")  # mid-Pacific: a zoom beside it is never clamped
        self.click(pin)
        self.b.wait_for(LOADED, timeout=5)
        box, map_left = self.card_box(), self.b.run("document.querySelector('#map').offsetLeft")
        x = pin["x"] + map_left
        self.assertTrue(box["left"] >= x + 10 or box["right"] <= x - 10, "beside the pin, not over it")
        self.assertLess(min(abs(box["left"] - x), abs(box["right"] - x)), 20)
        wx, wy = self.page_xy(pin["x"] - 100, pin["y"])  # a wheel notch left of the pin (the card is on its right)
        self.b.call("Input.dispatchMouseEvent", type="mouseWheel", x=wx, y=wy, deltaX=0, deltaY=-100)
        self.settle()
        moved = self.mark(kind="pin", id="h-pop")
        self.assertGreater(abs(moved["x"] - pin["x"]), 10, "the zoom moved the pin")
        box = self.card_box()
        x = moved["x"] + map_left
        self.assertLess(min(abs(box["left"] - x), abs(box["right"] - x)), 20, "it moved with the pin")
        self.assertTrue(0 <= box["left"] and box["right"] <= box["w"] and box["bottom"] <= box["h"], box)

    def test_a_pin_by_the_right_edge_gets_its_card_on_the_left(self):
        self.open_big_quake()
        width = self.b.run("document.querySelector('#stage').clientWidth")
        self.b.run(f"WWPopup.current.place({width - 20}, 300, true)")
        box = self.card_box()
        self.assertLessEqual(box["right"], box["w"] - 20 - 10)
        self.assertGreaterEqual(box["left"], 0)

    def test_it_hides_while_its_pin_is_off_the_map_and_comes_back(self):
        self.open_big_quake()
        self.b.run("document.querySelector('#go-mideast').click()")
        self.settle()
        self.assertTrue(self.b.run(f"{CARD}.hidden"))
        self.b.run("document.querySelector('#go-world').click()")
        self.settle()
        self.assertFalse(self.b.run(f"{CARD}.hidden"))

    def test_it_closes_with_the_cross_escape_or_a_click_on_nothing(self):
        for how in ("cross", "escape", "nothing"):
            with self.subTest(how=how):
                self.open_big_quake()
                if how == "cross":
                    self.b.run("document.querySelector('#picked-close').click()")
                elif how == "escape":
                    self.b.key("Escape", "Escape", 27)
                else:
                    self.click_at(*self.page_xy(*self.b.run("(() => { const p = WWMap.current.at(-55, -100); return [p.x, p.y]; })()")))
                self.assertTrue(self.b.run(f"{CARD}.hidden"), how)
                self.assertEqual(self.b.run(BODY), "")

    def test_source_text_stays_text(self):
        self.click(self.mark(kind="pin", id="h-pop"))
        self.b.wait_for(f"{BODY}.includes('Basis:')", timeout=5)
        self.assertIn(HOSTILE, self.b.run(BODY))
        self.assertEqual(self.b.run(f"{CARD}.querySelectorAll('img, script').length"), 0)

    def test_a_late_answer_never_fills_a_newer_card(self):
        self.b.run("(() => { const real = window.fetch; window.fetch = (u, o) => String(u).startsWith('/api/items/') &&"
                   " !window.__slowDone ? new Promise((r) => setTimeout(() => { window.__slowDone = true; r(real(u, o)); }, 600))"
                   " : real(u, o); })()")
        self.click(self.mark(kind="pin", id=self.qid["q-big"]))
        self.click(self.mark(kind="pin", id="h-pop"))
        self.b.wait_for(f"{BODY}.includes('Basis:')", timeout=5)
        self.b.run("new Promise((r) => setTimeout(r, 900))")
        title = self.b.run(f"{CARD}.querySelector('.title').textContent")
        self.assertEqual(title, HOSTILE, "the first, slower answer was dropped")

    def test_on_the_globe_it_docks_and_back_on_the_map_it_follows(self):
        pin = self.open_big_quake()
        self.b.run("document.querySelector('#view-globe').click()")
        box = self.card_box()
        self.assertFalse(self.b.run(f"{CARD}.hidden"))
        self.assertAlmostEqual(box["right"], box["w"] - 8, delta=2, msg="docked in the top right corner")
        self.b.run("document.querySelector('#view-map').click()")
        self.settle()
        box = self.card_box()
        x = pin["x"] + self.b.run("document.querySelector('#map').offsetLeft")
        self.assertLess(min(abs(box["left"] - x), abs(box["right"] - x)), 20)


if __name__ == "__main__":
    unittest.main()
