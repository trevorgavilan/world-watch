"""The Board's flat map in a real browser (Trevor, 2026-11-09: "actual pins, or cleaner pins").

The store holds Task 4's saved real responses (SSN, GDACS, EONET, FIRMS, all of 9 Nov) plus a few
USGS quakes written for the pin rules, and one near-CDMX alert. Each test opens the real page from a
real Board server in headless Edge, with the page's own CSP, and reads what the map drew from
WWMap.current.marks() (the canvas itself has no DOM to query).
"""

import gzip
import json
import math
import unittest
from datetime import datetime, timezone

from tests.browser import Browser, find_browser
from tests.helpers import fixture, sample_item, temp_dir
from tests.test_board import HOSTILE, get_json, start
from worldwatch.collectors import all_collectors, eonet, firms, gdacs, ssn
from worldwatch.item import iso_utc
from worldwatch.store import Store

EXE = find_browser()
NOW = datetime(2026, 11, 9, 19, 10, tzinfo=timezone.utc)
CDMX = (19.4326, -99.1332)
READY = ("window.WWMap && WWMap.current && document.querySelectorAll('#layers li input').length > 0 && "
         "WWMap.current.marks().some((m) => m.kind === 'cdmx') && WWMap.current.marks().some((m) => m.layer === 'fires')")
MARKS = "new Promise((r) => requestAnimationFrame(() => requestAnimationFrame(() => r(WWMap.current.marks()))))"  # after the next frame
QUAKES = [  # (id, lat, lon, magnitude): the pin starts at M5.0
    ("q-big", 38.3, 142.4, 6.1), ("q-five", -20.0, -70.5, 5.0), ("q-under", 35.0, -118.0, 4.9),
    ("q-small", 10.0, 120.0, 3.0), ("q-hostile", -45.0, -150.0, 4.0),
]


def gz(name):
    return gzip.decompress(fixture(name))


def map_store():
    path = temp_dir() / "worldwatch.sqlite3"
    store = Store(path)
    store.save_items(ssn.COLLECTOR.parse(fixture("ssn_ultimos_2026-11-09.xml"), NOW))
    store.save_items(gdacs.COLLECTOR.parse(gz("gdacs_events4app_2026-11-09.json.gz"), NOW))
    store.save_items(eonet.COLLECTOR.parse(gz("eonet_open_2026-11-09.json.gz"), NOW))
    store.save_items(firms.COLLECTOR.parse(gz("firms_j1_central_america_24h_2026-11-09.csv.gz"), NOW))
    quakes = []
    for n, (qid, lat, lon, mag) in enumerate(QUAKES):
        builder = sample_item(n, source="usgs-quakes", channel="hazards", native_id=qid, happened_at=NOW,
                              fetched_at=NOW, lat=lat, lon=lon, severity=f"M{mag:.1f}",
                              title=HOSTILE if qid == "q-hostile" else f"M {mag} quake {qid}")
        quakes.append(builder)
    store.save_items(quakes)
    alert = sample_item(99, source="near-cdmx", channel="hazards", native_id="ssn/alert-1", happened_at=NOW,
                        fetched_at=NOW, title="M5.6 quake 210 km from CDMX", severity="M5.6")
    store.save_items([alert])
    for source in ("ssn-quakes", "gdacs", "nasa-eonet", "nasa-firms", "usgs-quakes", "near-cdmx"):
        store.record_run(source, NOW, NOW, ok=True, n_items=1, error=None, next_due=iso_utc(NOW), fail_count=0)
    store.close()
    return path


def km_between(a, b):
    lat1, lon1, lat2, lon2 = map(math.radians, (*a, *b))
    h = math.sin((lat2 - lat1) / 2) ** 2 + math.cos(lat1) * math.cos(lat2) * math.sin((lon2 - lon1) / 2) ** 2
    return 2 * 6371.0088 * math.asin(math.sqrt(h))


