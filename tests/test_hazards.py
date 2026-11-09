"""Task 4's sources against their real producers: a response saved on 2026-11-09, and (WW_LIVE=1) the live feed."""

import gzip
import unittest
from datetime import datetime, timezone

from tests.helpers import LIVE, fixture
from worldwatch.collectors import ParseError, eonet, firms, gdacs, smn, ssn, swpc, usgs
from worldwatch.http import Fetcher

NOW = datetime(2026, 11, 9, 19, 10, tzinfo=timezone.utc)


def gz(name: str) -> bytes:
    return gzip.decompress(fixture(name))


def live(collector):
    now = datetime.now(timezone.utc)
    return collector.parse(Fetcher().get(collector.url), now), now


class Ssn(unittest.TestCase):
    def setUp(self):
        self.items = ssn.COLLECTOR.parse(fixture("ssn_ultimos_2026-11-09.xml"), NOW)

    def test_saved_feed(self):
        self.assertEqual(len(self.items), 15)
        first = self.items[0]
        self.assertEqual(first.title, "M4.1 — 109 km al SUROESTE de HUIXTLA, CHIS")
        self.assertEqual(first.severity, "M4.1")
        self.assertEqual((first.lat, first.lon), (14.406, -93.15))
        self.assertEqual(first.summary, "Profundidad 10 km.")
        self.assertEqual(first.lang, "es")
        self.assertIn("Servicio Sismológico Nacional", first.licence)  # the credit its terms ask for
        self.assertTrue(all(i.url and " " not in i.url for i in self.items))  # raw spaces quoted, link kept

    def test_mexico_time_is_utc_minus_six(self):
        # "Fecha:2026-11-09 12:47:36 (Hora de México)": CDMX has no DST since 2022.
        self.assertEqual(self.items[0].happened_at, "2026-11-09T18:47:36Z")

    def test_one_quake_one_id_whatever_its_place_or_magnitude_says(self):
        revised = fixture("ssn_ultimos_2026-11-09.xml").replace(b"<title>4.1, 109 km", b"<title>4.3, 108 km", 1)
        again = ssn.COLLECTOR.parse(revised, NOW)
        self.assertEqual(again[0].id, self.items[0].id)
        self.assertEqual(again[0].severity, "M4.3")

    def test_an_item_without_a_time_is_skipped_not_fatal(self):
        broken = fixture("ssn_ultimos_2026-11-09.xml").replace(b"Fecha:2026-11-09 12:47:36", b"Fecha:pronto", 1)
        self.assertEqual(len(ssn.COLLECTOR.parse(broken, NOW)), 14)

    def test_a_dtd_or_entity_is_refused(self):
        bomb = b'<?xml version="1.0"?><!DOCTYPE r [<!ENTITY a "aaaa">]><rss><channel></channel></rss>'
        with self.assertRaises(ParseError):
            ssn.COLLECTOR.parse(bomb, NOW)

    def test_not_rss_is_a_parse_error(self):
        for payload in (b"<html><body>mantenimiento</body></html>", b"not xml at all"):
            with self.assertRaises(ParseError):
                ssn.COLLECTOR.parse(payload, NOW)

    @unittest.skipUnless(LIVE, "set WW_LIVE=1 to hit the live feed")
    def test_live(self):
        items, now = live(ssn.COLLECTOR)
        self.assertGreater(len(items), 0)
        newest = max(i.happened_at for i in items)
        self.assertLessEqual(newest, now.strftime("%Y-%m-%dT%H:%M:%SZ"))  # a wrong offset would put it ahead


