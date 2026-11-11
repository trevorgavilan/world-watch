"""Task 5 — the markets page (/markets) and its read-only route (/api/markets), on the server and in a
real browser. The store holds the saved real CoinGecko and Fed answers of 10 Nov, a few FIX and rate
days, a hostile statement written straight into SQLite, Trevor's lines and a practice ledger."""

import json
import unittest
from datetime import timedelta

from tests.browser import Browser, find_browser
from tests.helpers import fixture, temp_dir
from tests.test_board import HOSTILE, get_json, raw_insert, request, start
from tests.test_markets import NOW, day, obs
from worldwatch.board.server import CSP
from worldwatch.collectors import all_collectors, coingecko, fed_press
from worldwatch.item import iso_utc
from worldwatch.markets import paper
from worldwatch.store import Store

EXE = find_browser()
READY = "document.querySelectorAll('.tile').length > 0 && document.querySelector('#paper').childElementCount > 0"


def markets_store():
    base = temp_dir()
    path = base / "worldwatch.sqlite3"
    store = Store(path)
    store.save_items(coingecko.COLLECTOR.parse(fixture("coingecko_simple_price_2026-11-10.json"), NOW))
    store.save_items(fed_press.COLLECTOR.parse(fixture("fed_press_monetary_2026-11-10.xml"), NOW))
    store.save_items([obs("usd-mxn-fix", "18.5000", day(5)), obs("usd-mxn-fix", "18.6226", day(6)),
                      obs("mx-target", "6.50", day(4)), obs("mx-target", "6.25", day(5)),
                      obs("amx", "20.00", NOW - timedelta(hours=1)), obs("vix", "17.20", day(6))])
    book = paper.trade(paper.empty(), store, "buy", "amx", "10", NOW)
    paper.save(base / "paper.json", book)
    store.record_run("fred", NOW, NOW, ok=False, n_items=0, error="needs WW_FRED_KEY (a Windows user environment "
                     "variable Trevor creates)", next_due=iso_utc(NOW), fail_count=0)
    store.close()
    (base / "markets.txt").write_text("peso above 18.50\nwatch NVDA\nwhat is this\n", encoding="utf-8")
    at = iso_utc(NOW)
    raw_insert(path, id="h-fed", source="fed-press", channel="markets", title=HOSTILE, summary=HOSTILE,
               url="javascript:alert(3)", happened_at=at, fetched_at=at, updated_at=at)
    return path


class Route(unittest.TestCase):
    @classmethod
    def setUpClass(cls):
        path = markets_store()
        collectors = all_collectors(path.parent)
        from worldwatch.collectors import peso_alert
        store = Store(path)
        store.save_items(peso_alert.derive(store, NOW, path.parent / "markets.txt"))
        store.close()
        cls.srv = start(path, collectors, now=NOW)
        cls.addClassCleanup(cls.srv.server_close)
        cls.addClassCleanup(cls.srv.shutdown)
        cls.body = get_json(cls.srv, "/api/markets")

    def test_the_page_is_served_with_the_plain_policy_no_frames(self):
        resp, data = request(self.srv, "/markets")
        self.assertEqual(resp.status, 200)
        self.assertEqual(resp.getheader("Content-Security-Policy"), CSP)
        self.assertNotIn("frame-src", resp.getheader("Content-Security-Policy"))
        self.assertIn(b"/static/markets.js", data)
        self.assertNotIn(b"<script>", data)  # no inline script

    def test_the_route_never_writes(self):
        resp, _ = request(self.srv, "/api/markets", method="POST", body=b"{}")
        self.assertEqual(resp.status, 405)

    def test_the_answer_has_the_numbers_lines_alerts_calendar_and_ledger(self):
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
        self.assertEqual(len(b["glossary"]), 17)
        self.assertIn("not investment advice", b["disclaimer_en"])

    def test_every_tile_names_its_source_page_and_delay(self):
        for g in self.body["groups"]:
            for item in g["items"]:
                self.assertTrue(item["page"].startswith("https://"), item["id"])
                self.assertTrue(item["delay_en"] and item["delay_es"], item["id"])
                self.assertIn(item["source"], ("banxico-peso", "banxico-rates", "fred", "coingecko", "twelvedata"))

    def test_no_advice_words_anywhere_in_the_answer(self):
        text = json.dumps(self.body).lower()
        for word in ("you should", "we recommend", "strong buy", "buy now", "sell now", "price target",
                     "guaranteed", "deberías", "recomendamos", "compra ahora"):
            self.assertNotIn(word, text)


