"""A quake near CDMX appears within one poll and raises one alert (Task 4's done-when, D-22).

The feeds are the real saved responses (SSN's RSS of 2026-11-09, USGS's week feed) with one quake
under the city written in the producers' own format, then run through the real runner.
"""

import json
import unittest
from datetime import datetime, timedelta, timezone

from tests.helpers import fixture, temp_dir
from tests.test_runner import FakeFetcher
from worldwatch import recon, runner
from worldwatch.collectors import cdmx, near_cdmx, ssn, usgs
from worldwatch.store import Store

NOW = datetime(2026, 11, 9, 19, 10, tzinfo=timezone.utc)
SSN_FIRST = (b"<title>4.1, 109 km al SUROESTE de  HUIXTLA, CHIS</title>", b"Fecha:2026-11-09 12:47:36",
             b"<geo:lat>14.406</geo:lat>", b"<geo:long>-93.15</geo:long>")


def ssn_feed(mag="2.9", place="4 km al SUR de  ALVARO OBREGON, CDMX", local="2026-11-09 12:52:10",
             lat="19.335", lon="-99.214") -> bytes:
    """The saved feed with its newest item moved: SSN's own format, our quake."""
    data = fixture("ssn_ultimos_2026-11-09.xml")
    for old, new in zip(SSN_FIRST, (f"<title>{mag}, {place}</title>".encode(), f"Fecha:{local}".encode(),
                                    f"<geo:lat>{lat}</geo:lat>".encode(), f"<geo:long>{lon}</geo:long>".encode())):
        assert old in data
        data = data.replace(old, new, 1)
    return data


def usgs_feed(*quakes) -> bytes:
    """The saved week feed plus quakes (id, mag, lat, lon, UTC time) cloned from its first feature."""
    data = json.loads(fixture("usgs_2.5_week.geojson"))
    template = data["features"][0]
    for qid, mag, lat, lon, when in quakes:
        feature = json.loads(json.dumps(template))
        feature["id"] = qid
        feature["geometry"]["coordinates"] = [lon, lat, 10.0]
        props = feature["properties"]
        props.update(mag=mag, time=int(when.timestamp() * 1000), sig=100, alert=None, tsunami=0,
                     place="5 km SW of Mexico City, Mexico", title=f"M {mag} - 5 km SW of Mexico City, Mexico",
                     url=f"https://earthquake.usgs.gov/earthquakes/eventpage/{qid}")
        data["features"].append(feature)
    return json.dumps(data).encode()


QUAKE_UTC = datetime(2026, 11, 9, 18, 52, 12, tzinfo=timezone.utc)  # SSN's 12:52:10 local, USGS 2 s later


class Rule(unittest.TestCase):
    def test_distance(self):
        self.assertAlmostEqual(cdmx.km_from_cdmx(cdmx.CDMX_LAT, cdmx.CDMX_LON), 0.0)
        # Acapulco is ~300 km from the Zócalo
        self.assertTrue(280 < cdmx.km_from_cdmx(16.85, -99.88) < 320)

    def test_bands(self):
        cases = [  # (mag, lat, lon, expected)
            (2.5, 19.33, -99.21, True),    # under the city
            (2.4, 19.33, -99.21, False),
            (4.9, 16.85, -99.88, False),   # Acapulco, ~300 km
            (5.0, 16.85, -99.88, True),
            (5.9, 16.20, -95.20, False),   # Salina Cruz, ~550 km
            (6.0, 16.20, -95.20, True),
            (6.9, 15.00, -93.00, False),   # off Chiapas, ~800 km
            (7.0, 15.00, -93.00, True),
            (8.5, 40.0, -125.0, False),    # far away: never, whatever its size
        ]
        for mag, lat, lon, expected in cases:
            self.assertEqual(cdmx.near_cdmx(mag, lat, lon), expected, (mag, lat, lon))

    def test_unknowns_never_alert(self):
        for mag, lat, lon in ((None, 19.4, -99.1), (float("nan"), 19.4, -99.1), (3.0, None, -99.1), (True, 19.4, -99.1)):
            self.assertFalse(cdmx.near_cdmx(mag, lat, lon))

    def test_usgs_keeps_a_small_quake_under_the_city(self):
        self.assertTrue(usgs.keep(2.6, None, 19.33, -99.21))
        self.assertFalse(usgs.keep(2.6, None, 17.0, -100.0))  # small and far: still dropped


