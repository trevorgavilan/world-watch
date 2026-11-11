"""Task 5 — Banxico, FRED and Twelve Data against their saved real answers of 11 Nov 2026 (fetched with
Trevor's keys; no key is inside any saved answer), and where each key travels."""

from __future__ import annotations

import json
import os
import unittest
from datetime import datetime, timezone
from urllib.parse import parse_qs, urlsplit
from unittest import mock

from tests.helpers import fixture, temp_dir
from tests.test_markets import FAKE_KEY, store
from worldwatch import keys
from worldwatch.collectors import ParseError, banxico, fred, twelvedata
from worldwatch.markets import calendar
from worldwatch.markets.catalog import INSTRUMENTS

NOW = datetime(2026, 11, 11, 22, 0, tzinfo=timezone.utc)
TOKEN = "b" * 64


def by_inst(items) -> dict:
    found = {}
    for item in items:
        found.setdefault(json.loads(item.raw)["instrument"], []).append(item)
    return found


def value(item) -> str:
    return json.loads(item.raw)["value"]


class BanxicoTest(unittest.TestCase):
    def test_the_saved_fix_answer_gives_one_number_per_bank_day(self):
        items = banxico.PESO.parse(fixture("banxico_peso_2026-11-11.json"), NOW)
        self.assertEqual(len(items), 29)
        newest = max(items, key=lambda i: i.happened_at)
        self.assertEqual((newest.happened_at, value(newest)), ("2026-11-11T00:00:00Z", "18.6192"))
        self.assertIn("Banco de México", newest.licence)
        self.assertEqual(json.loads(newest.raw)["record"]["idSerie"], "SF43718")

    def test_the_saved_rates_answer_gives_each_series(self):
        found = by_inst(banxico.RATES.parse(fixture("banxico_rates_2026-11-11.json"), NOW))
        self.assertEqual({k: len(v) for k, v in found.items()}, {"cetes-28": 6, "mx-target": 42, "tiie-28": 29})
        newest = {k: max(v, key=lambda i: i.happened_at) for k, v in found.items()}
        self.assertEqual({k: value(v) for k, v in newest.items()},
                         {"cetes-28": "6.2000", "mx-target": "6.2500", "tiie-28": "6.5147"})
        # Banxico's own page, 11 Nov: "Resultados de la última subasta 10/11/2026 — Cetes a 28 días 6.20"
        self.assertEqual(newest["cetes-28"].happened_at, "2026-11-10T00:00:00Z")

    def test_no_data_and_unknown_series_are_skipped_and_an_error_answer_fails(self):
        payload = json.dumps({"bmx": {"series": [
            {"idSerie": "SF43718", "datos": [{"fecha": "12/11/2026", "dato": "N/E"}, {"fecha": "13/11/2026", "dato": "18.7"}]},
            {"idSerie": "SF99999", "datos": [{"fecha": "12/11/2026", "dato": "1"}]}]}}).encode()
        self.assertEqual([value(i) for i in banxico.PESO.parse(payload, NOW)], ["18.7"])
        with self.assertRaises(ParseError):
            banxico.PESO.parse(b'{"error": {"mensaje": "Token inv\\u00e1lido"}}', NOW)

    def test_the_token_goes_in_the_header_never_the_url(self):
        with mock.patch.dict(os.environ, {"WW_BANXICO_TOKEN": TOKEN}):
            headers = banxico.PESO.request_headers()
            urls = banxico.PESO.fetch_urls(None, NOW)
        keys._seen.clear()
        self.assertEqual(headers["Bmx-Token"], TOKEN)
        self.assertEqual(urls, ["https://www.banxico.org.mx/SieAPIRest/service/v1/series/SF43718/datos/2025-10-07/2026-11-11"])
        self.assertTrue(all(TOKEN not in u for u in urls))

    def test_later_runs_reach_back_two_weeks(self):
        last = datetime(2026, 11, 10, 12, 0, tzinfo=timezone.utc)
        self.assertTrue(banxico.RATES.fetch_urls(last, NOW)[0].endswith("/datos/2026-10-27/2026-11-11"))

    def test_without_the_token_nothing_is_fetched(self):
        with mock.patch.dict(os.environ, {}, clear=True), mock.patch.object(keys, "_from_registry", return_value=None):
            with self.assertRaises(keys.MissingKey):
                banxico.PESO.request_headers()


