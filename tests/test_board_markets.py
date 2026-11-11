"""Task 5 — the markets terminal (/markets) and its read-only routes (/api/markets, /api/markets/series/<id>),
on the server and in a real browser. The store holds the saved real CoinGecko, Fed and Twelve Data
answers, a few FIX, rate and yield days, a hostile statement written straight into SQLite, Trevor's
lines and a practice ledger."""

import json
import unittest
from datetime import timedelta

from tests.browser import Browser, find_browser
from tests.helpers import fixture, temp_dir
from tests.test_board import HOSTILE, get_json, raw_insert, request, start
from tests.test_markets import NOW, day, obs
from worldwatch.board.server import CSP
from worldwatch.collectors import all_collectors, coingecko, fed_press, history, peso_alert
from worldwatch.item import iso_utc
from worldwatch.markets import paper
from worldwatch.store import Store

EXE = find_browser()
READY = ("document.querySelectorAll('#list .row').length > 0 && document.querySelector('#stats').childElementCount > 0 "
         "&& document.querySelector('#chart svg, #chart .empty:not(.loading)') !== null")


def markets_store():
    base = temp_dir()
    path = base / "worldwatch.sqlite3"
    (base / "markets.txt").write_text("peso above 18.50\nwatch NVDA\nwhat is this\n", encoding="utf-8")
    store = Store(path)
    store.save_items(coingecko.COLLECTOR.parse(fixture("coingecko_simple_price_2026-11-10.json"), NOW))
    store.save_items(fed_press.COLLECTOR.parse(fixture("fed_press_monetary_2026-11-10.xml"), NOW))
    url = f"{history.BASE}?symbol=BTC/MXN,SOL/USD&interval=1day"
    store.save_items(history.collector(base / "markets.txt").parse(
        fixture("twelvedata_time_series_crypto_2026-11-11.json"), NOW, url))
    store.save_items([obs("usd-mxn-fix", "18.5000", day(5)), obs("usd-mxn-fix", "18.6226", day(6)),
                      obs("mx-target", "6.50", day(4)), obs("mx-target", "6.25", day(5)),
                      obs("amx", "20.00", NOW - timedelta(hours=1)), obs("vix", "17.20", day(6)),
                      obs("ust-2y", "3.90", NOW - timedelta(days=40)), obs("ust-2y", "3.70", day(6)),
                      obs("ust-10y", "4.60", NOW - timedelta(days=40)), obs("ust-10y", "4.86", day(6))])
    book = paper.trade(paper.empty(), store, "buy", "amx", "10", NOW)
    paper.save(base / "paper.json", book)
    store.save_items(peso_alert.derive(store, NOW, base / "markets.txt"))
    store.record_run("fred", NOW, NOW, ok=False, n_items=0, error="needs WW_FRED_KEY (a Windows user environment "
                     "variable Trevor creates)", next_due=iso_utc(NOW), fail_count=0)
    store.close()
    at = iso_utc(NOW)
    raw_insert(path, id="h-fed", source="fed-press", channel="markets", title=HOSTILE, summary=HOSTILE,
               url="javascript:alert(3)", happened_at=at, fetched_at=at, updated_at=at)
    return path


