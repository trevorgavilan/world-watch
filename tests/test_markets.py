"""Task 5 — markets: keys kept out of logs and the store, the collectors against saved real answers,
the peso lines, the page's numbers, the practice portfolio."""

from __future__ import annotations

import io
import json
import logging
import os
import unittest
from datetime import datetime, timedelta, timezone
from decimal import Decimal
from unittest import mock

from tests.helpers import fixture, temp_dir
from worldwatch import keys, runner
from worldwatch.collectors import Collector, coingecko, fed_press, peso_alert
from worldwatch.markets import observation, paper, rules
from worldwatch.markets.catalog import INSTRUMENTS, watch_instrument
from worldwatch.markets.view import markets_view
from worldwatch.store import Store

NOW = datetime(2026, 11, 10, 8, 5, tzinfo=timezone.utc)
INST = {i.id: i for i in INSTRUMENTS}
FAKE_KEY = "abcdef0123456789abcdef0123456789"


_OPEN: list[Store] = []


def store() -> Store:
    opened = Store(temp_dir() / "ww.sqlite3")
    _OPEN.append(opened)
    return opened


def tearDownModule() -> None:  # noqa: N802 — unittest's name
    while _OPEN:
        _OPEN.pop().close()


def obs(inst_id: str, value: str, at: datetime, change_pct=None):
    inst = INST[inst_id]
    stamp = f"{at:%Y-%m-%d}" if inst.daily else f"{at:%Y-%m-%dT%H}"
    return observation(inst, value=value, at=at, fetched_at=NOW, licence="test", stamp=stamp, record={},
                       change_pct=change_pct)


def day(n: int) -> datetime:
    return datetime(2026, 11, n, tzinfo=timezone.utc)


class KeysTest(unittest.TestCase):
    def tearDown(self) -> None:
        keys._seen.clear()

    def test_a_key_is_read_from_the_environment_and_checked(self):
        with mock.patch.dict(os.environ, {"WW_TEST_KEY": f"  {FAKE_KEY}\n"}):
            self.assertEqual(keys.get_key("WW_TEST_KEY"), FAKE_KEY)
        for bad in ("short", "has space in it 123", "semi;colon0123", "x" * 200):
            with mock.patch.dict(os.environ, {"WW_TEST_KEY": bad}), mock.patch.object(keys, "_from_registry",
                                                                                     return_value=None):
                self.assertIsNone(keys.get_key("WW_TEST_KEY"), bad)

    def test_a_missing_key_is_none(self):
        with mock.patch.dict(os.environ, {}, clear=True), mock.patch.object(keys, "_from_registry", return_value=None):
            self.assertIsNone(keys.get_key("WW_NOT_SET"))

    def test_a_key_that_was_read_is_masked_in_text_and_log_lines(self):
        with mock.patch.dict(os.environ, {"WW_TEST_KEY": FAKE_KEY}):
            keys.get_key("WW_TEST_KEY")
        self.assertEqual(keys.redact(f"GET /x?api_key={FAKE_KEY}&y=1"), f"GET /x?api_key={keys.MASK}&y=1")
        out = io.StringIO()
        handler = logging.StreamHandler(out)
        handler.addFilter(keys.RedactKeys())
        log = logging.getLogger("ww-test-redact")
        log.addHandler(handler)
        log.propagate = False
        try:
            log.warning("skipped %s", f"https://api.example.org/?api_key={FAKE_KEY}")
            try:
                raise ValueError(f"bad url {FAKE_KEY}")
            except ValueError:
                log.exception("boom")
        finally:
            log.removeHandler(handler)
        self.assertNotIn(FAKE_KEY, out.getvalue())
        self.assertIn(keys.MASK, out.getvalue())