class Gdacs(unittest.TestCase):
    def setUp(self):
        self.items = gdacs.COLLECTOR.parse(gz("gdacs_events4app_2026-11-09.json.gz"), NOW)

    def test_saved_list(self):
        self.assertEqual(len(self.items), 100)
        quake = self.items[0]
        self.assertEqual(quake.title, "Earthquake in Mid-Indian Ridge")
        self.assertEqual(quake.severity, "Green · Earthquake")
        self.assertIn("Magnitude 4.9M", quake.summary)
        self.assertTrue(quake.url.startswith("https://www.gdacs.org/report.aspx"))
        self.assertEqual((quake.lat, quake.lon), (-28.1856, 74.3713))

    def test_times_are_utc(self):
        # USGS has the same M4.9 Mid-Indian Ridge quake at 15:04:33.79 UTC.
        self.assertEqual(self.items[0].happened_at, "2026-11-09T15:04:33Z")

    def test_alert_level_sets_the_weight(self):
        rows = [{"severity": "Red · Earthquake"}, {"severity": "Orange · Flood"}, {"severity": "Green · Wildfire"}]
        self.assertEqual([gdacs.weight(r) for r in rows], [1.0, 0.65, 0.25])

    def test_one_event_one_id_across_episodes(self):
        data = gz("gdacs_events4app_2026-11-09.json.gz").replace(b'"episodeid":1745598', b'"episodeid":1745599', 1)
        self.assertEqual(gdacs.COLLECTOR.parse(data, NOW)[0].id, self.items[0].id)

    def test_not_geojson_is_a_parse_error(self):
        with self.assertRaises(ParseError):
            gdacs.COLLECTOR.parse(b'{"error": "maintenance"}', NOW)

    @unittest.skipUnless(LIVE, "set WW_LIVE=1 to hit the live feed")
    def test_live(self):
        items, _ = live(gdacs.COLLECTOR)
        self.assertGreater(len(items), 0)
        self.assertTrue(all(i.lat is not None for i in items))


class Eonet(unittest.TestCase):
    def setUp(self):
        self.items = eonet.COLLECTOR.parse(gz("eonet_open_2026-11-09.json.gz"), NOW)

    def test_saved_events(self):
        self.assertEqual(len(self.items), 38)
        storm = self.items[0]
        self.assertEqual(storm.title, "Tropical Cyclone 03S")
        # five dated positions: the newest places it
        self.assertEqual(storm.happened_at, "2026-11-08T18:00:00Z")
        self.assertEqual((storm.lat, storm.lon), (-11.3, 50.5))
        self.assertEqual(storm.severity, "Severe Storms · 25 kts")

    def test_a_polygon_is_placed_at_its_corners_mean(self):
        self.assertEqual(eonet._point({"type": "Polygon", "coordinates": [[[0, 0], [2, 0], [2, 4], [0, 4]]]}), (2.0, 1.0))

    def test_no_events_list_is_a_parse_error(self):
        with self.assertRaises(ParseError):
            eonet.COLLECTOR.parse(b'{"title": "EONET Events"}', NOW)

    @unittest.skipUnless(LIVE, "set WW_LIVE=1 to hit the live feed")
    def test_live(self):
        items, _ = live(eonet.COLLECTOR)
        self.assertGreater(len(items), 0)


