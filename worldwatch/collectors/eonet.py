"""NASA EONET v3 — natural events still open (storms, wildfires, volcanoes, sea and lake ice…).

API: https://eonet.gsfc.nasa.gov/docs/v3 — no key. `status=open&days=30`: open events with a
position in the last 30 days. Each event lists dated positions (Point, sometimes Polygon); the
newest one places it. Disclaimer (eonet.gsfc.nasa.gov/what-is-eonet): for visualisation and
general information only; extents are approximations, not "official". NASA data, no stated limit.
"""

from __future__ import annotations

from datetime import datetime, timedelta, timezone
from functools import partial

from ..item import make_item
from ..views import Layer
from . import Collector, ParseError

SOURCE = "nasa-eonet"
URL = "https://eonet.gsfc.nasa.gov/api/v3/events?status=open&days=30"
LICENCE = "NASA EONET — for general information; positions are approximate"


def _utc(text: str) -> datetime:
    return datetime.strptime(text, "%Y-%m-%dT%H:%M:%SZ").replace(tzinfo=timezone.utc)


def _point(geometry: dict) -> tuple[float, float] | tuple[None, None]:
    """(lat, lon): a Point as given; a Polygon by the mean of its outer ring's corners."""
    coords = geometry.get("coordinates")
    if geometry.get("type") == "Point":
        return coords[1], coords[0]
    if geometry.get("type") == "Polygon" and coords and coords[0]:
        ring = coords[0]
        return sum(p[1] for p in ring) / len(ring), sum(p[0] for p in ring) / len(ring)
    return None, None


def _build(event: dict, fetched_at: datetime):
    latest = max(event["geometry"], key=lambda g: g["date"])
    lat, lon = _point(latest)
    categories = ", ".join(c["title"] for c in event.get("categories") or [] if c.get("title"))
    magnitude = ""
    if isinstance(latest.get("magnitudeValue"), (int, float)):
        magnitude = f"{latest['magnitudeValue']:g} {latest.get('magnitudeUnit') or ''}".strip()
    sources = [s for s in event.get("sources") or [] if isinstance(s, dict)]
    return make_item(
        channel="hazards",
        source=SOURCE,
        native_id=event["id"],
        happened_at=_utc(latest["date"]),
        fetched_at=fetched_at,
        title=event["title"],
        url=sources[0].get("url") if sources else None,
        summary=" ".join(part for part in (
            f"{categories}." if categories else "", f"{magnitude}." if magnitude else "",
            f"Sources: {', '.join(str(s.get('id')) for s in sources)}." if sources else "",
            f"{len(event['geometry'])} positions since {min(g['date'] for g in event['geometry'])[:10]}.")
            if part),
        lat=lat,
        lon=lon,
        severity=" · ".join(p for p in (categories, magnitude) if p) or None,
        licence=LICENCE,
        raw={k: event.get(k) for k in ("id", "title", "description", "link", "closed", "categories", "sources")}
        | {"latest": latest, "positions": len(event["geometry"])},
        lang="en",
    )


def parse_records(data: object, fetched_at: datetime) -> list:
    if not isinstance(data, dict) or not isinstance(data.get("events"), list):
        raise ParseError(f"{SOURCE}: no events list")
    return [partial(_build, event, fetched_at) for event in data["events"]]


COLLECTOR = Collector(
    source=SOURCE,
    channel="hazards",
    url=URL,
    interval_s=60 * 60,
    licence=LICENCE,
    parse_records=parse_records,
    layer=Layer(id="eonet", en="Natural events (NASA EONET)", es="Eventos naturales (NASA EONET)",
                window=timedelta(days=30), limit=500),
)