class RunnerKeysTest(unittest.TestCase):
    def tearDown(self) -> None:
        keys._seen.clear()

    def _collector(self, url_for=None, headers=None) -> Collector:
        return Collector(source="k-src", channel="markets", url="https://api.example.org/", interval_s=600,
                         licence="t", parse_records=lambda d, f: [], url_for=url_for, headers=headers)

    def test_a_missing_key_waits_without_backoff_or_a_fetch(self):
        def headers():
            raise keys.MissingKey("needs WW_X (a Windows user environment variable Trevor creates)")

        class Never:
            def get(self, url, headers=None):
                raise AssertionError("fetched without a key")

        s = store()
        for _ in range(3):
            result = runner.run_source(s, self._collector(headers=headers), Never(), NOW)
        self.assertFalse(result.ok)
        state = s.source_state("k-src")
        self.assertEqual(state["fail_count"], 0)
        self.assertIn("needs WW_X", state["last_error"])
        self.assertEqual(state["next_due"], "2026-11-10T08:35:00Z")

    def test_headers_reach_the_fetcher_and_a_key_in_a_url_never_reaches_the_store(self):
        with mock.patch.dict(os.environ, {"WW_TEST_KEY": FAKE_KEY}):
            key = keys.get_key("WW_TEST_KEY")
        seen = {}

        class Fails:
            def get(self, url, headers=None):
                seen["headers"] = headers
                from worldwatch.http import FetchError
                raise FetchError(f"HTTP 500 for {url}")

        s = store()
        col = self._collector(url_for=lambda last, now: [f"https://api.example.org/?api_key={key}"],
                              headers=lambda: {"Authorization": f"apikey {key}"})
        runner.run_source(s, col, Fails(), NOW)
        self.assertEqual(seen["headers"], {"Authorization": f"apikey {FAKE_KEY}"})
        self.assertNotIn(FAKE_KEY, s.source_state("k-src")["last_error"])

    def test_the_fetcher_sends_a_sources_headers_with_our_user_agent(self):
        from worldwatch import http

        captured = {}

        class Answer(io.BytesIO):
            headers = {}

            def __enter__(self):
                return self

            def __exit__(self, *a):
                return False

        def fake_open(request, timeout):
            captured.update(request.header_items())
            return Answer(b"{}")

        with mock.patch.object(http.urllib.request, "urlopen", fake_open):
            http.Fetcher(sleep=lambda s: None).get("https://api.example.org/q", {"Bmx-Token": "t" * 64,
                                                                               "User-Agent": "spoof"})
        self.assertEqual(captured["Bmx-token"], "t" * 64)
        self.assertEqual(captured["User-agent"], http.USER_AGENT)


class CoinGeckoTest(unittest.TestCase):
    def test_the_saved_answer_gives_each_coin_in_dollars_and_pesos(self):
        items = coingecko.COLLECTOR.parse(fixture("coingecko_simple_price_2026-11-10.json"), NOW)
        self.assertEqual(len(items), 6)
        by_inst = {json.loads(i.raw)["instrument"]: i for i in items}
        btc = json.loads(by_inst["bitcoin-usd"].raw)
        self.assertEqual(btc["value"], "74732.76770611235")
        self.assertEqual(btc["change_pct"], "1.359871589947371")
        self.assertEqual(by_inst["bitcoin-usd"].happened_at, "2026-11-10T08:01:55Z")  # last_updated_at 1794297715
        self.assertEqual(json.loads(by_inst["solana-mxn"].raw)["change_pct"], "-0.07984002967686052")
        self.assertTrue(all(i.channel == "markets" and "CoinGecko" in i.licence for i in items))

    def test_the_same_hour_updates_one_row(self):
        items = coingecko.COLLECTOR.parse(fixture("coingecko_simple_price_2026-11-10.json"), NOW)
        again = coingecko.COLLECTOR.parse(fixture("coingecko_simple_price_2026-11-10.json"), NOW + timedelta(minutes=15))
        self.assertEqual({i.id for i in items}, {i.id for i in again})

    def test_junk_values_are_skipped_not_stored(self):
        payload = json.dumps({"bitcoin": {"usd": "NaN", "mxn": None, "last_updated_at": 1794297715},
                              "ethereum": {"usd": 1.5, "mxn": 2.5, "last_updated_at": "soon"},
                              "solana": {"usd": True, "mxn": 3, "last_updated_at": 1794297715}}).encode()
        items = coingecko.COLLECTOR.parse(payload, NOW)
        self.assertEqual([json.loads(i.raw)["instrument"] for i in items], ["solana-mxn"])

    def test_an_answer_without_our_coins_is_an_error(self):
        from worldwatch.collectors import ParseError
        with self.assertRaises(ParseError):
            coingecko.COLLECTOR.parse(b'{"status": {"error_code": 429}}', NOW)


