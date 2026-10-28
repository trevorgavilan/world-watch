"""Each collector against the real feed: a response saved once, and (with WW_LIVE=1) the live feed."""

import json
import unittest
from datetime import datetime, timedelta, timezone
from urllib.parse import parse_qs, urlsplit

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
            self.assertTrue(mag >= 4.5 or usgs.near_mexico(item.lat, item.lon) or sig >= 600, item.title)
            place = json.loads(item.raw)["properties"].get("place") or ""
            in_mexico = place.endswith("Mexico") and not place.endswith("New Mexico")
            self.assertEqual(item.country == "MX", in_mexico, place)

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

    def test_impossible_time_skips_that_record_only(self):
        good = {"id": "ok", "properties": {"mag": 6.0, "time": 1792795371088, "title": "M 6.0 - x"},
                "geometry": {"coordinates": [10.0, 10.0, 5.0]}}
        bad = {"id": "bad", "properties": {"mag": 6.0, "time": 1e30, "title": "M 6.0 - y"},
               "geometry": {"coordinates": [10.0, 10.0, 5.0]}}
        payload = json.dumps({"type": "FeatureCollection", "features": [bad, good]}).encode()
        self.assertEqual([i.title for i in usgs.COLLECTOR.parse(payload, NOW)], ["M 6.0 - x"])
        payload = payload.replace(b"1e+30", b"Infinity")
        self.assertEqual([i.title for i in usgs.COLLECTOR.parse(payload, NOW)], ["M 6.0 - x"])

    def test_mexico_is_the_sources_own_place_text_not_our_box(self):
        def feature(place, lat, lon):
            return {"id": place, "properties": {"mag": 3.6, "time": 1792795371088, "title": f"M 3.6 - {place}",
                                                "place": place}, "geometry": {"coordinates": [lon, lat, 5.0]}}
        payload = json.dumps({"type": "FeatureCollection", "features": [
            feature("10 km N of El Paso, Texas", 31.9, -106.4),
            feature("12 km SW of Pinotepa Nacional, Mexico", 16.3, -98.1),
        ]}).encode()
        items = {i.title: i for i in usgs.COLLECTOR.parse(payload, NOW)}
        self.assertIsNone(items["M 3.6 - 10 km N of El Paso, Texas"].country)  # kept by the box, not called Mexico
        self.assertEqual(items["M 3.6 - 12 km SW of Pinotepa Nacional, Mexico"].country, "MX")
        self.assertTrue(all(i.basis == "reported" for i in items.values()))

    @unittest.skipUnless(LIVE, "set WW_LIVE=1 to hit the live feed")
    def test_live(self):
        items = usgs.COLLECTOR.parse(Fetcher().get(usgs.COLLECTOR.url), NOW)
        self.assertGreater(len(items), 0)


