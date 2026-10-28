"""Task 3: NVD, OSV and EPSS collectors, the watchlist, and the "my stack" alerts — on saved real
responses (NVD 21 Oct = PHP2Shell day, 25 Oct = a quiet day; KEV, OSV and EPSS of 28 Oct)."""

from __future__ import annotations

import gzip
import unittest
from datetime import datetime, timedelta, timezone
from urllib.parse import parse_qs, urlsplit

from tests.helpers import LIVE, fixture, temp_dir
from worldwatch import watchlist
from worldwatch.board.data import Registry, panel_entries
from worldwatch.collectors import ParseError, all_collectors, cisa_kev, epss, my_stack, nvd, osv
from worldwatch.http import Fetcher
from worldwatch.runner import run_once
from worldwatch.store import Store

PHP2SHELL = {"CVE-2026-109618", "CVE-2026-109619"}
REPLAY_NOW = datetime(2026, 10, 22, 5, 0, tzinfo=timezone.utc)   # 21 Oct, 23:00 in CDMX
QUIET_NOW = datetime(2026, 10, 26, 5, 0, tzinfo=timezone.utc)    # 25 Oct, 23:00 in CDMX
LATER_NOW = datetime(2026, 10, 28, 20, 0, tzinfo=timezone.utc)
# Trevor's kind of list, without PHP: none of it is named on either day.
NO_PHP = "Windows 11 = windows 11*\nChrome = chromium*, google chrome\nPython = cpython\nTouchDesigner\nAbleton Live\nCarrd\n"


def gz(name: str) -> bytes:
    return gzip.decompress(fixture(name))


def keys(items) -> set:
    return {i.title.split(" · ")[1].split(" — ")[0] for i in items if " · " in i.title}


class StoreCase(unittest.TestCase):
    def setUp(self):
        self.dir = temp_dir()
        self.store = Store(self.dir / "t.sqlite3")
        self.addCleanup(self.store.close)

    def load(self, now, nvd_day="nvd_pub_2026-10-21.json.gz"):
        self.store.save_items(nvd.COLLECTOR.parse(gz(nvd_day), now))
        self.store.save_items(cisa_kev.COLLECTOR.parse(gz("cisa_kev_2026-10-28.json.gz"), now))
        for name in ("osv_BIT-php-2026-109618.json", "osv_BIT-php-2026-109619.json", "osv_BIT-pillow-2026-112901.json"):
            self.store.save_items(osv.COLLECTOR.parse(fixture(name), now))
        self.store.save_items(epss.COLLECTOR.parse(fixture("epss_recent.json"), now))

    def watch(self, text: str):
        path = self.dir / "watchlist.txt"
        path.write_text(text, encoding="utf-8")
        return path

    def derive(self, text: str, now, *, save=False):
        items = my_stack.derive(self.store, now, self.watch(text))
        if save:
            self.store.save_items(items)
        return items