class Route(unittest.TestCase):
    @classmethod
    def setUpClass(cls):
        path = markets_store()
        cls.srv = start(path, all_collectors(path.parent), now=NOW)
        cls.addClassCleanup(cls.srv.server_close)
        cls.addClassCleanup(cls.srv.shutdown)
        cls.body = get_json(cls.srv, "/api/markets")

    def test_the_page_is_served_with_the_plain_policy_no_frames(self):
        resp, data = request(self.srv, "/markets")
        self.assertEqual(resp.status, 200)
        self.assertEqual(resp.getheader("Content-Security-Policy"), CSP)
        self.assertNotIn("frame-src", resp.getheader("Content-Security-Policy"))
        for script in (b"markets.js", b"mk_list.js", b"mk_chart.js", b"mk_panels.js"):
            self.assertIn(b"/static/" + script, data)
            self.assertEqual(request(self.srv, "/static/" + script.decode())[0].status, 200)
        self.assertNotIn(b"<script>", data)  # no inline script
        self.assertNotIn(b"style=", data)    # no inline style either

    def test_the_routes_never_write(self):
        for path in ("/api/markets", "/api/markets/series/usd-mxn-fix"):
            self.assertEqual(request(self.srv, path, method="POST", body=b"{}")[0].status, 405)

    def test_the_answer_has_the_numbers_lines_alerts_calendar_ledger_and_sources(self):
        b = self.body
        self.assertEqual(b["groups"][0]["id"], "peso")
        fix = b["groups"][0]["items"][0]
        self.assertEqual((fix["id"], fix["latest"]["value"]), ("usd-mxn-fix", "18.6226"))
        self.assertEqual(b["lines"], ["peso above 18.50"])
        self.assertEqual(b["watch"], ["NVDA"])
        self.assertEqual(b["problems"], ["line 3: not understood"])
        self.assertEqual(len(b["alerts"]), 1)
        self.assertEqual(b["alerts"][0]["basis"], "inferred")
        self.assertTrue(any(c["source"] == "fed" for c in b["calendar"]))
        self.assertEqual(b["paper"]["holdings"][0]["id"], "amx")
        self.assertEqual(b["paper"]["recent"][0]["by"], "you")
        self.assertEqual(len(b["glossary"]), 17)
        self.assertIn("not investment advice", b["disclaimer_en"])
        self.assertIn("twelvedata-history", {s["source"] for s in b["sources"]})

    def test_the_us_curve_compares_today_with_a_month_before(self):
        us = next(c for c in self.body["curves"] if c["id"] == "us")
        self.assertEqual([p["id"] for p in us["points"]], ["ust-2y", "ust-10y"])
        two = us["points"][0]
        self.assertEqual((two["value"], two["before"]), (3.70, 3.90))
        self.assertEqual(two["at"], "2026-11-06T00:00:00Z")

    def test_a_series_holds_the_hourly_price_and_its_daily_history(self):
        btc = get_json(self.srv, "/api/markets/series/bitcoin-mxn")
        self.assertGreater(len(btc["points"]), 300)  # a year of Twelve Data's days, then CoinGecko's hour
        self.assertEqual(btc["points"], sorted(btc["points"]))
        self.assertIn("Twelve Data", btc["note"])
        for bad in ("nope", "usd-mxn-fix'--", "x" * 60, "..%2F..%2Fetc"):
            self.assertEqual(request(self.srv, "/api/markets/series/" + bad)[0].status, 404, bad)

    def test_every_number_names_its_source_page_and_delay(self):
        for g in self.body["groups"]:
            for item in g["items"]:
                self.assertTrue(item["page"].startswith("https://"), item["id"])
                self.assertTrue(item["delay_en"] and item["delay_es"], item["id"])

    def test_no_advice_words_anywhere_in_the_answer(self):
        text = json.dumps(self.body).lower()
        for word in ("you should", "we recommend", "strong buy", "buy now", "sell now", "price target",
                     "guaranteed", "deberías", "recomendamos", "compra ahora"):
            self.assertNotIn(word, text)


