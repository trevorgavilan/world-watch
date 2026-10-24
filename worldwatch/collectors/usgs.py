"""USGS earthquakes — the M2.5+ past-week GeoJSON summary feed (updated every minute).

Docs: https://earthquake.usgs.gov/earthquakes/feed/v1.0/geojson.php
Licence: USGS-authored data is US public domain; credit "U.S. Geological Survey".
A week of history means a PC that was off overnight catches up on its next run.
Kept: M4.5+ anywhere, anything USGS rates significant (sig >= 600), and M3.5+
in a box around Mexico.
"""

from __future__ import annotations

from datetime import datetime, timezone
from functools import partial

from ..item import make_item
from . import Collector, ParseError

SOURCE = "usgs-quakes"
LICENCE = "US public domain (credit: U.S. Geological Survey)"

GLOBAL_MIN_MAG = 4.5
SIGNIFICANT_MIN_SIG = 600
MEXICO_MIN_MAG = 3.5
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


COLLECTOR = Collector(
    source=SOURCE,
    channel="hazards",
    url="https://earthquake.usgs.gov/earthquakes/feed/v1.0/summary/2.5_week.geojson",
    interval_s=15 * 60,
    licence=LICENCE,
    parse_records=parse_records,
)