class Nvd(unittest.TestCase):
    def test_saved_php2shell_day(self):
        items = nvd.COLLECTOR.parse(gz("nvd_pub_2026-10-21.json.gz"), REPLAY_NOW)
        self.assertEqual(len(items), 564)
        php = next(i for i in items if i.title.startswith("CVE-2026-109618"))
        self.assertEqual(php.happened_at, "2026-10-21T14:17:09Z")
        self.assertEqual(php.severity, "CVSS 9.2 critical")
        self.assertEqual(php.url, "https://nvd.nist.gov/vuln/detail/CVE-2026-109618")
        self.assertIn('["PHP Group", "PHP"]', php.raw)  # the vendor's own filing
        self.assertTrue(php.licence.startswith("US public domain"))

    def test_cpe_names_count_too(self):
        cve = __import__("json").loads(fixture("nvd_cve_CVE-2026-109618.json"))["vulnerabilities"][0]["cve"]
        self.assertIn(["php", "php"], nvd.products(cve))
        self.assertIn(["PHP Group", "PHP"], nvd.products(cve))

    def test_bad_records(self):
        with self.assertRaises(ParseError):
            nvd.COLLECTOR.parse(b'{"nope": 1}', REPLAY_NOW)
        bad = b'{"vulnerabilities": [{"cve": {"id": "CVE-x", "published": "2026-10-21T00:00:00.000"}},' \
              b'{"cve": {"id": "CVE-2026-1234", "published": "2026-10-21T00:00:00.000"}}]}'
        self.assertEqual([i.title for i in nvd.COLLECTOR.parse(bad, REPLAY_NOW)],
                         ["CVE-2026-1234 — product not named yet"])

    def test_window(self):
        def q(url):
            return {k: v[0] for k, v in parse_qs(urlsplit(url).query, keep_blank_values=True).items()}
        now = LATER_NOW
        first = q(nvd.url_for(None, now)[0])
        self.assertEqual(first["pubStartDate"], "2026-10-21T20:00:00.000Z")
        self.assertEqual(first["pubEndDate"], "2026-10-28T20:00:00.000Z")
        self.assertIn("noRejected", first)
        self.assertEqual(q(nvd.url_for(now - timedelta(hours=2), now)[0])["pubStartDate"], "2026-10-28T15:00:00.000Z")
        self.assertEqual(q(nvd.url_for(now - timedelta(days=90), now)[0])["pubStartDate"], "2026-09-28T20:00:00.000Z")
        self.assertEqual(q(nvd.url_for(now + timedelta(days=2), now)[0])["pubStartDate"], first["pubStartDate"])

    def test_paging(self):
        url = nvd.url_for(None, LATER_NOW)[0]
        self.assertEqual(nvd.follow(gz("nvd_pub_2026-10-25.json.gz"), url, None, LATER_NOW), [])
        page = b'{"startIndex": 0, "resultsPerPage": 2000, "totalResults": 4500, "vulnerabilities": []}'
        nxt = nvd.follow(page, url, None, LATER_NOW)
        self.assertEqual(len(nxt), 1)
        self.assertEqual(parse_qs(urlsplit(nxt[0]).query)["startIndex"], ["2000"])
        self.assertEqual(parse_qs(urlsplit(nxt[0]).query)["pubStartDate"], parse_qs(urlsplit(url).query)["pubStartDate"])
        last = b'{"startIndex": 4000, "resultsPerPage": 500, "totalResults": 4500, "vulnerabilities": []}'
        self.assertEqual(nvd.follow(last, url, None, LATER_NOW), [])
        huge = b'{"startIndex": 38000, "resultsPerPage": 2000, "totalResults": 90000, "vulnerabilities": []}'
        with self.assertRaises(ParseError):
            nvd.follow(huge, url, None, LATER_NOW)

    @unittest.skipUnless(LIVE, "live")
    def test_live(self):
        now = datetime.now(timezone.utc)
        payload = Fetcher().get(nvd.url_for(now - timedelta(hours=6), now)[0])
        nvd.COLLECTOR.parse(payload, now)  # any count, even 0 on a quiet morning; the shape must hold
        self.assertIn(b'"totalResults"', payload)


class Osv(unittest.TestCase):
    def test_listing_names_records_changed_since_the_last_run(self):
        listing = gz("osv_bitnami_modified_id.csv.gz")
        self.assertEqual(osv.COLLECTOR.parse(listing, LATER_NOW), [])
        urls = osv.follow(listing, osv.LISTING, datetime(2026, 10, 26, 9, 0, tzinfo=timezone.utc), LATER_NOW)
        self.assertIn(f"{osv.BUCKET}/Bitnami/BIT-php-2026-109618.json", urls)
        self.assertTrue(all(u.startswith(f"{osv.BUCKET}/Bitnami/BIT-") for u in urls))
        self.assertLessEqual(len(urls), osv.MAX_RECORDS)
        self.assertEqual(osv.follow(fixture("osv_BIT-php-2026-109618.json"), "https://x/BIT-a.json", None, LATER_NOW), [])

    def test_hostile_listing_ids_never_become_urls(self):
        listing = (b"2026-10-28T11:00:00Z,../../other/evil\n2026-10-28T10:00:00Z,a/b\n"
                   b"2026-10-28T09:00:00Z,BIT-ok-2026-1\n2026-10-28T08:00:00Z,x..y\n")
        self.assertEqual(osv.follow(listing, osv.LISTING, None, LATER_NOW), [f"{osv.BUCKET}/Bitnami/BIT-ok-2026-1.json"])
        with self.assertRaises(ParseError):
            osv.COLLECTOR.parse(b"one,two,three\n", LATER_NOW)

    def test_first_run_reads_three_days_and_caps(self):
        rows = "".join(f"2026-10-28T{19 - n // 60:02d}:{59 - n % 60:02d}:00Z,BIT-x-{n}\n" for n in range(300))
        urls = osv.follow(rows.encode(), osv.LISTING, None, LATER_NOW)
        self.assertEqual(len(urls), osv.MAX_RECORDS)
        self.assertTrue(urls[0].endswith("BIT-x-0.json"))  # newest kept
        old = b"2026-10-24T00:00:00Z,BIT-old-1\n"
        self.assertEqual(osv.follow(old, osv.LISTING, None, LATER_NOW), [])

    def test_record(self):
        item = osv.COLLECTOR.parse(fixture("osv_BIT-php-2026-109618.json"), LATER_NOW)[0]
        self.assertEqual(item.happened_at, "2026-10-22T08:08:19Z")
        self.assertEqual(item.url, "https://osv.dev/vulnerability/BIT-php-2026-109618")
        self.assertIn('"cves": ["CVE-2026-109618"]', item.raw)
        self.assertIn('["Bitnami", "php"]', item.raw)
        withdrawn = b'{"id": "BIT-x-1", "withdrawn": "2026-10-01T00:00:00Z", "published": "2026-09-01T00:00:00Z"}'
        self.assertEqual(osv.COLLECTOR.parse(withdrawn, LATER_NOW), [])

    @unittest.skipUnless(LIVE, "live")
    def test_live_listing(self):
        payload = Fetcher().get(osv.LISTING)
        self.assertGreater(len(osv.decode(payload, osv.SOURCE)), 1000)