@unittest.skipUnless(EXE, "no Edge or Chrome on this machine")
class Page(unittest.TestCase):
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
        self.b.size(1280, 900)
        self.b.open(self.url, READY)

    def text(self, selector):
        return self.b.run(f"document.querySelector({json.dumps(selector)}).textContent")

    def test_tiles_show_value_change_source_and_the_delayed_tag(self):
        fix = self.text(".tile[data-id='usd-mxn-fix']")
        self.assertIn("18.6226", fix)
        self.assertIn("+0.1226 (+0.66%)", fix)
        self.assertIn("Delayed", fix)
        self.assertIn("banxico-peso", fix)
        rate = self.text(".tile[data-id='mx-target']")
        self.assertIn("−0.25 percentage points", rate)
        btc = self.text(".tile[data-id='bitcoin-usd']")
        self.assertIn("74,732.77", btc)
        self.assertIn("(as reported, 24 h)", btc)
        self.assertIn("No number yet from fred — needs WW_FRED_KEY", self.text(".tile[data-id='sp500']"))
        numbered = self.b.run("[...document.querySelectorAll('.tile')].filter((t) => t.querySelector('.value'))"
                              ".every((t) => t.querySelector('.tag') && t.querySelector('.tag').textContent === 'Delayed')")
        self.assertTrue(numbered)

    def test_a_copyrighted_series_keeps_its_owners_notice(self):
        self.assertIn("Chicago Board Options Exchange, Inc. Reprinted with permission. Personal use only.",
                      self.text(".tile[data-id='vix']"))
        self.assertNotIn("Copyright", self.text(".tile[data-id='usd-mxn-fix']"))

    def test_the_disclaimer_and_credits_show(self):
        self.assertIn("not investment advice", self.text("#disclaimer"))
        foot = self.text(".foot")
        self.assertIn("Powered by CoinGecko", foot)
        self.assertIn("not endorsed or certified by the Federal Reserve Bank of St. Louis", foot)

    def test_hostile_source_text_stays_text_and_a_bad_link_is_dropped(self):
        self.assertIn("<script>alert(2)</script>", self.text("#statements"))
        self.assertEqual(self.b.run("document.querySelectorAll('#statements img, #statements script').length"), 0)
        self.assertFalse(self.b.run("[...document.querySelectorAll('a')].some((a) => a.href.startsWith('javascript:'))"))

    def test_a_question_mark_opens_and_closes_the_glossary_entry(self):
        self.b.run("document.querySelector(\".tile[data-id='usd-mxn-fix'] .term\").click()")
        self.assertIn("Banco de México", self.text(".tile[data-id='usd-mxn-fix'] .define"))
        self.b.run("document.querySelector(\".tile[data-id='usd-mxn-fix'] .term\").click()")
        self.assertEqual(self.b.run("document.querySelectorAll(\".tile[data-id='usd-mxn-fix'] .define\").length"), 0)

    def test_the_side_shows_lines_problems_ledger_and_calendar(self):
        self.assertIn("peso above 18.50", self.text("#lines"))
        self.assertIn("line 3: not understood", self.text("#problems"))
        self.assertIn("amx", self.text("#paper"))
        self.assertIn("Federal Reserve rate decision", self.text("#calendar"))
        self.assertEqual(self.b.run("document.querySelectorAll('#glossary details').length"), 17)

    def test_a_phone_width_has_no_sideways_scroll(self):
        self.b.size(375, 800)
        self.b.open(self.url, READY)
        self.assertLessEqual(self.b.run("document.documentElement.scrollWidth"), 375)


if __name__ == "__main__":
    unittest.main()
