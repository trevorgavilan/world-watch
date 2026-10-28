"""USGS earthquakes — the M2.5+ past-week GeoJSON summary feed (updated every minute).

Docs: https://earthquake.usgs.gov/earthquakes/feed/v1.0/geojson.php
      https://earthquake.usgs.gov/fdsnws/event/1/ (the catalogue query, for catching up)
Licence: USGS-authored data is US public domain; credit "U.S. Geological Survey".
The PC is switched on at no fixed time. A week of history covers most gaps; after a longer one
the catalogue query fetches what `keep` wants since the last good fetch (up to a year), in two
queries — M4.5+ worldwide and M3.5+ in the Mexico box — each far under the query's 20,000-event
cap (M3.5+ worldwide was 17,585 for the year to Oct 2026: too close). Catch-up misses only the rare
sig >= 600 quake under M4.5 outside Mexico. USGS asks automated readers to prefer the feeds, so
the query is used only for that catch-up.
Kept: M4.5+ anywhere, anything USGS rates significant (sig >= 600), and M3.5+
in a box around Mexico.
"""

from __future__ import annotations

from datetime import datetime, timedelta, timezone
from functools import partial
from urllib.parse import urlencode

from ..item import make_item
from ..views import Layer
from . import Collector, ParseError

SOURCE = "usgs-quakes"
LICENCE = "US public domain (credit: U.S. Geological Survey)"

GLOBAL_MIN_MAG = 4.5
SIGNIFICANT_MIN_SIG = 600
MEXICO_MIN_MAG = 3.5
WEEK_URL = "https://earthquake.usgs.gov/earthquakes/feed/v1.0/summary/2.5_week.geojson"
QUERY_URL = "https://earthquake.usgs.gov/fdsnws/event/1/query"
CATCH_UP_AFTER = timedelta(days=6)     # the week feed, with a day to spare
# starttime filters on when a quake happened; USGS adds some (regional networks) hours or days
# late, so overlap the last fetch by a day, as the week feed does. Items are de-duplicated.
CATCH_UP_MARGIN = timedelta(days=1)
CATCH_UP_MAX = timedelta(days=365)     # a year: ~7,800 M4.5+ worldwide, ~470 M3.5+ in the box

# lat_min, lat_max, lon_min, lon_max — Mexico plus its coasts; a rough box, not a border.
MEXICO_BOX = (14.0, 33.0, -118.5, -86.5)


def near_mexico(lat: float, lon: float) -> bool:
    lat_min, lat_max, lon_min, lon_max = MEXICO_BOX
    return lat_min <= lat <= lat_max and lon_min <= lon <= lon_max


def in_mexico_per_usgs(place: object) -> bool:
    """USGS's own place text ("12 km SW of Pinotepa Nacional, Mexico") — reported, not our guess.
    The box above only decides what to keep; it also covers Texas, Arizona and Guatemala."""
    return isinstance(place, str) and place.rstrip().endswith("Mexico") and not place.rstrip().endswith("New Mexico")


def keep(mag: float | None, sig: object, lat: float, lon: float) -> bool:
    if isinstance(sig, (int, float)) and sig >= SIGNIFICANT_MIN_SIG:
        return True
    if mag is None:
        return False
    if mag >= GLOBAL_MIN_MAG:
        return True
    return mag >= MEXICO_MIN_MAG and near_mexico(lat, lon)


def _build(feature: dict, fetched_at: datetime):
    props = feature["properties"]
    lon, lat, depth_km = feature["geometry"]["coordinates"][:3]
    mag = props.get("mag")
    alert = props.get("alert")
    severity = f"M{mag:.1f}" if isinstance(mag, (int, float)) else None
    if severity and alert:
        severity += f" · PAGER {alert}"
    tsunami = " Tsunami flag set." if props.get("tsunami") == 1 else ""
    depth = f"Depth {depth_km:.0f} km." if isinstance(depth_km, (int, float)) else ""
    return make_item(
        channel="hazards",
        source=SOURCE,
        native_id=feature["id"],
        happened_at=datetime.fromtimestamp(props["time"] / 1000, tz=timezone.utc),
        fetched_at=fetched_at,
        title=props.get("title") or props.get("place"),
        url=props.get("url"),
        summary=f"{depth}{tsunami}",
        lat=lat,
        lon=lon,
        country="MX" if in_mexico_per_usgs(props.get("place")) else None,
        severity=severity,
        licence=LICENCE,
        raw=feature,
        lang="en",
    )


def parse_records(data: object, fetched_at: datetime) -> list:
    if not isinstance(data, dict) or data.get("type") != "FeatureCollection":
        raise ParseError(f"{SOURCE}: not a GeoJSON FeatureCollection")
    builders = []
    for feature in data.get("features") or []:
        try:
            props = feature["properties"]
            lon, lat = feature["geometry"]["coordinates"][:2]
            mag = props.get("mag")
            if not keep(mag if isinstance(mag, (int, float)) else None, props.get("sig"), lat, lon):
                continue
        except Exception:  # noqa: BLE001 — malformed record: skipped, the rest still count
            continue
        builders.append(partial(_build, feature, fetched_at))
    return builders


def catch_up_queries(start: datetime) -> list[dict]:
    lat_min, lat_max, lon_min, lon_max = MEXICO_BOX
    common = {"format": "geojson", "starttime": start.astimezone(timezone.utc).strftime("%Y-%m-%dT%H:%M:%SZ"),
              "orderby": "time-asc"}
    return [
        {**common, "minmagnitude": GLOBAL_MIN_MAG},  # minmagnitude is inclusive
        {**common, "minmagnitude": MEXICO_MIN_MAG, "minlatitude": lat_min, "maxlatitude": lat_max,
         "minlongitude": lon_min, "maxlongitude": lon_max},
    ]


def url_for(last_ok: datetime | None, now: datetime) -> list[str]:
    """The week feed, unless the last good fetch is older than the feed covers."""
    if last_ok is None or now - last_ok <= CATCH_UP_AFTER:
        return [WEEK_URL]
    start = max(last_ok - CATCH_UP_MARGIN, now - CATCH_UP_MAX)
    return [QUERY_URL + "?" + urlencode(q) for q in catch_up_queries(start)]


def magnitude(row) -> float | None:
    """From the stored severity ("M4.7" or "M6.1 · PAGER yellow")."""
    try:
        return float((row["severity"] or "").split()[0][1:])
    except (ValueError, IndexError):
        return None


def weight(row) -> float:
    """M2.5 -> 0, M8.0 and up -> 1; an unknown magnitude shows small."""
    mag = magnitude(row)
    if mag is None:
        return 0.0
    return min(max((mag - 2.5) / 5.5, 0.0), 1.0)


COLLECTOR = Collector(
    source=SOURCE,
    channel="hazards",
    url=WEEK_URL,
    interval_s=15 * 60,
    licence=LICENCE,
    parse_records=parse_records,
    url_for=url_for,
    layer=Layer(id="quakes", en="Earthquakes", es="Sismos", window=timedelta(days=7), limit=2000, weight=weight),
)
