"""Task 5's code review (2026-11-11): each finding that was fixed, held by a test."""

from __future__ import annotations

import json
import os
import unittest
from datetime import timedelta
from unittest import mock

from tests.helpers import fixture, temp_dir
from tests.test_markets import NOW, day, obs, store
from worldwatch import keys, runner
from worldwatch.collectors import banxico, fred, peso_alert, twelvedata
from worldwatch.collectors import ParseError
from worldwatch.http import FetchError
from worldwatch.markets import calendar, number, paper, view
from worldwatch.markets.catalog import INSTRUMENTS

INST = {i.id: i for i in INSTRUMENTS}


class NewestRowsWin(unittest.TestCase):
    def test_tiles_show_the_newest_number_even_past_the_row_cap(self):
        s = store()
        start = NOW - timedelta(days=60)
        s.save_items([obs("bitcoin-usd", str(100 + n), start + timedelta(hours=n)) for n in range(60 * 24)])
        with mock.patch.object(view, "ROWS_PER_SOURCE", 500):
            body = view.markets_view(s, ["coingecko"], NOW)
        tile = next(i for g in body["groups"] for i in g["items"] if i["id"] == "bitcoin-usd")
        self.assertEqual(tile["latest"]["value"], f"{100 + 60 * 24 - 1:.2f}")


class OneBadTicker(unittest.TestCase):
    def test_a_refused_lone_symbol_is_skipped_but_a_refused_key_fails(self):
        path = temp_dir() / "markets.txt"
        path.write_text("watch ZZZZ\n")
        col = twelvedata.collector(path)
        url = f"{twelvedata.BASE}?symbol=ZZZZ"
        refused = b'{"code": 404, "message": "**symbol** not found", "status": "error"}'
        self.assertEqual(col.parse(refused, NOW, url), [])
        with self.assertRaises(ParseError):
            col.parse(b'{"code": 401, "message": "invalid api key", "status": "error"}', NOW, url)


class SaneNumbers(unittest.TestCase):
    def test_absurd_values_are_refused_and_real_ones_kept(self):
        for bad in ("1e999999999", "-1e20", "1e-400", "Infinity", "NaN", "", ".", "N/E", True):
            with self.subTest(bad=bad), self.assertRaises(ValueError):
                number(bad)
        for good in ("0", "0.0000001", "18.6192", "74732.76770611235", "-1.2987", "1e12"):
            number(good)

    def test_a_bad_reported_change_keeps_the_price(self):
        item = obs("bitcoin-usd", "74000", NOW, change_pct="abc")
        raw = json.loads(item.raw)
        self.assertEqual(raw["value"], "74000")
        self.assertNotIn("change_pct", raw)


class PesoAlertsKept(unittest.TestCase):
    def setUp(self) -> None:
        self.path = temp_dir() / "markets.txt"
        self.s = store()
        self.s.save_items([obs("usd-mxn-fix", "18.6226", day(6))])
        self.path.write_text("peso above 18.50\n")
        self.s.save_items(peso_alert.derive(self.s, NOW, self.path))

    def test_a_file_that_cant_be_read_forgets_nothing(self):
        self.path.unlink()
        peso_alert.derive(self.s, NOW, self.path)
        self.assertEqual(self.s.count_items("peso-alert"), 1)
        self.path.write_bytes(b"peso above 18.50\n\xff\xfe")
        peso_alert.derive(self.s, NOW, self.path)
        self.assertEqual(self.s.count_items("peso-alert"), 1)

    def test_the_same_line_written_differently_is_the_same_line(self):
        self.path.write_text("peso above 18.5\n")
        self.s.save_items(peso_alert.derive(self.s, NOW, self.path))
        self.assertEqual(self.s.count_items("peso-alert"), 1)


class CalendarMoves(unittest.TestCase):
    def test_a_release_fred_moved_shows_once_on_its_new_day(self):
        s = store()
        first = NOW - timedelta(days=1)
        old = fred.CALENDAR.parse(json.dumps({"release_dates": [{"release_id": 10, "date": "2026-12-03"}]}).encode(), first)
        s.save_items(old)
        s.record_run(fred.CALENDAR_SOURCE, first, first, ok=True, n_items=1, error=None, next_due="x", fail_count=0)
        s.save_items(fred.CALENDAR.parse(fixture("fred_release_10_dates_2026-11-11.json"), NOW))
        s.record_run(fred.CALENDAR_SOURCE, NOW, NOW, ok=True, n_items=1, error=None, next_due="x", fail_count=0)
        days = [r["day"] for r in calendar.releases(s, NOW)]
        self.assertEqual(days, ["2026-12-10"])


class OneFredSeriesDown(unittest.TestCase):
    def tearDown(self) -> None:
        keys._seen.clear()

    def test_a_failing_series_is_skipped_and_the_rest_stored(self):
        class Fake:
            def get(self, url):
                if fred.series_of(url) == "DGS10":
                    raise FetchError("HTTP 500 from api.stlouisfed.org")
                return fixture("fred_SP500_2026-11-11.json")

        s = store()
        with mock.patch.dict(os.environ, {"WW_FRED_KEY": "a" * 32}), self.assertLogs("worldwatch.runner") as logged:
            result = runner.run_source(s, fred.COLLECTOR, Fake(), NOW)
        self.assertTrue(result.ok)
        self.assertTrue(any("skipped" in line for line in logged.output))
        self.assertFalse(any("a" * 32 in line for line in logged.output))  # masked by the runner itself
        self.assertGreater(s.count_items("fred"), 0)


class DamagedLedger(unittest.TestCase):
    def test_every_trade_is_checked_when_the_ledger_loads(self):
        path = temp_dir() / "paper.json"
        good = {"at": "x", "side": "buy", "instrument": "amx", "key": "AMX", "source": "twelvedata", "qty": "1",
                "price": "20", "fx": "18.5"}
        damaged = [{**good, "side": "BUY"}, {**good, "instrument": 5}, {**good, "qty": "1e999999"},
                   {**good, "price": "-3"}, {**good, "fx": None}, "a string"]
        for t in damaged:
            with self.subTest(trade=t):
                path.write_text(json.dumps({"start_mxn": "100000", "trades": [t]}))
                with self.assertRaises(paper.PaperError):
                    paper.load(path)
        path.write_text(json.dumps({"start_mxn": "100000", "trades": [good]}))
        self.assertEqual(paper.load(path)["trades"], [good])


class SmallOnes(unittest.TestCase):
    def tearDown(self) -> None:
        keys._seen.clear()

    def test_a_banxico_error_as_plain_text_is_a_parse_error(self):
        with self.assertRaises(ParseError):
            banxico.PESO.parse(b'{"error": "Token invalido"}', NOW)

    def test_a_malformed_key_is_named_as_malformed(self):
        with mock.patch.dict(os.environ, {"WW_FRED_KEY": "has spaces in it"}):
            with self.assertRaisesRegex(keys.MissingKey, "set but malformed"):
                keys.require_key("WW_FRED_KEY")
        with mock.patch.dict(os.environ, {}, clear=True), mock.patch.object(keys, "_from_registry", return_value=None):
            with self.assertRaisesRegex(keys.MissingKey, "needs WW_FRED_KEY"):
                keys.require_key("WW_FRED_KEY")


if __name__ == "__main__":
    unittest.main()