class FedPressTest(unittest.TestCase):
    def test_the_saved_feed_gives_the_fomc_statements_with_their_times(self):
        items = fed_press.COLLECTOR.parse(fixture("fed_press_monetary_2026-11-10.xml"), NOW)
        self.assertEqual(len(items), 15)
        first = items[0]
        self.assertEqual(first.title, "Federal Reserve issues FOMC statement")
        self.assertEqual(first.happened_at, "2026-10-28T18:00:00Z")
        self.assertTrue(first.url.startswith("https://www.federalreserve.gov/"))
        self.assertEqual(first.severity, "Monetary Policy")


class RulesTest(unittest.TestCase):
    def test_lines_and_tickers_are_read_and_bad_lines_named(self):
        text = ("# comment\npeso above 19.50\nPESO BELOW 17.8  # low\npeso above 19.50\nwatch nvda\nwatch BRK.B\n"
                "peso above lots\npeso above 190\nbuy everything\nwatch <script>\n")
        r = rules.parse(text)
        self.assertEqual([p.text for p in r.peso], ["peso above 19.50", "peso below 17.8"])
        self.assertEqual(r.watch, ["NVDA", "BRK.B"])
        self.assertEqual(len(r.problems), 4)
        self.assertTrue(r.peso[0].crossed(Decimal("19.51")))
        self.assertFalse(r.peso[0].crossed(Decimal("19.50")))
        self.assertTrue(r.peso[1].crossed(Decimal("17.79")))

    def test_limits_hold(self):
        r = rules.parse("\n".join(f"watch T{n}" for n in range(30)))
        self.assertEqual(len(r.watch), rules.MAX_WATCH)
        self.assertTrue(r.problems)

    def test_a_missing_or_huge_file_reads_as_no_lines(self):
        base = temp_dir()
        self.assertEqual(rules.load(base / "markets.txt").peso, [])
        (base / "big.txt").write_text("x" * (rules.MAX_BYTES + 1))
        self.assertTrue(rules.load(base / "big.txt").problems)

    def test_ensure_writes_the_template_once_and_never_overwrites(self):
        path = temp_dir() / "markets.txt"
        rules.ensure(path)
        self.assertEqual([p.text for p in rules.load(path).peso], ["peso above 19.50", "peso below 17.80"])
        path.write_text("watch AMX\n")
        rules.ensure(path)
        self.assertEqual(path.read_text(), "watch AMX\n")


