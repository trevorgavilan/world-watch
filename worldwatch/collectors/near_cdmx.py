"""Alerts: a quake near Mexico City, from what USGS and the SSN already stored (cdmx.py's rule, D-22).

Nothing is fetched (`derive`); it runs after the fetches, every 5 minutes like the SSN, so a quake
either source reports raises its alert in the same poll. Every report within reach of the city is
grouped first, whatever its magnitude, so a revised magnitude never moves an alert:
- reports from the two sources within QUAKE_SECONDS and QUAKE_KM are one quake; a second report from
  the same source (a re-timed SSN line, a new USGS id) joins only within SAME_SECONDS and SAME_KM;
  a report joins the group whose nearest report is closest in time (an aftershock burst stays apart);
- a quake raises an alert when any of its reports meets the rule; the alert keeps the id of the
  quake's first-stored report (the store never changes a first fetch time), so it never doubles or
  moves when a source catches up or revises;
- an alert no quake supports any more (revised below the rule) leaves the Board on the next run.
Every alert is basis "inferred": the rule is ours, the facts are the sources'. No cap: quakes this
close are rare, and every one is shown.
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
SAME_SECONDS = 10    # one source's own revisions move a quake by a second or two
SAME_KM = 20.0
REACH_KM = max(km for km, _ in cdmx.NEAR_RULES)


@dataclass(frozen=True)
class Report:
    row: object
    when: datetime
    mag: float | None
    lat: float
    lon: float

    @property
    def source(self) -> str:
        return self.row["source"]

    @property
    def near(self) -> bool:
        return cdmx.near_cdmx(self.mag, self.lat, self.lon)


def _reports(store, now: datetime) -> tuple[list[Report], bool]:
    """Every report within reach of the city, and whether every scan was complete."""
    out, complete = [], True
    for source in QUAKE_SOURCES:
        rows = store.items_between(source, iso_utc(now - LOOKBACK), iso_utc(now + FUTURE_SLACK),
                                   limit=SCAN_LIMIT, positioned=True)
        complete = complete and len(rows) < SCAN_LIMIT
        for row in rows:
            if cdmx.km_from_cdmx(row["lat"], row["lon"]) <= REACH_KM:
                out.append(Report(row, parse_iso_utc(row["happened_at"]), usgs.magnitude(row), row["lat"], row["lon"]))
    return out, complete


def _gap(a: Report, b: Report) -> float | None:
    """Seconds between two reports of one quake, or None when they are two quakes."""
    seconds = abs((a.when - b.when).total_seconds())
    limit_s, limit_km = (SAME_SECONDS, SAME_KM) if a.source == b.source else (QUAKE_SECONDS, QUAKE_KM)
    if seconds <= limit_s and cdmx.km_between(a.lat, a.lon, b.lat, b.lon) <= limit_km:
        return seconds
    return None


def group(reports: list[Report]) -> list[list[Report]]:
    """Each quake's reports, the first-stored report first (then the national service)."""
    order = sorted(reports, key=lambda r: (r.row["fetched_at"], QUAKE_SOURCES.index(r.source), r.row["id"]))
    quakes: list[list[Report]] = []
    by_minute: dict[int, list[int]] = {}  # time bucket -> quakes with a report in it (a month is ~1,500 reports)

    def bucket(report: Report) -> int:
        return int(report.when.timestamp() // QUAKE_SECONDS)

    for report in order:
        best, best_gap = None, None
        nearby = {n for b in (bucket(report) - 1, bucket(report), bucket(report) + 1) for n in by_minute.get(b, [])}
        for n in sorted(nearby):
            gaps = [g for g in (_gap(member, report) for member in quakes[n]) if g is not None]
            if gaps and (best_gap is None or min(gaps) < best_gap):
                best, best_gap = n, min(gaps)
        if best is None:
            best = len(quakes)
            quakes.append([report])
        else:
            quakes[best].append(report)
        by_minute.setdefault(bucket(report), []).append(best)
    return quakes


def _alert(quake: list[Report], now: datetime) -> Item:
    first = quake[0]
    passing = [r for r in quake if r.near]
    lead = next((r for r in passing if r.source == ssn.SOURCE), passing[0])  # SSN's words when it has them
    distance = cdmx.km_from_cdmx(lead.lat, lead.lon)
    place = lead.row["title"].split(" — ", 1)[-1] if lead.source == ssn.SOURCE else lead.row["title"]
    facts = "; ".join(f"{r.source}: {r.row['severity'] or 'M?'}, {r.row['title']}" for r in quake)
    return make_item(
        channel="hazards", source=SOURCE, native_id=f"{first.source}/{first.row['id']}",
        happened_at=min(r.when for r in quake), fetched_at=now,
        title=f"Quake M{lead.mag:.1f}, {distance:.0f} km from CDMX — {place}",
        url=lead.row["url"] or first.row["url"],
        summary=f"{facts}. {lead.row['summary']} Near CDMX by World Watch's rule (cdmx.py), not an official warning.",
        lat=lead.lat, lon=lead.lon, severity=f"M{max(r.mag for r in passing):.1f}",
        licence=LICENCE,
        raw={"kind": "alert", "reports": [[r.source, r.row["id"]] for r in quake], "km": round(distance, 1)},
        basis="inferred", lang="en",
    )


def derive(store, now: datetime) -> list[Item]:
    reports, complete = _reports(store, now)
    items = [_alert(quake, now) for quake in group(reports) if any(r.near for r in quake)]
    if complete:  # a cut-short scan could miss a quake's reports: then nothing is taken away
        kept = {i.id for i in items}
        old = store.items_between(SOURCE, iso_utc(now - LOOKBACK), iso_utc(now + FUTURE_SLACK), limit=SCAN_LIMIT)
        store.forget_items(SOURCE, [row["id"] for row in old if row["id"] not in kept])
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