class FredTest(unittest.TestCase):
    def url(self, series: str) -> str:
        return f"{fred.BASE}?series_id={series}&api_key=x&file_type=json"

    def test_each_saved_series_is_read_by_the_url_that_asked_for_it(self):
        sp = fred.COLLECTOR.parse(fixture("fred_SP500_2026-11-11.json"), NOW, self.url("SP500"))
        self.assertEqual(len(sp), 29)
        newest = max(sp, key=lambda i: i.happened_at)
        self.assertEqual((newest.happened_at, value(newest)), ("2026-11-10T00:00:00Z", "7520.93"))
        self.assertEqual(json.loads(newest.raw)["instrument"], "sp500")
        noon = fred.COLLECTOR.parse(fixture("fred_DEXMXUS_2026-11-11.json"), NOW, self.url("DEXMXUS"))
        self.assertEqual(len(noon), 26)  # one day of 27 had no number (".")
        self.assertEqual(value(max(noon, key=lambda i: i.happened_at)), "18.6226")

    def test_a_dot_day_is_skipped(self):
        ten = fred.COLLECTOR.parse(fixture("fred_DGS10_2026-11-11.json"), NOW, self.url("DGS10"))
        self.assertEqual(len(ten), 27)
        self.assertNotIn("2026-10-12T00:00:00Z", {i.happened_at for i in ten})

    def test_an_answer_for_a_series_we_didnt_ask_for_fails(self):
        with self.assertRaises(ParseError):
            fred.COLLECTOR.parse(fixture("fred_SP500_2026-11-11.json"), NOW, self.url("GOLDAMGBD228NLBM"))

    def test_one_url_per_series_with_the_key_only_in_the_query(self):
        with mock.patch.dict(os.environ, {"WW_FRED_KEY": FAKE_KEY}):
            urls = fred.COLLECTOR.fetch_urls(None, NOW)
        keys._seen.clear()
        asked = [parse_qs(urlsplit(u).query) for u in urls]
        self.assertEqual(sorted(q["series_id"][0] for q in asked), sorted(i.key for i in INSTRUMENTS if i.source == "fred"))
        self.assertTrue(all(q["api_key"] == [FAKE_KEY] and q["observation_start"] == ["2025-10-07"] for q in asked))

    def test_the_calendar_reads_each_release_date(self):
        items = fred.CALENDAR.parse(fixture("fred_release_10_dates_2026-11-11.json"), NOW)
        items += fred.CALENDAR.parse(fixture("fred_release_50_dates_2026-11-11.json"), NOW)
        self.assertEqual([(i.title, i.happened_at) for i in items],
                         [("Consumer prices (CPI)", "2026-12-10T00:00:00Z"),
                          ("Jobs report (Employment Situation)", "2026-12-04T00:00:00Z")])
        s = store()
        s.save_items(items)
        rows = calendar.upcoming(s, NOW)
        self.assertEqual([r["day"] for r in rows], ["2026-12-04", "2026-12-09", "2026-12-10", "2026-12-17"])
        self.assertEqual(rows[0]["es"], "Informe de empleo (Employment Situation)")

    def test_the_calendar_asks_once_per_release(self):
        with mock.patch.dict(os.environ, {"WW_FRED_KEY": FAKE_KEY}):
            urls = fred.CALENDAR.fetch_urls(None, NOW)
        keys._seen.clear()
        self.assertEqual(sorted(int(parse_qs(urlsplit(u).query)["release_id"][0]) for u in urls), [9, 10, 50, 53, 54])


class TwelveDataTest(unittest.TestCase):
    def setUp(self) -> None:
        self.path = temp_dir() / "markets.txt"
        self.path.write_text("watch NVDA\n")
        self.col = twelvedata.collector(self.path)

    def url(self, symbols: str) -> str:
        return f"{twelvedata.BASE}?symbol={symbols}"

    def test_the_saved_batch_gives_each_mexican_listing_at_its_last_quote(self):
        items = self.col.parse(fixture("twelvedata_quote_mexico_2026-11-11.json"), NOW,
                               self.url("EWW,AMX,FMX,CX,ASR,PAC,OMAB"))
        found = {k: v[0] for k, v in by_inst(items).items()}
        self.assertEqual(sorted(found), ["amx", "asr", "cx", "eww", "fmx", "omab", "pac"])
        amx = json.loads(found["amx"].raw)
        self.assertEqual((amx["value"], amx["change_pct"]), ("25.81", "0.19409849"))
        self.assertEqual(found["amx"].happened_at, "2026-11-11T20:59:00Z")  # last_quote_at, not the bar's open

    def test_gold_is_read_and_a_symbol_outside_the_plan_is_skipped(self):
        items = self.col.parse(fixture("twelvedata_quote_metals_2026-11-11.json"), NOW, self.url("XAU/USD,XAG/USD"))
        self.assertEqual([(json.loads(i.raw)["instrument"], value(i)) for i in items], [("gold", "3985.9449")])

    def test_a_single_symbol_answer_is_the_quote_itself(self):
        items = self.col.parse(fixture("twelvedata_quote_one_2026-11-11.json"), NOW, self.url("NVDA"))
        self.assertEqual([(json.loads(i.raw)["instrument"], value(i)) for i in items], [("watch-nvda", "173.85001")])

    def test_out_of_credits_is_a_rate_limit(self):
        from worldwatch.http import RateLimited
        with self.assertRaises(RateLimited):
            self.col.parse(b'{"code": 429, "message": "run out of API credits", "status": "error"}', NOW, self.url("AMX"))

    def test_batches_of_eight_with_the_key_only_in_the_header(self):
        self.path.write_text("\n".join(f"watch T{n}" for n in range(12)))
        with mock.patch.dict(os.environ, {"WW_TWELVEDATA_KEY": FAKE_KEY}):
            headers = self.col.request_headers()
            urls = self.col.fetch_urls(None, NOW)
        keys._seen.clear()
        self.assertEqual(headers, {"Authorization": f"apikey {FAKE_KEY}"})
        symbols = [parse_qs(urlsplit(u).query)["symbol"][0].split(",") for u in urls]
        self.assertTrue(all(len(batch) <= twelvedata.BATCH for batch in symbols))
        self.assertEqual(sum(len(b) for b in symbols), 8 + 12)  # 7 Mexican listings, gold, 12 tickers
        self.assertTrue(all(FAKE_KEY not in u for u in urls))


if __name__ == "__main__":
    unittest.main()