class Epss(unittest.TestCase):
    def test_saved(self):
        items = epss.COLLECTOR.parse(fixture("epss_recent.json"), LATER_NOW)
        self.assertEqual(len(items), 19)
        php = next(i for i in items if i.title.startswith("CVE-2026-109618"))
        self.assertEqual(php.severity, "EPSS 100.0%")
        self.assertEqual(php.happened_at, "2026-10-28T00:00:00Z")

    def test_bad_answers(self):
        for payload in (b'{"status": "ERROR", "data": []}', b'{"status": "OK"}',
                        b'{"status": "OK", "total": 5, "data": []}'):
            with self.assertRaises(ParseError):
                epss.COLLECTOR.parse(payload, LATER_NOW)
        row = '{"cve": "CVE-2026-1234", "epss": "%s", "percentile": "0.5", "date": "2026-10-28"}'
        odd = ('{"status": "OK", "data": [%s, %s]}' % (row % "1.5", row % "0.25")).encode()
        self.assertEqual([i.severity for i in epss.COLLECTOR.parse(odd, LATER_NOW)], ["EPSS 25.0%"])

    def test_the_question_names_no_cve(self):
        self.assertNotIn("cve=", epss.URL)

    @unittest.skipUnless(LIVE, "live")
    def test_live(self):
        self.assertTrue(epss.COLLECTOR.parse(Fetcher().get(epss.URL), datetime.now(timezone.utc)))


class Watchlist(unittest.TestCase):
    def test_names_aliases_and_prefixes(self):
        entries = watchlist.parse("# mine\n\nPHP\nWindows 11 = windows 11*, microsoft windows 11*\nbad = w*, a*b\n")
        self.assertEqual([e.name for e in entries], ["PHP", "Windows 11", "bad"])
        php, win, bad = entries
        self.assertEqual(php.matches("PHP Group", "PHP"), "PHP Group PHP")
        self.assertIsNone(php.matches("thorsten", "phpMyFAQ"))
        self.assertIsNone(php.matches("PHPOffice", "PHPPresentation"))
        self.assertIsNone(php.matches("php", ""))
        self.assertTrue(win.matches("Microsoft", "Windows 11 Version 24H2"))
        self.assertIsNone(win.matches("Microsoft", "Windows 110"))
        self.assertEqual(len(bad.terms), 1)  # "w*" too short, "a*b" not a name: only "bad" itself

    def test_a_missing_or_oversized_file_means_no_entries(self):
        d = temp_dir()
        self.assertEqual(watchlist.load(d / "none.txt"), [])
        big = d / "big.txt"
        big.write_text("x\n" * 40_000, encoding="utf-8")
        self.assertEqual(watchlist.load(big), [])