@unittest.skipUnless(EXE, "no Edge or Chrome on this machine")
class FlatMap(unittest.TestCase):
    @classmethod
    def setUpClass(cls):
        cls.srv = start(map_store(), all_collectors(temp_dir()), now=NOW)
        cls.addClassCleanup(cls.srv.server_close)
        cls.addClassCleanup(cls.srv.shutdown)
        cls.url = f"http://127.0.0.1:{cls.srv.server_port}/"
        cls.points = {layer: get_json(cls.srv, f"/api/layers/{layer}")["points"]
                      for layer in ("quakes", "ssn-quakes", "gdacs", "eonet", "fires")}
        cls.qid = {name: p["id"] for name, lat, lon, _ in QUAKES for p in cls.points["quakes"]
                   if (p["lat"], p["lon"]) == (lat, lon)}  # the store names items by a hash
        cls.b = Browser(EXE)
        cls.addClassCleanup(cls.b.close)

    def setUp(self):
        self.b.size(1280, 800)
        if not self.b.run(f"location.href === {json.dumps(self.url)}"):
            self.b.open(self.url, READY)
        self.b.run("localStorage.clear()")
        self.b.open(self.url, READY)

    def marks(self, **match):
        return [m for m in self.b.run(MARKS) if all(m.get(k) == v for k, v in match.items())]

    def page_xy(self, mark):
        return self.b.run("(() => { const r = document.querySelector('#map canvas').getBoundingClientRect();"
                          f" return [r.left + {mark['x']}, r.top + {mark['y']}]; }})()")

    def click(self, mark):
        x, y = self.page_xy(mark)
        self.b.mouse("mouseMoved", x, y, buttons=0)
        self.b.mouse("mousePressed", x, y)
        self.b.mouse("mouseReleased", x, y, buttons=0)

    def wheel(self, x, y, delta, times=1):
        for _ in range(times):
            self.b.call("Input.dispatchMouseEvent", type="mouseWheel", x=x, y=y, deltaX=0, deltaY=delta)
        self.b.run("new Promise((r) => requestAnimationFrame(() => requestAnimationFrame(r)))")

    def settle(self):
        self.b.run("new Promise((r) => requestAnimationFrame(() => requestAnimationFrame(r)))")

    def view(self):
        return self.b.run("WWMap.current.view()")

    # -- what is drawn -----------------------------------------------------------------------------

    def test_the_map_is_the_first_view_and_the_globe_is_not_even_fetched(self):
        self.assertFalse(self.b.run("document.querySelector('#map').hidden"))
        self.assertTrue(self.b.run("document.querySelector('#globe').hidden"))
        self.assertEqual(self.b.run("document.querySelector('#view-map').getAttribute('aria-pressed')"), "true")
        self.assertFalse(self.b.run("performance.getEntriesByType('resource').some((e) => e.name.includes('globe.gl'))"))
        self.b.wait_for("document.querySelector('#map canvas').dataset.base === 'loaded'")

    def test_every_point_of_every_layer_is_on_the_map(self):
        for layer, points in self.points.items():
            with self.subTest(layer=layer):
                self.assertTrue(points, f"the fixture store has no {layer}")
                drawn = sum(m["n"] for m in self.marks(layer=layer) if m["kind"] != "pin")
                self.assertEqual(drawn, len(points))

    def test_each_layer_has_its_own_shape(self):
        shapes = {"quakes": {"circle"}, "ssn-quakes": {"ring"}, "gdacs": {"triangle"}, "eonet": {"diamond"},
                  "fires": {"speck", "cluster"}}
        for layer, allowed in shapes.items():
            with self.subTest(layer=layer):
                kinds = {m["kind"] for m in self.marks(layer=layer)} - {"pin"}
                self.assertTrue(kinds)
                self.assertLessEqual(kinds, allowed)

    def test_a_point_sits_where_it_happened(self):
        for layer in ("quakes", "ssn-quakes", "eonet"):
            for p in self.points[layer][:5]:
                with self.subTest(layer=layer, id=p["id"]):
                    where = self.b.run(f"WWMap.current.at({p['lat']}, {p['lon']})")
                    mark = next(m for m in self.marks(layer=layer, id=p["id"]) if m["kind"] != "pin")
                    self.assertAlmostEqual(mark["x"], where["x"], delta=0.01)
                    self.assertAlmostEqual(mark["y"], where["y"], delta=0.01)

    def test_quakes_from_m5_get_a_pin_with_their_magnitude(self):
        names = {self.qid[k]: k for k in self.qid}
        pins = {names.get(m["id"]): m for m in self.marks(kind="pin", layer="quakes")}
        self.assertEqual(set(pins), {"q-big", "q-five"}, "M4.9 and smaller stay dots")
        self.assertEqual(pins["q-big"]["label"], "M6.1")
        self.assertEqual(pins["q-five"]["label"], "M5.0")
        where = self.b.run("WWMap.current.at(38.3, 142.4)")
        self.assertAlmostEqual(pins["q-big"]["x"], where["x"], delta=0.01, msg="the pin stands on the quake")
        self.assertLess(pins["q-big"]["y"], where["y"] - 10, "its head is above the spot")
        ssn_pins = {m["id"] for m in self.marks(kind="pin", layer="ssn-quakes")}
        big_ssn = {p["id"] for p in self.points["ssn-quakes"] if float(p["severity"][1:]) >= 5}
        self.assertEqual(ssn_pins, big_ssn)

    def test_gdacs_pins_only_orange_and_red(self):
        levels = {p["id"]: p["severity"].split(" · ")[0] for p in self.points["gdacs"]}
        self.assertIn("Green", levels.values(), "the fixture needs a Green event to prove it stays unpinned")
        pinned = {m["id"] for m in self.marks(kind="pin", layer="gdacs")}
        self.assertEqual(pinned, {i for i, lvl in levels.items() if lvl in ("Orange", "Red")})

    def test_nothing_else_is_pinned(self):
        self.assertFalse(self.marks(kind="pin", layer="eonet"))
        self.assertFalse(self.marks(kind="pin", layer="fires"))

    # -- fires -------------------------------------------------------------------------------------

    def test_fires_merge_into_counted_clusters_when_zoomed_out(self):
        clusters = self.marks(layer="fires", kind="cluster")
        self.assertTrue(clusters, "500 fires at world scale must merge")
        self.assertTrue(all(c["n"] >= 4 for c in clusters), "fewer than 4 stay single specks")
        self.assertLess(len(self.marks(layer="fires")), len(self.points["fires"]) / 5)

    def test_clicking_a_cluster_zooms_into_it_and_fires_split_at_close_range(self):
        before = self.view()["s"]
        biggest = max(self.marks(layer="fires", kind="cluster"), key=lambda c: c["n"])
        self.click(biggest)
        self.settle()
        self.assertAlmostEqual(self.view()["s"], before * 4, delta=0.01)
        self.b.run("WWMap.current.zoom(1000)")
        self.settle()
        self.assertAlmostEqual(self.view()["s"], self.view()["max"], delta=0.01, msg="zoom stops at its limit")
        self.assertFalse(self.marks(layer="fires", kind="cluster"), "at close range every fire is its own speck")

    # -- the near-CDMX mark ------------------------------------------------------------------------

    def test_cdmx_turns_red_with_an_alert_and_shows_it_on_click(self):
        cdmx = self.marks(kind="cdmx")
        self.assertEqual(len(cdmx), 1)
        self.assertEqual(cdmx[0]["n"], 1, "one alert in the near-CDMX panel")
        where = self.b.run(f"WWMap.current.at({CDMX[0]}, {CDMX[1]})")
        self.assertAlmostEqual(cdmx[0]["x"], where["x"], delta=0.01)
        self.click(cdmx[0])
        self.assertIn("210 km from CDMX", self.b.run("document.querySelector('#picked-body').textContent"))
        self.b.run("WWMap.current.setAlerts([])")
        self.settle()
        self.assertEqual(self.marks(kind="cdmx")[0]["n"], 0)

    def test_the_rings_are_true_distances_from_the_zocalo(self):
        for km in (150, 400, 700, 1200):
            ring = self.b.run(f"WWPins.ring(WWPins.CDMX, {km})")
            self.assertGreater(len(ring), 36)
            for p in ring:
                self.assertAlmostEqual(km_between(CDMX, (p["lat"], p["lon"])), km, delta=km * 0.002)
        self.assertEqual(self.b.run("WWPins.CDMX_RINGS_KM"), [150, 400, 700, 1200], "D-22's bands")

    # -- selecting and safety ----------------------------------------------------------------------

    def test_clicking_a_pin_selects_its_point(self):
        pin = self.marks(kind="pin", id=self.qid["q-big"])[0]
        self.click(pin)
        self.assertFalse(self.b.run("document.querySelector('#picked').hidden"))
        self.b.wait_for("document.querySelector('#picked-body').textContent.includes('Basis:')", timeout=5)
        body = self.b.run("document.querySelector('#picked-body').textContent")
        self.assertIn("quake q-big", body)
        self.assertIn("U.S. Geological Survey", body)  # the pop-up card (test_board_popup) names the source

    def test_hover_shows_source_text_as_text(self):
        mark = next(m for m in self.marks(layer="quakes", id=self.qid["q-hostile"]) if m["kind"] == "circle")
        x, y = self.page_xy(mark)
        self.b.mouse("mouseMoved", x, y, buttons=0)
        tip = self.b.run("(() => { const t = document.querySelector('#map .tip');"
                         " return [t.hidden, t.textContent, t.children.length]; })()")
        self.assertFalse(tip[0])
        title = next(p["title"] for p in self.points["quakes"] if p["id"] == self.qid["q-hostile"])
        self.assertIn(title + " · M4.0", tip[1])  # make_item already strips the tags; the rest is still text
        self.assertEqual(tip[2], 0, "never parsed as HTML")
        self.assertEqual(self.b.run("document.querySelectorAll('img, #map script').length"), 0)
        self.b.mouse("mouseMoved", x + 300, y + 300, buttons=0)
        self.assertTrue(self.b.run("document.querySelector('#map .tip').hidden"), "the tip leaves with the pointer")

    def test_impossible_positions_are_never_drawn(self):
        self.b.run("WWMap.current.setLayers([{ id: 'quakes', points: ["
                   "{ id: 'a', lat: 91, lon: 0, weight: 1 }, { id: 'b', lat: 0, lon: 181, weight: 1 },"
                   "{ id: 'c', lat: null, lon: 0, weight: 1 }, { id: 'd', lat: '10', lon: 10, weight: 1 },"
                   "{ id: 'ok', lat: 0, lon: 0, weight: 1 }] }])")
        self.settle()
        self.assertEqual({m["id"] for m in self.marks(layer="quakes")}, {"ok"})

    # -- moving around -----------------------------------------------------------------------------

    def test_a_layer_switched_off_leaves_the_map(self):
        self.b.run("document.querySelector('[data-key=\"layer:gdacs\"]').click()")
        self.settle()
        self.assertFalse(self.marks(layer="gdacs"))
        self.assertTrue(self.marks(layer="eonet"))

    def test_the_wheel_zooms_about_the_pointer_within_limits(self):
        x, y = self.page_xy({"x": 400, "y": 250})
        before = self.view()
        self.wheel(x, y, -100)
        self.assertAlmostEqual(self.view()["s"], before["s"] * 1.25, delta=0.01)
        self.wheel(x, y, 100, times=10)
        self.assertAlmostEqual(self.view()["s"], before["min"], delta=0.01, msg="never smaller than the world")

    def test_the_place_under_the_pointer_stays_put_while_zooming(self):
        self.b.run("document.querySelector('#go-mexico').click()")
        self.settle()
        here = self.b.run(f"WWMap.current.at({CDMX[0]}, {CDMX[1]})")
        x, y = self.page_xy(here)
        self.wheel(x, y, -100)
        again = self.b.run(f"WWMap.current.at({CDMX[0]}, {CDMX[1]})")
        self.assertAlmostEqual(again["x"], here["x"], delta=0.5)
        self.assertAlmostEqual(again["y"], here["y"], delta=0.5)

    def test_dragging_pans_and_the_world_never_leaves_the_frame(self):
        self.b.run("document.querySelector('#go-mexico').click()")
        self.settle()
        here = self.b.run(f"WWMap.current.at({CDMX[0]}, {CDMX[1]})")
        x, y = self.page_xy(here)  # starting on the CDMX mark, which a click would select
        self.b.drag(x, y, x + 120)
        moved = self.b.run(f"WWMap.current.at({CDMX[0]}, {CDMX[1]})")
        self.assertAlmostEqual(moved["x"], here["x"] + 120, delta=2)
        self.assertEqual(self.b.run("document.querySelector('#picked').hidden"), True, "a drag is not a click")
        self.b.run("document.querySelector('#go-world').click()")
        self.settle()
        world = self.b.run("WWMap.current.at(90, -180)")
        self.b.drag(x, y, x + 400)
        self.assertEqual(self.b.run("WWMap.current.at(90, -180)"), world, "the whole world is in view: no panning off it")

    def test_mexico_button_frames_mexico(self):
        self.b.run("document.querySelector('#go-mexico').click()")
        self.settle()
        v = self.view()
        self.assertGreater(v["s"], v["min"] * 3)
        for lat, lon in ((32.5, -117.0), (14.6, -92.2), (21.2, -86.8), CDMX):  # Tijuana, Tapachula, Cancún
            p = self.b.run(f"WWMap.current.at({lat}, {lon})")
            self.assertTrue(0 <= p["x"] <= v["w"] and 0 <= p["y"] <= v["h"], (lat, lon, p))

    # -- the globe, one click away -----------------------------------------------------------------

    def test_the_globe_is_one_click_away_and_remembered(self):
        self.b.run("document.querySelector('#view-globe').click()")
        self.b.wait_for("document.querySelector('#globe canvas') !== null")
        self.assertTrue(self.b.run("document.querySelector('#map').hidden"))
        self.assertTrue(self.b.run("document.querySelector('#map-tools').hidden"))
        self.b.open(self.url, "document.querySelector('#globe canvas') !== null")
        self.assertEqual(self.b.run("document.querySelector('#view-globe').getAttribute('aria-pressed')"), "true")
        self.b.run("document.querySelector('#view-map').click()")
        self.b.open(self.url, READY)
        self.assertFalse(self.b.run("document.querySelector('#map').hidden"))

    def test_junk_in_the_view_setting_means_the_map(self):
        for junk in ("globe2", "", "{}", "MAP"):
            with self.subTest(junk=junk):
                self.b.run(f"localStorage.setItem('ww.board.view', {json.dumps(junk)})")
                self.b.open(self.url, READY)
                self.assertFalse(self.b.run("document.querySelector('#map').hidden"))
                self.assertTrue(self.b.run("document.querySelector('#globe').hidden"))

    def test_each_layer_in_the_list_shows_its_pin_shape(self):
        self.assertEqual(self.b.run("document.querySelectorAll('#layers .swatch').length"),
                         self.b.run("document.querySelectorAll('#layers input').length"))

    def test_back_from_the_globe_in_the_same_page_the_map_fills_its_place(self):
        self.b.run("document.querySelector('#view-globe').click()")
        self.b.wait_for("document.querySelector('#globe canvas') !== null")
        self.b.run("document.querySelector('#view-map').click()")
        self.settle()
        self.assertAlmostEqual(self.b.run("document.querySelector('#map canvas').getBoundingClientRect().width"),
                               self.b.run("document.querySelector('#stage').getBoundingClientRect().width"), delta=1)
        self.assertTrue(self.marks(kind="cdmx"))

    # -- review round: gestures and screens --------------------------------------------------------

    def test_merging_needs_four_fires_in_one_spot(self):
        groups = self.b.run("(() => { const at = (n) => Array.from({ length: n }, (_, i) =>"
                            " ({ x: 100 + i, y: 100, point: { id: 'f' + i } }));"
                            " return [3, 4].map((n) => WWPins.group(at(n), true).map((g) => g.members.length))"
                            ".concat([WWPins.group(at(4), false).map((g) => g.members.length)]); })()")
        self.assertEqual(groups, [[1, 1, 1], [4], [1, 1, 1, 1]])

    def test_a_sideways_swipe_does_not_zoom(self):
        x, y = self.page_xy({"x": 400, "y": 250})
        before = self.view()["s"]
        self.b.call("Input.dispatchMouseEvent", type="mouseWheel", x=x, y=y, deltaX=120, deltaY=0)
        self.settle()
        self.assertEqual(self.view()["s"], before)

    def test_a_screen_with_another_scaling_redraws_sharp(self):
        try:
            self.b.call("Emulation.setDeviceMetricsOverride", width=1280, height=800, deviceScaleFactor=2, mobile=False)
            self.b.run("document.querySelector('#zoom-in').click()")  # any redraw notices the new scaling
            self.b.wait_for("(() => { const c = document.querySelector('#map canvas');"
                            " return c.width === Math.round(c.getBoundingClientRect().width * 2); })()", timeout=5)
        finally:
            self.b.size(1280, 800)