class Firms(unittest.TestCase):
    def setUp(self):
        self.items = firms.COLLECTOR.parse(gz("firms_j1_central_america_24h_2026-11-09.csv.gz"), NOW)

    def test_saved_file_keeps_the_mexico_box_and_confident_detections(self):
        # 1,150 rows: 519 inside the box, 514 of them nominal or high confidence.
        self.assertEqual(len(self.items), 514)
        self.assertTrue(all(usgs.near_mexico(i.lat, i.lon) for i in self.items))
        first = self.items[0]
        self.assertEqual(first.happened_at, "2026-11-08T07:33:00Z")  # acq_date + acq_time, UTC
        self.assertEqual(first.severity, "FRP 0.54 MW")

    def test_low_confidence_is_dropped(self):
        rows = firms.decode_csv(gz("firms_j1_central_america_24h_2026-11-09.csv.gz"), firms.SOURCE)
        low = [r for r in rows if r["confidence"] == "low" and usgs.near_mexico(float(r["latitude"]), float(r["longitude"]))]
        self.assertTrue(low)
        ids = {i.id for i in self.items}
        self.assertFalse(any(firms._build(r, NOW).id in ids for r in low))

    def test_bigger_fires_weigh_more(self):
        self.assertLess(firms.weight({"severity": "FRP 1 MW"}), firms.weight({"severity": "FRP 80 MW"}))
        self.assertEqual(firms.weight({"severity": "FRP 900 MW"}), 1.0)

    def test_not_the_firms_csv_is_a_parse_error(self):
        for payload in (b'{"error": "Invalid MAP_KEY."}', b"<html>Not Found</html>"):
            with self.assertRaises(ParseError):
                firms.COLLECTOR.parse(payload, NOW)

    @unittest.skipUnless(LIVE, "set WW_LIVE=1 to hit the live feed")
    def test_live(self):
        items, _ = live(firms.COLLECTOR)
        self.assertGreater(len(items), 0)


class Swpc(unittest.TestCase):
    def setUp(self):
        self.items = swpc.COLLECTOR.parse(gz("swpc_alerts_2026-11-09.json.gz"), NOW)

    def test_saved_messages(self):
        self.assertEqual(len(self.items), 71)
        first = self.items[0]
        self.assertEqual(first.title, "EXTENDED WARNING: Geomagnetic K-index of 4 expected")
        self.assertEqual(first.happened_at, "2026-11-09T17:55:46Z")
        self.assertIn("Now Valid Until: 2026 Nov 10 0600 UTC", first.summary)
        self.assertNotIn("Serial Number: 5452", first.summary)  # the header is not the news
        self.assertIsNone(first.lat)  # space weather is a panel, not a point

    def test_noaa_scale_is_the_severity_when_given(self):
        scaled = [i for i in self.items if i.severity and i.severity[:1] in "GSR" and i.severity[1:].isdigit()]
        self.assertTrue(scaled)

    def test_ids_are_product_and_serial(self):
        self.assertEqual(len({i.id for i in self.items}), 71)

    def test_not_a_list_is_a_parse_error(self):
        with self.assertRaises(ParseError):
            swpc.COLLECTOR.parse(b'{"message": "down"}', NOW)

    @unittest.skipUnless(LIVE, "set WW_LIVE=1 to hit the live feed")
    def test_live(self):
        items, _ = live(swpc.COLLECTOR)
        self.assertGreater(len(items), 0)


class Smn(unittest.TestCase):
    def setUp(self):
        self.items = smn.COLLECTOR.parse(fixture("smn_daily_forecast_2026-11-09.gz"), NOW)

    def test_saved_file_keeps_cdmx_only(self):
        self.assertEqual(len(self.items), 64)  # 16 alcaldías x 4 days, of 9,852 municipality-days
        first = self.items[0]
        self.assertEqual(first.title, "Azcapotzalco: 11–24 °C, Medio nublado")
        self.assertEqual(first.lang, "es")

    def test_a_forecast_is_dated_at_its_days_start_in_cdmx(self):
        self.assertEqual(self.items[0].happened_at, "2026-11-09T06:00:00Z")

    def test_a_gzip_bomb_stops_at_the_cap(self):
        bomb = gzip.compress(b"[" + b" " * (smn.MAX_UNPACKED + 10) + b"]")
        with self.assertRaises(ParseError):
            smn.COLLECTOR.parse(bomb, NOW)

    def test_not_gzip_is_a_parse_error(self):
        with self.assertRaises(ParseError):
            smn.COLLECTOR.parse(b"<html>Servicio no disponible</html>", NOW)

    @unittest.skipUnless(LIVE, "set WW_LIVE=1 to hit the live feed")
    def test_live(self):
        items, _ = live(smn.COLLECTOR)
        self.assertGreaterEqual(len(items), 16)


if __name__ == "__main__":
    unittest.main()
