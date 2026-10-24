"""Each collector against the real feed: a response saved once, and (with WW_LIVE=1) the live feed."""

import json
import unittest

from tests.helpers import LIVE, NOW, fixture
from worldwatch.collectors import ParseError, cisa_kev, gdelt, usgs
from worldwatch.http import Fetcher, RateLimited


class Usgs(unittest.TestCase):
    def test_saved_week_feed(self):
        payload = fixture("usgs_2.5_week.geojson")
        raw = json.loads(payload.decode("utf-8"))
        items = usgs.COLLECTOR.parse(payload, NOW)
        self.assertGreater(len(items), 10)
        self.assertLess(len(items), raw["metadata"]["count"])  # M2.5–3.5 far from Mexico is dropped
        for item in items:
            self.assertEqual(item.source, "usgs-quakes")
            self.assertTrue(item.url.startswith("https://earthquake.usgs.gov/"))
            self.assertTrue(item.severity.startswith("M"))
            self.assertIsNotNone(item.lat)
            mag = float(item.severity[1:].split()[0])
            sig = json.loads(item.raw)["properties"].get("sig") or 0
            self.assertTrue(mag >= 4.5 or item.country == "MX" or sig >= 600, item.title)

    def test_time_is_the_event_not_the_fetch(self):
        items = usgs.COLLECTOR.parse(fixture("usgs_4.5_day.geojson"), NOW)
        first = json.loads(items[0].raw)
        self.assertNotEqual(items[0].happened_at, items[0].fetched_at)
        self.assertEqual(items[0].fetched_at, "2026-10-23T23:50:00Z")
        self.assertTrue(first["properties"]["time"] > 0)

    def test_filter_rules(self):
        self.assertTrue(usgs.keep(4.5, 0, 0.0, 0.0))
        self.assertFalse(usgs.keep(4.4, 0, 0.0, 0.0))
        self.assertTrue(usgs.keep(3.5, 0, 19.4, -99.1))  # CDMX
        self.assertFalse(usgs.keep(3.4, 0, 19.4, -99.1))
        self.assertTrue(usgs.keep(2.6, 650, 0.0, 0.0))
        self.assertFalse(usgs.keep(None, 0, 19.4, -99.1))

    def test_not_geojson_is_a_parse_error(self):
        with self.assertRaises(ParseError):
            usgs.COLLECTOR.parse(b'{"type": "Feature"}', NOW)
        with self.assertRaises(ParseError):
            usgs.COLLECTOR.parse(b"<html>maintenance</html>", NOW)

    def test_a_malformed_feature_is_skipped_not_fatal(self):
        payload = json.dumps({"type": "FeatureCollection", "features": [
            {"id": "bad", "properties": {"mag": 6.0}},  # no geometry
            {"id": "ok", "properties": {"mag": 6.0, "time": 1792795371088, "title": "M 6.0 - x", "url": "https://earthquake.usgs.gov/x"},
             "geometry": {"coordinates": [10.0, 10.0, 5.0]}},
        ]}).encode()
        items = usgs.COLLECTOR.parse(payload, NOW)
        self.assertEqual([i.title for i in items], ["M 6.0 - x"])

    @unittest.skipUnless(LIVE, "set WW_LIVE=1 to hit the live feed")
    def test_live(self):
        items = usgs.COLLECTOR.parse(Fetcher().get(usgs.COLLECTOR.url), NOW)
        self.assertGreater(len(items), 0)


class Kev(unittest.TestCase):
    def test_saved_catalogue(self):
        payload = fixture("cisa_kev.json")
        raw = json.loads(payload.decode("utf-8"))
        items = cisa_kev.COLLECTOR.parse(payload, NOW)
        self.assertEqual(len(items), raw["count"])
        self.assertEqual(len({i.id for i in items}), len(items))
        sample = items[-1]
        self.assertTrue(sample.title.startswith("CVE-"))
        self.assertTrue(sample.url.startswith("https://www.cve.org/CVERecord?id=CVE-"))
        self.assertEqual(sample.licence, cisa_kev.LICENCE)
        ransomware = [i for i in items if i.severity == "ransomware: known"]
        expected = sum(1 for v in raw["vulnerabilities"] if v["knownRansomwareCampaignUse"] == "Known")
        self.assertEqual(len(ransomware), expected)

    def test_bad_cve_id_is_skipped(self):
        payload = json.dumps({"vulnerabilities": [
            {"cveID": "CVE-2026-1234", "dateAdded": "2026-10-01", "vulnerabilityName": "ok"},
            {"cveID": "javascript:alert(1)", "dateAdded": "2026-10-01", "vulnerabilityName": "bad"},
        ]}).encode()
        self.assertEqual([i.title for i in cisa_kev.COLLECTOR.parse(payload, NOW)], ["CVE-2026-1234 — ok"])

    def test_missing_list_is_a_parse_error(self):
        with self.assertRaises(ParseError):
            cisa_kev.COLLECTOR.parse(b'{"count": 0}', NOW)

    @unittest.skipUnless(LIVE, "set WW_LIVE=1 to hit the live feed")
    def test_live(self):
        items = cisa_kev.COLLECTOR.parse(Fetcher().get(cisa_kev.COLLECTOR.url), NOW)
        self.assertGreater(len(items), 1000)


class Gdelt(unittest.TestCase):
    def test_saved_article_list(self):
        payload = fixture("gdelt_artlist.json")
        items = gdelt.COLLECTORS[0].parse(payload, NOW)
        self.assertEqual(len(items), len(json.loads(payload.decode("utf-8"))["articles"]))
        self.assertEqual(items[0].happened_at, "2026-10-23T23:30:00Z")
        self.assertEqual(items[0].lang, "en")
        self.assertTrue(items[0].url.startswith("https://"))
        self.assertIn("gdeltproject.org", items[0].licence)

    def test_empty_result_is_no_items_not_an_error(self):
        self.assertEqual(gdelt.COLLECTORS[0].parse(b"{}", NOW), [])

    def test_rate_limit_text_is_a_parse_error(self):
        with self.assertRaises(ParseError):
            gdelt.COLLECTORS[0].parse(b"Please limit requests to one every 5 seconds", NOW)

    def test_spanish_maps_to_es(self):
        payload = json.dumps({"articles": [{"url": "https://www.jornada.com.mx/a", "title": "Sismo en Oaxaca",
                                            "seendate": "20261023T120000Z", "domain": "jornada.com.mx",
                                            "language": "Spanish", "sourcecountry": "Mexico"}]}).encode()
        self.assertEqual(gdelt.COLLECTORS[1].parse(payload, NOW)[0].lang, "es")

    def test_queries_are_encoded(self):
        self.assertIn("query=sourcecountry%3Amexico+sourcelang%3Aspanish", gdelt.COLLECTORS[1].url)

    @unittest.skipUnless(LIVE, "set WW_LIVE=1 to hit the live feed")
    def test_live(self):
        try:
            items = gdelt.COLLECTORS[1].parse(Fetcher().get(gdelt.COLLECTORS[1].url), NOW)
        except RateLimited:
            self.skipTest("GDELT answered 429 — expected now and then; the runner backs off")
        self.assertGreater(len(items), 0)


if __name__ == "__main__":
    unittest.main()