@unittest.skipUnless(EXE, "no Edge or Chrome on this machine")
class Terminal(unittest.TestCase):
    @classmethod
    def setUpClass(cls):
        path = markets_store()
        cls.srv = start(path, all_collectors(path.parent), now=NOW)
        cls.addClassCleanup(cls.srv.server_close)
        cls.addClassCleanup(cls.srv.shutdown)
        cls.url = f"http://127.0.0.1:{cls.srv.server_port}/markets"
        cls.b = Browser(EXE)
        cls.addClassCleanup(cls.b.close)

    def setUp(self):
        self.b.size(1440, 1000)
        if not self.b.run(f"location.href === {json.dumps(self.url)}"):
            self.b.open(self.url, READY)
        self.b.run("localStorage.clear()")
        self.b.open(self.url, READY)

    def text(self, selector):
        return self.b.run(f"document.querySelector({json.dumps(selector)}).textContent")

    def pick(self, inst_id):
        self.b.run(f"WWM.pick({json.dumps(inst_id)})")
        self.b.wait_for(f"document.querySelector('#pick-name').textContent === WWM.state.items[{json.dumps(inst_id)}].en")

    def test_the_picked_number_shows_value_change_both_times_source_and_delayed(self):
        stats = self.text("#stats")
        self.assertIn("18.6226 MXN per USD", stats)
        self.assertIn("▲ +0.66%", stats)
        self.assertIn("since Thu, 05 Nov 2026", stats)
        self.assertIn("ForFri, 06 Nov 2026", stats)  # <dt>For</dt><dd>Fri, 06 Nov 2026</dd>
        self.assertIn("Delayed", stats)
        self.assertIn("banxico-peso", stats)
        self.pick("mx-target")
        self.assertIn("▼ −0.25 pp", self.text("#stats"))
        self.pick("sp500")
        self.assertIn("No number yet — needs WW_FRED_KEY", self.text("#stats"))

    def test_every_picked_number_carries_the_delayed_tag(self):
        ids = self.b.run("WWM.state.order.filter((id) => WWM.state.items[id].latest)")
        for inst_id in ids:
            self.pick(inst_id)
            self.assertEqual(self.b.run("document.querySelector('#stats .tag').textContent"), "Delayed", inst_id)

    def test_a_copyrighted_series_keeps_its_owners_notice(self):
        self.pick("vix")
        self.assertIn("Chicago Board Options Exchange, Inc. Reprinted with permission. Personal use only.", self.text("#stats"))

    def test_the_list_rows_and_tabs(self):
        self.assertIn("18.6226", self.text("#list .row[data-id='usd-mxn-fix']"))
        self.b.run("document.querySelector(\"[data-tab='crypto']\").click()")
        self.assertIn("74,732.77", self.text("#list .row[data-id='bitcoin-usd']"))
        self.b.run("document.querySelector(\"[data-tab='rates']\").click()")
        self.assertIn("▼ −0.25 pp", self.text("#list .row[data-id='mx-target']"))

    def test_a_star_puts_a_number_on_the_strip_and_is_remembered(self):
        self.assertNotIn("Solana (USD)", self.text("#strip"))
        self.pick("solana-usd")
        self.b.run("document.querySelector('#star').click()")
        self.assertIn("Solana (USD)", self.text("#strip"))
        self.b.open(self.url, READY)
        self.assertIn("Solana (USD)", self.text("#strip"))
        self.assertEqual(self.text("#pick-name"), "Solana (USD)")

    def test_arrow_keys_move_through_the_list_and_number_keys_pick_the_range(self):
        self.b.key("ArrowDown", "ArrowDown", 40)
        self.b.wait_for("document.querySelector('#pick-name').textContent === 'US dollar in pesos (New York noon)'")
        self.b.key("2", "Digit2", 50)
        self.assertEqual(self.b.run("document.querySelector(\"[data-range='30']\").getAttribute('aria-pressed')"), "true")

    def test_the_chart_draws_a_years_history_and_names_it(self):
        self.pick("bitcoin-mxn")
        self.b.wait_for("document.querySelector('#chart polyline.line') !== null && "
                        "document.querySelector('#chart polyline.line').getAttribute('points').split(' ').length > 300")
        self.assertIn("Twelve Data", self.text("#stats"))
        self.b.run("document.querySelector(\"[data-range='7']\").click()")
        self.b.wait_for("document.querySelector('#chart polyline.line').getAttribute('points').split(' ').length < 10")

    def test_the_yield_curve_view(self):
        self.b.run("document.querySelector(\"[data-view='curve']\").click()")
        curve = self.text("#curves [data-curve='us']")
        self.assertIn("US Treasury yields", curve)
        self.assertIn("3.70%", curve)
        self.assertIn("3.90%", curve)
        self.assertIn("▼ −0.20 pp", curve)

    def test_the_question_mark_opens_and_closes_the_glossary_entry(self):
        self.b.run("document.querySelector('#pick-term').click()")
        self.assertIn("Banco de México", self.text("#pick-define"))
        self.b.run("document.querySelector('#pick-term').click()")
        self.assertTrue(self.b.run("document.querySelector('#pick-define').hidden"))

    def test_hostile_source_text_stays_text_and_a_bad_link_is_dropped(self):
        self.assertIn("<script>alert(2)</script>", self.text("#statements"))
        self.assertEqual(self.b.run("document.querySelectorAll('#statements img, #statements script').length"), 0)
        self.assertFalse(self.b.run("[...document.querySelectorAll('a')].some((a) => a.href.startsWith('javascript:'))"))

    def test_the_side_and_bottom_tabs(self):
        self.assertIn("peso above 18.50", self.text("#lines"))
        self.assertIn("line 3: not understood", self.text("#problems"))
        self.assertIn("Peso past your line", self.text("#alerts"))
        self.assertIn("amx", self.text("#bottom-holdings"))
        self.assertIn("you", self.text("#bottom-trades"))
        self.assertIn("Federal Reserve rate decision", self.text("#calendar"))
        self.assertEqual(self.b.run("document.querySelectorAll('#bottom-glossary details').length"), 17)
        self.b.run("document.querySelector(\"[data-bottom='calendar']\").click()")
        self.assertFalse(self.b.run("document.querySelector('#bottom-calendar').hidden"))
        self.assertTrue(self.b.run("document.querySelector('#bottom-holdings').hidden"))

    def test_the_status_bar_credits_and_disclaimer_stay_visible(self):
        self.assertIn("not investment advice", self.text("#disclaimer"))
        foot = self.text(".status")
        self.assertIn("Powered by CoinGecko", foot)
        self.assertIn("not endorsed or certified by the Federal Reserve Bank of St. Louis", foot)
        self.assertGreater(self.b.run("document.querySelectorAll('#dots span').length"), 5)
        self.assertTrue(self.b.run("document.querySelector('.credits').getBoundingClientRect().height > 0"))

    def test_the_countdowns(self):
        rows = self.text("#countdown")
        self.assertIn("Next FIX (12:00 CDMX)", rows)  # NOW is Tue 10 Nov 08:05 UTC = 02:05 CDMX
        self.assertIn("9 h 55 min", rows)
        self.assertIn("NYSE opens in", rows)
        self.assertIn("Holidays not counted", rows)

    def test_a_phone_width_has_no_sideways_scroll(self):
        self.b.size(375, 800)
        self.b.open(self.url, READY)
        self.assertLessEqual(self.b.run("document.documentElement.scrollWidth"), 375)


if __name__ == "__main__":
    unittest.main()
