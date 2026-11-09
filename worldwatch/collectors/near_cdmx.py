"""Alerts: a quake near Mexico City, from what USGS and the SSN already stored (cdmx.py's rule, D-22).

Nothing is fetched (`derive`); it runs after the fetches, every 5 minutes like the SSN, so a quake
either source reports raises its alert in the same poll. One quake reported by both is one alert:
two reports within QUAKE_SECONDS and QUAKE_KM of each other are the same quake, and the alert keeps
the id of the report stored first (the store never changes a first fetch time), so it never doubles
or moves when the second source catches up. Every alert is basis "inferred": the rule is ours,
the facts are the sources'. No cap: quakes this close are rare, and every one is shown.
"""

from __future__ import annotations

import logging
from dataclasses import dataclass
from datetime import datetime, timedelta

from ..item import Item, iso_utc, make_item, parse_iso_utc
from ..views import Panel
from . import Collector, cdmx, ssn, usgs

log = logging.getLogger(__name__)

SOURCE = "near-cdmx"
LICENCE = ("worked out here from USGS (public domain) and Servicio Sismológico Nacional, UNAM "
           "(free use with credit) reports")
QUAKE_SOURCES = (ssn.SOURCE, usgs.SOURCE)  # the order breaks a tie: the national service first
LOOKBACK = timedelta(days=30)
FUTURE_SLACK = timedelta(minutes=5)
SCAN_LIMIT = 50_000
QUAKE_SECONDS = 120  # SSN and USGS times for one quake differ by seconds; a minute's margin each way
QUAKE_KM = 100.0     # their epicentres by tens of km


@dataclass(frozen=True)
class Report:
    row: object
    when: datetime
    mag: float
    lat: float
    lon: float

    @property
    def source(self) -> str:
        return self.row["source"]


def _reports(store, now: datetime) -> list[Report]:
    out = []
    for source in QUAKE_SOURCES:
        for row in store.items_between(source, iso_utc(now - LOOKBACK), iso_utc(now + FUTURE_SLACK),
                                       limit=SCAN_LIMIT, positioned=True):
            mag = usgs.magnitude(row)
            if mag is not None and cdmx.near_cdmx(mag, row["lat"], row["lon"]):
                out.append(Report(row, parse_iso_utc(row["happened_at"]), mag, row["lat"], row["lon"]))
    return out


def _same_quake(a: Report, b: Report) -> bool:
    return (a.source != b.source and abs((a.when - b.when).total_seconds()) <= QUAKE_SECONDS
            and cdmx.km_between(a.lat, a.lon, b.lat, b.lon) <= QUAKE_KM)


def group(reports: list[Report]) -> list[list[Report]]:
    """Each quake's reports, the first-stored report first (then the national service)."""
    order = sorted(reports, key=lambda r: (r.row["fetched_at"], QUAKE_SOURCES.index(r.source), r.row["id"]))
    quakes: list[list[Report]] = []
    for report in order:
        home = next((q for q in quakes if all(r.source != report.source for r in q)
                     and _same_quake(q[0], report)), None)
        if home is None:
            quakes.append([report])
        else:
            home.append(report)
    return quakes


def _alert(quake: list[Report], now: datetime) -> Item:
    first = quake[0]
    lead = next((r for r in quake if r.source == ssn.SOURCE), first)  # SSN's words when it has them
    distance = cdmx.km_from_cdmx(lead.lat, lead.lon)
    place = lead.row["title"].split(" — ", 1)[-1] if lead.source == ssn.SOURCE else lead.row["title"]
    facts = "; ".join(f"{r.source}: M{r.mag:.1f}, {r.row['title']}" for r in quake)
    return make_item(
        channel="hazards", source=SOURCE, native_id=f"{first.source}/{first.row['id']}",
        happened_at=min(r.when for r in quake), fetched_at=now,
        title=f"Quake M{lead.mag:.1f}, {distance:.0f} km from CDMX — {place}",
        url=lead.row["url"] or first.row["url"],
        summary=f"{facts}. {lead.row['summary']} Near CDMX by World Watch's rule (cdmx.py), not an official warning.",
        lat=lead.lat, lon=lead.lon, severity=f"M{max(r.mag for r in quake):.1f}",
        licence=LICENCE,
        raw={"kind": "alert", "reports": [[r.source, r.row["id"]] for r in quake], "km": round(distance, 1)},
        basis="inferred", lang="en",
    )


def derive(store, now: datetime) -> list[Item]:
    items = [_alert(quake, now) for quake in group(_reports(store, now))]
    if items:
        log.info("%s: %d quake alerts in %d days", SOURCE, len(items), LOOKBACK.days)
    return items


COLLECTOR = Collector(
    source=SOURCE,
    channel="hazards",
    url="",  # nothing is fetched
    interval_s=5 * 60,
    licence=LICENCE,
    parse_records=lambda data, fetched_at: [],
    derive=derive,
    panel=Panel(id="near-cdmx", en="Near CDMX — quake alerts", es="Cerca de CDMX — alertas de sismo",
                window=LOOKBACK, limit=100),
)