class Alerts(StoreCase):
    """ROADMAP Task 3 done-when."""

    def test_php2shell_day_alerts_with_php(self):
        self.load(REPLAY_NOW)
        items = self.derive("PHP\n", REPLAY_NOW)
        self.assertEqual(keys(items), PHP2SHELL)
        self.assertTrue(all(i.basis == "inferred" and i.source == "my-stack" for i in items))
        self.assertTrue(all("new vulnerability" in i.title and i.severity == "CVSS 9.2 critical" for i in items))
        self.assertTrue(all("EPSS" not in i.summary for i in items))  # 28 Oct's score is not known on 21 Oct

    def test_php2shell_day_is_silent_without_php(self):
        self.load(REPLAY_NOW)
        self.assertEqual(self.derive(NO_PHP, REPLAY_NOW), [])

    def test_a_quiet_day_gives_none(self):
        # 25 Oct as it was: that day's NVD and the KEV catalogue of 23 Oct.
        self.store.save_items(nvd.COLLECTOR.parse(gz("nvd_pub_2026-10-25.json.gz"), QUIET_NOW))
        self.store.save_items(cisa_kev.COLLECTOR.parse(fixture("cisa_kev.json"), QUIET_NOW))
        self.assertEqual(self.derive("PHP\n" + NO_PHP, QUIET_NOW), [])

    def test_a_quiet_day_adds_nothing_dated_that_day(self):
        self.load(QUIET_NOW, "nvd_pub_2026-10-25.json.gz")  # PHP2Shell is still in the 30-day look-back
        items = self.derive("PHP\n" + NO_PHP, QUIET_NOW)
        self.assertEqual(keys(items), PHP2SHELL)
        self.assertFalse([i for i in items if i.happened_at[:10] == "2026-10-25"])

    def test_no_watchlist_no_alerts(self):
        self.load(REPLAY_NOW)
        self.assertEqual(my_stack.derive(self.store, REPLAY_NOW, self.dir / "missing.txt"), [])

    def test_exploitation_is_a_second_alert(self):
        self.load(LATER_NOW)
        items = self.derive("PHP\n", LATER_NOW)
        exploited = [i for i in items if i.severity == "exploited"]
        self.assertEqual(keys(exploited), PHP2SHELL)
        self.assertEqual({i.happened_at for i in exploited}, {"2026-10-26T00:00:00Z"})
        new = [i for i in items if "new vulnerability" in i.title]
        self.assertTrue(all("osv-bitnami" in i.summary and "EPSS 100.0%" in i.summary for i in new))

    def test_the_cap(self):
        self.load(REPLAY_NOW)
        first = self.derive("Roundcube = roundcube webmail\n", REPLAY_NOW, save=True)
        alerts = [i for i in first if " · " in i.title]
        overflow = [i for i in first if i.title.startswith("+")]
        self.assertEqual(len(alerts), my_stack.CAP_PER_DAY)
        self.assertEqual(len(overflow), 1)
        self.assertTrue(overflow[0].title.startswith(f"+{19 - my_stack.CAP_PER_DAY} more"))
        # Shown alerts stay shown; a later, bigger match that day does not push one out.
        again = self.derive("Roundcube = roundcube webmail\nPHP\n", REPLAY_NOW)
        self.assertEqual({i.id for i in again if " · " in i.title}, {i.id for i in alerts})
        self.assertIn(f"+{19 - my_stack.CAP_PER_DAY + 2} more", next(i.title for i in again if i.title.startswith("+")))


class Wiring(StoreCase):
    def test_a_run_fetches_follows_pages_derives_and_shows_on_the_board(self):
        self.watch("PHP\nSecretProduct\n")
        requested = []
        answers = {
            "services.nvd.nist.gov": gz("nvd_pub_2026-10-21.json.gz"),
            "www.cisa.gov": fixture("cisa_kev.json"),
            "api.first.org": fixture("epss_recent.json"),
        }

        class Fake:
            def get(self, url):
                requested.append(url)
                host = urlsplit(url).hostname
                if url == osv.LISTING:
                    return b"2026-10-22T08:08:19Z,BIT-php-2026-109618\n"
                if host == "storage.googleapis.com":
                    return fixture("osv_BIT-php-2026-109618.json")
                return answers[host]

        collectors = [c for c in all_collectors(self.dir) if c.source != "usgs-quakes"]
        results = run_once(self.store, collectors, Fake(), REPLAY_NOW)
        self.assertTrue(all(r.ok for r in results), results)
        # Fixed questions only: no URL depends on the watchlist, and my-stack fetched nothing.
        self.assertEqual(set(requested), {nvd.url_for(None, REPLAY_NOW)[0], cisa_kev.COLLECTOR.url, epss.URL,
                                          osv.LISTING, f"{osv.BUCKET}/Bitnami/BIT-php-2026-109618.json"})
        self.assertFalse(any("secret" in u.lower() for u in requested))
        board = panel_entries(self.store, Registry(collectors).panel("my-stack"), REPLAY_NOW)
        self.assertEqual({e["title"].split(" · ")[1].split(" — ")[0] for e in board["entries"]}, PHP2SHELL)

    def test_runaway_paging_stops(self):
        from worldwatch import runner

        class Endless:
            calls = 0

            def get(self, url):
                Endless.calls += 1
                if Endless.calls > 2 * runner.MAX_URLS_PER_RUN:  # without the cap: stop the test, not hang
                    raise RuntimeError("no cap")
                return b'{"startIndex": 0, "resultsPerPage": 1, "totalResults": 99, "vulnerabilities": []}'

        loop = nvd.COLLECTOR.__class__(**{**nvd.COLLECTOR.__dict__, "follow": lambda p, u, l, n: [u]})
        result = runner.run_source(self.store, loop, Endless(), REPLAY_NOW)
        self.assertFalse(result.ok)
        self.assertIn("URLs in one run", result.error)


if __name__ == "__main__":
    unittest.main()