class UsgsCatchUp(unittest.TestCase):
    """The PC is switched on whenever Trevor likes: after a gap longer than the week feed covers,
    the catalogue query fetches everything since the last good fetch."""

    def queries(self, urls):
        out = []
        for url in urls:
            parts = urlsplit(url)
            self.assertEqual(f"{parts.scheme}://{parts.netloc}{parts.path}", usgs.QUERY_URL)
            out.append({k: v[0] for k, v in parse_qs(parts.query).items()})
        return out

    def test_first_run_and_short_gaps_use_the_week_feed(self):
        self.assertEqual(usgs.COLLECTOR.fetch_urls(None, NOW), [usgs.WEEK_URL])
        self.assertEqual(usgs.COLLECTOR.fetch_urls(NOW - timedelta(days=2), NOW), [usgs.WEEK_URL])
        self.assertEqual(usgs.COLLECTOR.fetch_urls(NOW - usgs.CATCH_UP_AFTER, NOW), [usgs.WEEK_URL])

    def test_a_clock_that_ran_ahead_uses_the_week_feed(self):
        self.assertEqual(usgs.COLLECTOR.fetch_urls(NOW + timedelta(days=30), NOW), [usgs.WEEK_URL])

    def test_a_long_gap_queries_what_keep_wants_from_a_day_before_the_last_fetch(self):
        last_ok = NOW - timedelta(days=10)
        world, mexico = self.queries(usgs.COLLECTOR.fetch_urls(last_ok, NOW))
        self.assertEqual(usgs.CATCH_UP_MARGIN, timedelta(days=1))  # USGS publishes some quakes late
        for q in (world, mexico):
            self.assertEqual(q["starttime"], (last_ok - usgs.CATCH_UP_MARGIN).strftime("%Y-%m-%dT%H:%M:%SZ"))
            self.assertEqual(q["format"], "geojson")
            self.assertEqual(q["orderby"], "time-asc")
            self.assertNotIn("endtime", q)
        self.assertEqual(float(world["minmagnitude"]), usgs.GLOBAL_MIN_MAG)
        self.assertNotIn("minlatitude", world)
        self.assertEqual(float(mexico["minmagnitude"]), usgs.MEXICO_MIN_MAG)
        box = tuple(float(mexico[k]) for k in ("minlatitude", "maxlatitude", "minlongitude", "maxlongitude"))
        self.assertEqual(box, usgs.MEXICO_BOX)

    def test_just_past_the_week_feed_already_queries(self):
        urls = usgs.COLLECTOR.fetch_urls(NOW - usgs.CATCH_UP_AFTER - timedelta(minutes=1), NOW)
        self.assertTrue(all(u.startswith(usgs.QUERY_URL) for u in urls))

    def test_a_very_long_gap_is_capped(self):
        for q in self.queries(usgs.COLLECTOR.fetch_urls(NOW - timedelta(days=3 * 365), NOW)):
            self.assertEqual(q["starttime"], (NOW - usgs.CATCH_UP_MAX).strftime("%Y-%m-%dT%H:%M:%SZ"))

    def test_starttime_is_utc_whatever_zone_the_times_carry(self):
        cdmx = timezone(timedelta(hours=-6))
        urls = usgs.COLLECTOR.fetch_urls((NOW - timedelta(days=10)).astimezone(cdmx), NOW.astimezone(cdmx))
        self.assertEqual(self.queries(urls)[0]["starttime"], (NOW - timedelta(days=11)).strftime("%Y-%m-%dT%H:%M:%SZ"))

    def test_saved_query_responses(self):
        for name in ("usgs_query_global.geojson", "usgs_query_mexico.geojson"):
            payload = fixture(name)
            raw = json.loads(payload.decode("utf-8"))
            items = usgs.COLLECTOR.parse(payload, NOW)
            self.assertGreater(len(items), 0, name)
            self.assertEqual(len(items), len(raw["features"]), name)  # each query asks only for what `keep` wants
            self.assertTrue(all(i.source == "usgs-quakes" for i in items))

    @unittest.skipUnless(LIVE, "set WW_LIVE=1 to hit the live feed")
    def test_live_query(self):
        now = datetime.now(timezone.utc)
        for url in usgs.COLLECTOR.fetch_urls(now - timedelta(days=9), now):
            self.assertIsInstance(usgs.COLLECTOR.parse(Fetcher().get(url), now), list)

    @unittest.skipUnless(LIVE, "set WW_LIVE=1 to hit the live feed")
    def test_live_a_full_year_stays_far_under_the_query_cap(self):
        now = datetime.now(timezone.utc)
        for url in usgs.COLLECTOR.fetch_urls(now - timedelta(days=3 * 365), now):
            count_url = url.replace("/query?", "/count?")
            answer = json.loads(Fetcher().get(count_url).decode("utf-8"))
            self.assertLess(answer["count"], 0.7 * answer["maxAllowed"], count_url)


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

    def test_rate_limit_text_with_200_is_rate_limited(self):
        with self.assertRaises(RateLimited):
            gdelt.COLLECTORS[0].parse(b"Please limit requests to one every 5 seconds or contact ...", NOW)

    def test_other_text_is_a_parse_error(self):
        with self.assertRaises(ParseError):
            gdelt.COLLECTORS[0].parse(b"Your search contained an invalid operator", NOW)

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
