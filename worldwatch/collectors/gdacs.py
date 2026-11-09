"""GDACS — the Global Disaster Alert and Coordination System (UN OCHA, UNOSAT, the EU's JRC and ECHO).

API: https://www.gdacs.org/gdacsapi/api/events/geteventlist/events4app — the current events
(about two weeks, ~100), GeoJSON points, as named in GDACS's API quickstart (data.gdacs.org,
2025), which calls the API free to use. Times are UTC without a zone mark.
Terms (gdacs.org/documents/2025/GDACS_Terms_of_use_Mar_25.pdf): provided "as is"; automatic
notifications, not reviewed; never a substitute for national authorities' alerts.
An event keeps its id while its episodes update: one item per event, refreshed.
"""

from __future__ import annotations

from datetime import datetime, timedelta, timezone
from functools import partial

from ..item import make_item
from ..views import Layer
from . import Collector, ParseError

SOURCE = "gdacs"
URL = "https://www.gdacs.org/gdacsapi/api/events/geteventlist/events4app"
LICENCE = "GDACS (European Commission, UN OCHA, UNOSAT) — automatic estimates, provided as is"
KINDS = {"EQ": "Earthquake", "TC": "Tropical cyclone", "FL": "Flood", "VO": "Volcano", "WF": "Wildfire",
         "DR": "Drought", "TS": "Tsunami"}
LEVEL_WEIGHT = {"green": 0.25, "orange": 0.65, "red": 1.0}


def _utc(text: object) -> datetime:
    if not isinstance(text, str):
        raise ValueError("no time")
    return datetime.fromisoformat(text.rstrip("Z")).replace(tzinfo=timezone.utc)


def _build(feature: dict, fetched_at: datetime):
    props = feature["properties"]
    lon, lat = feature["geometry"]["coordinates"][:2]
    kind = props["eventtype"]
    level = str(props.get("alertlevel") or "").strip()
    severity_text = (props.get("severitydata") or {}).get("severitytext") or ""
    links = props.get("url") or {}
    return make_item(
        channel="hazards",
        source=SOURCE,
        native_id=f"{kind}{props['eventid']}",
        happened_at=_utc(props.get("fromdate")),
        fetched_at=fetched_at,
        title=props.get("name") or props.get("description") or KINDS.get(kind, kind),
        url=links.get("report") if isinstance(links, dict) else None,
        summary=" ".join(part for part in (
            f"{level} alert." if level else "", f"{severity_text.strip()}." if severity_text.strip() else "",
            f"Until {props['todate']} UTC." if props.get("todate") else "") if part),
        lat=lat,
        lon=lon,
        country=props.get("country") or None,
        severity=f"{level} · {KINDS.get(kind, kind)}" if level else KINDS.get(kind, kind),
        licence=LICENCE,
        raw=feature,
        lang="en",
    )


def parse_records(data: object, fetched_at: datetime) -> list:
    if not isinstance(data, dict) or data.get("type") != "FeatureCollection" or not isinstance(data.get("features"), list):
        raise ParseError(f"{SOURCE}: not a GeoJSON FeatureCollection")
    return [partial(_build, feature, fetched_at) for feature in data["features"]]


def weight(row) -> float:
    level = (row["severity"] or "").split(" · ")[0].strip().lower()
    return LEVEL_WEIGHT.get(level, 0.25)


COLLECTOR = Collector(
    source=SOURCE,
    channel="hazards",
    url=URL,
    interval_s=30 * 60,
    licence=LICENCE,
    parse_records=parse_records,
    layer=Layer(id="gdacs", en="Disaster alerts (GDACS)", es="Alertas de desastre (GDACS)",
                window=timedelta(days=30), limit=500, weight=weight),
)