class OnePoll(unittest.TestCase):
    def setUp(self):
        self.store = Store(temp_dir() / "ww.sqlite3")
        self.collectors = [near_cdmx.COLLECTOR, usgs.COLLECTOR, ssn.COLLECTOR]

    def poll(self, now, *, ssn_payload=None, usgs_payload=None):
        answers = {ssn.URL: ssn_payload or fixture("ssn_ultimos_2026-11-09.xml"),
                   usgs.WEEK_URL: usgs_payload or usgs_feed()}
        return runner.run_once(self.store, self.collectors, FakeFetcher(answers), now)

    def alerts(self, now=NOW):
        return self.store.items_between(near_cdmx.SOURCE, "2026-01-01T00:00:00Z", (now + timedelta(days=1)).strftime("%Y-%m-%dT%H:%M:%SZ"))

    def city_alerts(self, now=NOW):
        return [a for a in self.alerts(now) if "km from CDMX" in a["title"] and a["happened_at"].startswith("2026-11-09T18:52")]

    def test_a_quake_near_cdmx_raises_one_alert_in_the_same_poll(self):
        results = self.poll(NOW, ssn_payload=ssn_feed(), usgs_payload=usgs_feed(("us7000cdmx", 3.1, 19.34, -99.20, QUAKE_UTC)))
        self.assertTrue(all(r.ok for r in results), results)
        alerts = self.city_alerts()
        self.assertEqual(len(alerts), 1, [a["title"] for a in alerts])  # SSN and USGS: one quake
        alert = alerts[0]
        self.assertEqual(alert["title"], "Quake M2.9, 14 km from CDMX — 4 km al SUR de ALVARO OBREGON, CDMX")
        self.assertEqual(alert["basis"], "inferred")
        self.assertEqual(alert["happened_at"], "2026-11-09T18:52:10Z")
        self.assertEqual(alert["severity"], "M3.1")  # the larger report
        self.assertIn("ssn-quakes: M2.9", alert["summary"])
        self.assertIn("usgs-quakes: M3.1", alert["summary"])
        self.assertIn("not an official warning", alert["summary"])
        self.assertTrue(alert["url"].startswith("http://www2.ssn.unam.mx:8080/"))

    def test_the_second_source_arriving_later_keeps_the_same_single_alert(self):
        self.poll(NOW, ssn_payload=ssn_feed())
        first = self.city_alerts()
        self.assertEqual(len(first), 1)
        later = NOW + timedelta(minutes=15)
        self.poll(later, ssn_payload=ssn_feed(), usgs_payload=usgs_feed(("us7000cdmx", 3.1, 19.34, -99.20, QUAKE_UTC)))
        again = self.city_alerts(later)
        self.assertEqual([a["id"] for a in again], [first[0]["id"]])
        self.assertIn("usgs-quakes: M3.1", again[0]["summary"])

    def test_usgs_first_then_ssn_keeps_the_usgs_id(self):
        self.poll(NOW, usgs_payload=usgs_feed(("us7000cdmx", 3.1, 19.34, -99.20, QUAKE_UTC)))
        first = self.city_alerts()
        self.assertEqual(len(first), 1)
        later = NOW + timedelta(minutes=15)
        self.poll(later, ssn_payload=ssn_feed(), usgs_payload=usgs_feed(("us7000cdmx", 3.1, 19.34, -99.20, QUAKE_UTC)))
        self.assertEqual([a["id"] for a in self.city_alerts(later)], [first[0]["id"]])

    def test_two_quakes_minutes_apart_are_two_alerts(self):
        aftershock = QUAKE_UTC + timedelta(minutes=4)
        self.poll(NOW, ssn_payload=ssn_feed(), usgs_payload=usgs_feed(("us7000cdmx", 3.1, 19.34, -99.20, aftershock)))
        self.assertEqual(len([a for a in self.alerts() if "km from CDMX" in a["title"]
                              and a["happened_at"][:13] == "2026-11-09T18"]), 2)

    def test_same_moment_far_apart_are_two_quakes(self):
        oaxaca = ("us7000oax", 6.3, 16.2, -95.2, QUAKE_UTC)  # same second, ~550 km away: not the city's quake
        self.poll(NOW, ssn_payload=ssn_feed(), usgs_payload=usgs_feed(oaxaca))
        titles = sorted(a["title"] for a in self.alerts() if a["happened_at"].startswith("2026-11-09T18:52"))
        self.assertEqual(len(titles), 2, titles)

    def test_a_small_far_quake_raises_nothing(self):
        self.poll(NOW, ssn_payload=ssn_feed(mag="3.2", lat="16.747", lon="-99.122", place="29 km al ESTE de  SAN MARCOS, GRO"))
        self.assertEqual(self.city_alerts(), [])

    def test_recon_leads_with_the_alert(self):
        self.poll(NOW, ssn_payload=ssn_feed())
        page = recon.gather(self.store, self.collectors, NOW)
        section = next(s for s in page.sections if s.key == "near-cdmx")
        self.assertEqual(page.sections[0].key, "near-cdmx")  # no my-stack in this run: it leads
        self.assertEqual(len(section.groups[0].rows), 1)


if __name__ == "__main__":
    unittest.main()