@unittest.skipUnless(EXE, "no Edge or Chrome on this machine")
class FirstLoad(unittest.TestCase):
    """A Board opened before the store can be read tries again in 3 s, with one timer only (the review round)."""

    @classmethod
    def setUpClass(cls):
        cls.db = temp_dir() / "worldwatch.sqlite3"  # not there yet
        cls.srv = start(cls.db, all_collectors(temp_dir()), now=NOW)
        cls.addClassCleanup(cls.srv.server_close)
        cls.addClassCleanup(cls.srv.shutdown)
        cls.b = Browser(EXE)
        cls.addClassCleanup(cls.b.close)

    def test_it_retries_soon_without_stacking_and_recovers(self):
        url = f"http://127.0.0.1:{self.srv.server_port}/"
        # The 60 s refresh every second instead: each failed refresh must not start one more retry chain.
        fast = self.b.before_each_page("const realEvery = window.setInterval; window.setInterval = (f) => realEvery(f, 1000);"
                                       " window.__asked = 0; const realFetch = window.fetch;"
                                       " window.fetch = (u, o) => { if (String(u) === '/api/board') window.__asked += 1;"
                                       " return realFetch(u, o); };")
        try:
            self.b.open(url, "document.querySelector('#status').className === 'error'")
            self.b.run("new Promise((r) => setTimeout(r, 10000))")
            asked = self.b.run("window.__asked")
            self.assertLessEqual(asked, 16, "about 1 + 10 refreshes + 3 retries; stacked retries make 25 or more")
            self.assertGreaterEqual(asked, 12)
        finally:
            self.b.forget_script(fast)
        self.b.open(url, "document.querySelector('#status').className === 'error'")
        map_store_at(self.db)
        self.b.wait_for("document.querySelectorAll('#layers li input').length > 0", timeout=5)


def map_store_at(path):
    """The map's store, copied to `path` (an SQLite backup, never a half-written file)."""
    import sqlite3
    src = sqlite3.connect(map_store())
    dst = sqlite3.connect(path)
    src.backup(dst)
    dst.close()
    src.close()


if __name__ == "__main__":
    unittest.main()
