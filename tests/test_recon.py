import base64
import hashlib
import re
import unittest
from datetime import datetime, timedelta, timezone

from tests.helpers import NOW, sample_item, temp_dir
from worldwatch import recon
from worldwatch.collectors import Collector
from worldwatch.store import Store

HOUR = timedelta(hours=1)


def coll(source, interval_s=3600):
    return Collector(source=source, channel="x", url=f"https://example.org/{source}", interval_s=interval_s,
                     licence="t", parse_records=lambda d, f: [])


SOURCES = [coll("usgs-quakes", 900), coll("cisa-kev", 6 * 3600), coll("gdelt-aljazeera"), coll("gdelt-mx")]


def quake(n, mag, hours_ago, mx=False):
    lat, lon = (17.0, -100.0) if mx else (-15.0, 168.0)
    return sample_item(n, source="usgs-quakes", channel="hazards", title=f"M {mag} - quake {n}",
                       severity=f"M{mag:.1f}", happened_at=NOW - hours_ago * HOUR, lat=lat, lon=lon,
                       country="MX" if mx else None)


class ReconBuild(unittest.TestCase):
    def setUp(self):
        self.out = temp_dir()
        self.store = Store(self.out / "ww.sqlite3")
        for c in SOURCES:
            self.store.record_run(c.source, NOW, NOW, ok=True, n_items=1, error=None,
                                  next_due="2026-10-24T00:00:00Z", fail_count=0)

    def tearDown(self):
        self.store.close()

    def build(self, now=NOW):
        html_path, md_path = recon.build(self.store, SOURCES, now, self.out)
        return html_path.read_text(encoding="utf-8"), md_path.read_text(encoding="utf-8")

    def test_hostile_text_is_escaped_and_bad_links_dropped(self):
        evil = sample_item(1, source="gdelt-aljazeera", title='<script>alert(1)</script>" onmouseover="x',
                           url="javascript:alert(1)")
        # make_item strips tags; force raw markup through to prove the renderer escapes too
        from dataclasses import replace
        evil = replace(evil, title='<img src=x onerror=alert(1)>" onmouseover="x')
        self.store.save_items([evil])
        page, md = self.build()
        self.assertNotIn("<img", page)
        self.assertIn("&lt;img src=x onerror=alert(1)&gt;&quot; onmouseover=&quot;x", page)
        self.assertNotIn("javascript:", page)
        self.assertNotRegex(md, r"(?<!\\)<img")  # only the escaped \<img, which renders as text
        self.assertIn(r"\<img", md)

    def test_renderer_rechecks_link_schemes(self):
        from dataclasses import replace
        sneaky = replace(sample_item(1, source="gdelt-aljazeera", title="Sneaky"), url="javascript:alert(1)")
        self.store.save_items([sneaky])
        page, md = self.build()
        self.assertIn("Sneaky", page)
        self.assertNotIn("javascript:", page)
        self.assertNotIn("javascript:", md)

    def test_no_temp_files_left_behind(self):
        self.build()
        self.assertEqual(list(self.out.glob("*.tmp")), [])

    def test_self_contained_with_a_matching_csp(self):
        page, _ = self.build()
        self.assertNotRegex(page, r"(?i)<(link|img|iframe|object|embed)\b")
        self.assertNotRegex(page, r"(?i)\bsrc\s*=")
        self.assertNotRegex(page, r"(?i)@import|url\(")
        scripts = re.findall(r"<script>(.*?)</script>", page, re.S)
        self.assertEqual(len(scripts), 1)
        digest = base64.b64encode(hashlib.sha256(scripts[0].encode("utf-8")).digest()).decode()
        self.assertIn(f"script-src 'sha256-{digest}'", page)
        self.assertIn("default-src 'none'", page)

    def test_every_item_shows_source_event_time_and_fetch_time(self):
        self.store.save_items([sample_item(1, source="gdelt-aljazeera", title="Ceasefire talks",
                                           happened_at=NOW - 2 * HOUR, fetched_at=NOW - HOUR)])
        page, md = self.build()
        block = page[page.index("Ceasefire talks"):][:900]
        self.assertIn("gdelt-aljazeera", block)
        self.assertIn("23 Oct 15:50", block)   # event, Mexico City time (UTC-6)
        self.assertIn("23 Oct 16:50", block)   # fetched
        self.assertIn("reported", block)
        md_block = md[md.index("Ceasefire talks"):][:400]
        self.assertIn("23 Oct 15:50", md_block)
        self.assertIn("23 Oct 16:50", md_block)

    def test_date_only_sources_show_their_date_not_a_shifted_time(self):
        added = datetime(2026, 10, 23, tzinfo=timezone.utc)  # KEV gives a date: stored as 00:00 UTC
        self.store.save_items([sample_item(1, source="cisa-kev", channel="security",
                                           title="CVE-2026-0003 — x", happened_at=added)])
        page, md = self.build()
        block = page[page.index("CVE-2026-0003"):][:900]
        self.assertIn("23 Oct", block)
        self.assertNotIn("22 Oct 18:00", block)  # midnight UTC shown as CDMX time would be the day before
        self.assertNotIn("22 Oct 18:00", md)

    def test_mexico_group_says_what_it_is(self):
        page, _ = self.build()
        self.assertIn("Mexico (USGS place)", page)
        self.assertNotIn("World, M4.5+", page)

    def test_quakes_last_24h_mexico_first_then_by_magnitude(self):
        self.store.save_items([quake(1, 5.0, 2), quake(2, 6.1, 3), quake(3, 3.9, 1, mx=True),
                               quake(4, 7.0, 30)])
        page, _ = self.build()
        self.assertNotIn("quake 4", page)  # 30 h old
        order = [page.index(f"quake {n}") for n in (3, 2, 1)]
        self.assertEqual(order, sorted(order))

    def test_kev_last_7_days_only(self):
        self.store.save_items([
            sample_item(1, source="cisa-kev", channel="security", title="CVE-2026-0001 — new", happened_at=NOW - 2 * 24 * HOUR),
            sample_item(2, source="cisa-kev", channel="security", title="CVE-2026-0002 — old", happened_at=NOW - 9 * 24 * HOUR),
        ])
        page, md = self.build()
        self.assertIn("CVE-2026-0001", page)
        self.assertNotIn("CVE-2026-0002", page)
        self.assertNotIn("CVE-2026-0002", md)

    def test_news_split_by_language_with_a_toggle(self):
        self.store.save_items([
            sample_item(1, source="gdelt-aljazeera", title="English headline", lang="en"),
            sample_item(2, source="gdelt-mx", title="Titular en español", lang="es"),
        ])
        page, _ = self.build()
        self.assertIn('data-news-lang="en"', page)
        self.assertIn('data-news-lang="es"', page)
        self.assertIn("English headline", page)
        self.assertIn("Titular en español", page)
        self.assertIn('id="lang-toggle"', page)
        self.assertRegex(page, r'<span class="i18n" lang="es">[^<]+</span>')

    def test_stale_and_never_fetched_sources_are_flagged(self):
        self.store.record_run("gdelt-mx", NOW - 10 * HOUR, NOW - 10 * HOUR, ok=True, n_items=1, error=None,
                              next_due="2026-10-24T00:00:00Z", fail_count=0)
        self.store.record_run("gdelt-mx", NOW, NOW, ok=False, n_items=0, error="429 from api.gdeltproject.org",
                              next_due="2026-10-24T00:00:00Z", fail_count=4)
        self.store.db.execute("DELETE FROM source_state WHERE source = 'cisa-kev'")
        self.store.db.commit()
        page, md = self.build()
        status = page[page.index('id="sources"'):]
        self.assertRegex(status, r"gdelt-mx[\s\S]{0,400}stale")
        self.assertRegex(status, r"cisa-kev[\s\S]{0,400}never")
        self.assertNotRegex(status, r"usgs-quakes[^\n]{0,200}stale")
        self.assertIn("stale", md)

    def test_parked_sources_leave_no_trace(self):
        self.store.save_items([sample_item(1, source="gdelt-mx", title="Old headline", lang="es")])
        html_path, md_path = recon.build(self.store, SOURCES[:2], NOW, self.out)  # GDELT parked
        page, md = html_path.read_text(encoding="utf-8"), md_path.read_text(encoding="utf-8")
        for text in (page, md):
            self.assertNotIn("gdelt", text)
            self.assertNotIn("Old headline", text)
            self.assertIn("U.S. Geological Survey", text)
        self.assertNotIn('id="news"', page)
        self.assertNotIn('data-news-lang="', page)  # the toggle script names it; no element carries it

    def test_empty_store_still_builds(self):
        page, md = self.build()
        self.assertIn("Nothing yet", page)
        self.assertIn("Morning Recon", md)

    def test_file_named_by_mexico_city_date(self):
        late = datetime(2026, 10, 24, 3, 0, tzinfo=timezone.utc)  # 21:00 on the 23rd in CDMX
        html_path, md_path = recon.build(self.store, SOURCES, late, self.out)
        self.assertEqual(html_path.name, "recon-2026-10-23.html")
        self.assertEqual(md_path.name, "recon-2026-10-23.md")
        self.assertTrue((self.out / "recon-latest.html").exists())

    def test_markdown_escapes_link_syntax(self):
        self.store.save_items([sample_item(1, source="gdelt-aljazeera", title="A [fake](http://x) *bold*",
                                           url="https://example.org/a_(b)")])
        _, md = self.build()
        self.assertIn(r"A \[fake\]\(http://x\) \*bold\*", md)
        self.assertIn("(https://example.org/a_%28b%29)", md)

    def test_markdown_url_backslash_cannot_escape_the_link(self):
        from worldwatch.recon_md import md_url
        self.assertEqual(md_url("https://example.org/a\\"), "https://example.org/a%5C")

    def test_phone_ready_basics(self):
        page, _ = self.build()
        self.assertIn('name="viewport" content="width=device-width, initial-scale=1"', page)
        self.assertIn("prefers-color-scheme: dark", page)
        self.assertIn("overflow-wrap: anywhere", page)
        self.assertIn("min-height: 44px", page)

    def test_credits_each_source(self):
        page, md = self.build()
        for credit in ("U.S. Geological Survey", "gdeltproject.org", "CISA"):
            self.assertIn(credit, page)
            self.assertIn(credit, md)


if __name__ == "__main__":
    unittest.main()