class PesoAlertTest(unittest.TestCase):
    def setUp(self) -> None:
        self.base = temp_dir()
        self.path = self.base / "markets.txt"
        self.s = store()

    def test_a_crossed_line_is_an_inferred_alert_for_the_fix_day(self):
        self.path.write_text("peso above 18.50\npeso below 17.00\n")
        self.s.save_items([obs("usd-mxn-fix", "18.4000", day(5)), obs("usd-mxn-fix", "18.6226", day(6))])
        items = peso_alert.derive(self.s, NOW, self.path)
        self.assertEqual(len(items), 1)
        self.assertEqual(items[0].basis, "inferred")
        self.assertEqual(items[0].happened_at, "2026-11-06T00:00:00Z")
        self.assertIn("18.6226", items[0].title)
        self.assertIn("above 18.50", items[0].title)

    def test_no_alert_when_inside_the_lines_or_no_fix(self):
        self.path.write_text("peso above 19.50\n")
        self.assertEqual(peso_alert.derive(self.s, NOW, self.path), [])
        self.s.save_items([obs("usd-mxn-fix", "18.6226", day(6))])
        self.assertEqual(peso_alert.derive(self.s, NOW, self.path), [])

    def test_a_line_taken_out_forgets_its_alerts(self):
        self.path.write_text("peso above 18.50\n")
        self.s.save_items([obs("usd-mxn-fix", "18.6226", day(6))])
        self.s.save_items(peso_alert.derive(self.s, NOW, self.path))
        self.assertEqual(self.s.count_items("peso-alert"), 1)
        self.path.write_text("peso above 19.50\n")
        self.s.save_items(peso_alert.derive(self.s, NOW, self.path))
        self.assertEqual(self.s.count_items("peso-alert"), 0)
        self.assertEqual(self.s.count_items("banxico-peso"), 1)  # Banxico's own rows are never touched


class ViewTest(unittest.TestCase):
    def setUp(self) -> None:
        self.s = store()

    def view(self, sources=("banxico-peso", "banxico-rates", "fred", "coingecko", "twelvedata"), **kw):
        return markets_view(self.s, list(sources), NOW, **kw)

    def tile(self, body, inst_id):
        return next(i for g in body["groups"] for i in g["items"] if i["id"] == inst_id)

    def test_a_daily_number_changes_against_the_one_before(self):
        self.s.save_items([obs("usd-mxn-fix", "18.5000", day(5)), obs("usd-mxn-fix", "18.6226", day(6))])
        t = self.tile(self.view(), "usd-mxn-fix")
        self.assertEqual(t["latest"]["value"], "18.6226")
        self.assertAlmostEqual(t["change"]["abs"], 0.1226)
        self.assertAlmostEqual(t["change"]["pct"], 0.1226 / 18.5 * 100)
        self.assertEqual(t["change"]["since"], "2026-11-05T00:00:00Z")
        self.assertEqual(len(t["history"]), 2)

    def test_a_rate_changes_in_percentage_points_only(self):
        self.s.save_items([obs("mx-target", "6.50", day(4)), obs("mx-target", "6.25", day(5))])
        t = self.tile(self.view(), "mx-target")
        self.assertAlmostEqual(t["change"]["abs"], -0.25)
        self.assertNotIn("pct", t["change"])
        self.assertTrue(t["points"])

    def test_a_fetched_price_shows_the_change_its_source_reported(self):
        self.s.save_items([obs("bitcoin-usd", "74732.77", NOW, change_pct="1.36")])
        t = self.tile(self.view(), "bitcoin-usd")
        self.assertEqual(t["change"], {"pct": 1.36, "since": "reported"})

    def test_the_peso_comes_first_and_empty_tiles_still_show(self):
        body = self.view()
        self.assertEqual(body["groups"][0]["id"], "peso")
        self.assertIsNone(self.tile(body, "sp500")["latest"])
        self.assertIn("not investment advice", body["disclaimer_en"])

    def test_what_moved_ranks_recent_moves_and_skips_old_and_rates(self):
        self.s.save_items([obs("usd-mxn-fix", "18.00", day(5)), obs("usd-mxn-fix", "18.90", day(6)),  # +5%
                           obs("sp500", "100", day(1)), obs("sp500", "150", day(2)),  # old: 8 days
                           obs("mx-target", "6.50", day(4)), obs("mx-target", "7.50", day(5)),
                           obs("bitcoin-usd", "1", NOW, change_pct="-7.5")])
        moves = self.view()["moves"]
        self.assertEqual([m["id"] for m in moves], ["bitcoin-usd", "usd-mxn-fix"])

    def test_history_is_thinned_but_keeps_the_newest(self):
        start = NOW - timedelta(days=300)
        self.s.save_items([obs("sp500", str(1000 + n), start + timedelta(days=n)) for n in range(300)])
        t = self.tile(self.view(), "sp500")
        self.assertLessEqual(len(t["history"]), 120)
        self.assertEqual(t["history"][-1][1], 1299.0)

    def test_only_sources_in_the_run_show_and_a_watch_ticker_gets_a_tile(self):
        body = self.view(sources=("coingecko", "twelvedata"), watch=[watch_instrument("NVDA")])
        ids = [i["id"] for g in body["groups"] for i in g["items"]]
        self.assertNotIn("usd-mxn-fix", ids)
        self.assertIn("watch-nvda", ids)


class PaperTest(unittest.TestCase):
    def setUp(self) -> None:
        self.s = store()
        self.s.save_items([obs("usd-mxn-fix", "18.5000", day(9)), obs("amx", "20.00", NOW - timedelta(hours=1)),
                           obs("bitcoin-mxn", "1000000", NOW - timedelta(hours=1))])

    def test_a_buy_converts_dollars_at_the_fix_and_a_sell_returns_cash(self):
        book = paper.trade(paper.empty(), self.s, "buy", "AMX", "10", NOW)
        self.assertEqual(paper.cash(book), Decimal("100000") - Decimal("10") * Decimal("20.00") * Decimal("18.5000"))
        book = paper.trade(book, self.s, "sell", "amx", "4", NOW)
        self.assertEqual(paper.holdings(book), {"amx": Decimal(6)})
        view = paper.summary(book, self.s, NOW)
        self.assertEqual(view["total_mxn"], "100000.00")  # no price move: no gain, no loss
        self.assertEqual(view["holdings"][0]["value_mxn"], "2220.00")

    def test_crypto_in_pesos_can_be_bought_in_fractions(self):
        book = paper.trade(paper.empty(), self.s, "buy", "bitcoin-mxn", "0.05", NOW)
        self.assertEqual(paper.cash(book), Decimal("50000"))

    def test_trades_that_cant_be_made_are_refused(self):
        cases = [("buy", "sp500", "1"), ("buy", "AMX", "1.5"), ("buy", "AMX", "-1"), ("buy", "AMX", "NaN"),
                 ("buy", "bitcoin-mxn", "1"), ("sell", "AMX", "1"), ("buy", "ETH", "1"), ("short", "AMX", "1")]
        for side, name, qty in cases:
            with self.subTest(side=side, name=name, qty=qty), self.assertRaises(paper.PaperError):
                paper.trade(paper.empty(), self.s, side, name, qty, NOW)

    def test_a_stale_price_is_never_used(self):
        later = NOW + timedelta(days=10)
        with self.assertRaises(paper.PaperError):
            paper.trade(paper.empty(), self.s, "buy", "AMX", "1", later)

    def test_the_ledger_saves_whole_and_reads_back(self):
        path = temp_dir() / "paper.json"
        book = paper.trade(paper.empty(), self.s, "buy", "AMX", "1", NOW)
        paper.save(path, book)
        self.assertEqual(paper.load(path), book)
        path.write_text("[1, 2]")
        with self.assertRaises(paper.PaperError):
            paper.load(path)


if __name__ == "__main__":
    unittest.main()


class ReconPesoTest(unittest.TestCase):
    def test_recon_shows_the_fix_and_crossed_lines_with_their_dates(self):
        from worldwatch.recon import gather
        from worldwatch.recon_html import render_html
        from worldwatch.collectors import banxico

        base = temp_dir()
        (base / "markets.txt").write_text("peso above 18.50\n")
        s = store()
        s.save_items([obs("usd-mxn-fix", "18.6226", day(6))])
        alert = peso_alert.collector(base / "markets.txt")
        s.save_items(peso_alert.derive(s, NOW, base / "markets.txt"))
        page = render_html(gather(s, [alert, banxico.PESO], NOW))
        self.assertIn("The peso", page)
        self.assertIn("18.6226", page)
        self.assertIn("Peso past your line", page)
        self.assertIn("06 Nov", page)
        self.assertIn("Banco de México", page)
