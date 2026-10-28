"""Alerts for "my stack": security items from NVD, OSV and CISA KEV whose products match a name
in the local watchlist (worldwatch/watchlist.py), with EPSS when FIRST has scored the CVE.

Nothing is fetched: this collector works from the store (`derive`), so it runs after the others.
An alert is one (vulnerability, stage): "new" when NVD or OSV publishes it, "exploited" when CISA
lists it — the second is news even when the first was already shown. At most CAP_PER_DAY alerts per
day — Trevor's day in CDMX, or KEV's own date for KEV, which gives a date, not a moment; once shown
an alert stays, and the rest of that day fold into one "+N more" line. Every alert is basis "inferred": the match is ours, the facts are the sources'.
"""

from __future__ import annotations

import json
import logging
from dataclasses import dataclass, field
from datetime import datetime, timedelta
from functools import partial
from pathlib import Path

from .. import watchlist
from ..item import Item, item_id, iso_utc, make_item, parse_iso_utc
from ..recon import local
from ..views import Panel
from . import Collector, cisa_kev, epss, nvd, osv

log = logging.getLogger(__name__)

SOURCE = "my-stack"
LICENCE = "worked out here from NVD (public domain), OSV.dev, CISA KEV (CC0) and EPSS (FIRST) data"
LOOKBACK = timedelta(days=30)
CAP_PER_DAY = 5
FUTURE_SLACK = timedelta(minutes=5)
SCAN_LIMIT = 100_000
NEW, EXPLOITED = "new", "exploited"


@dataclass
class Evidence:
    key: str  # the CVE id, or the OSV id when there is none
    published: list = field(default_factory=list)  # NVD / OSV rows that named a watched product
    exploited: object = None                         # the KEV row, if CISA lists it
    entry: str | None = None
    matched: str | None = None


def _raw(row) -> dict:
    try:
        data = json.loads(row["raw"])
    except ValueError:
        return {}
    return data if isinstance(data, dict) else {}


def _match(entries, pairs) -> tuple[str, str] | None:
    for entry in entries:
        for vendor, product in pairs:
            hit = entry.matches(vendor, product)
            if hit:
                return entry.name, hit
    return None


def _rows(store, source: str, now: datetime):
    return store.items_between(source, iso_utc(now - LOOKBACK), iso_utc(now + FUTURE_SLACK), limit=SCAN_LIMIT)


def gather(store, entries, now: datetime) -> dict[str, Evidence]:
    found: dict[str, Evidence] = {}

    def note(key: str, row, hit) -> None:
        ev = found.setdefault(key, Evidence(key))
        ev.published.append(row)
        if ev.entry is None:
            ev.entry, ev.matched = hit

    for row in _rows(store, nvd.SOURCE, now):
        hit = _match(entries, _raw(row).get("products") or [])
        if hit:
            note(_raw(row).get("id") or row["id"], row, hit)
    for row in _rows(store, osv.SOURCE, now):
        data = _raw(row)
        hit = _match(entries, [(eco, name) for eco, name in data.get("packages") or []])
        if hit:
            note((data.get("cves") or [data.get("id") or row["id"]])[0], row, hit)
    kev_rows = {(_raw(r).get("cveID")): r for r in _rows(store, cisa_kev.SOURCE, now)}
    for cve, row in kev_rows.items():
        data = _raw(row)
        hit = _match(entries, [(data.get("vendorProject") or "", data.get("product") or "")])
        if hit:
            ev = found.setdefault(cve, Evidence(cve))
            ev.exploited = row
            if ev.entry is None:
                ev.entry, ev.matched = hit
        elif cve in found:
            found[cve].exploited = row  # the advisory matched; CISA now says it is exploited
    return found


@dataclass(frozen=True)
class Alert:
    item: Item
    day: str
    rank: tuple


def _day(happened_at: str, stage: str) -> str:
    if stage == EXPLOITED:
        return happened_at[:10]
    return local(parse_iso_utc(happened_at)).strftime("%Y-%m-%d")


def _epss(store, cve: str, now: datetime) -> dict | None:
    """FIRST's latest score for the CVE as of `now` (a replay never sees a later score)."""
    row = store.db.execute("SELECT raw FROM items WHERE id = ? AND happened_at <= ?",
                           (item_id(epss.SOURCE, cve), iso_utc(now + FUTURE_SLACK))).fetchone()
    return _raw(row) if row else None


def _best_cvss(rows) -> tuple[float, str] | None:
    scores = [tuple(_raw(r)["cvss"]) for r in rows if r["source"] == nvd.SOURCE and _raw(r).get("cvss")]
    return max(scores) if scores else None


def _alerts(store, ev: Evidence, now: datetime) -> list[Alert]:
    is_cve = ev.key.startswith("CVE-")
    score = _epss(store, ev.key, now) if is_cve else None
    cvss = _best_cvss(ev.published)
    sources = sorted({r["source"] for r in ev.published} | ({cisa_kev.SOURCE} if ev.exploited else set()))
    facts = []
    if cvss:
        facts.append(f"CVSS {cvss[0]:g} {cvss[1]}".strip())
    if score:
        facts.append(f"EPSS {score['epss']:.1%} on {score['date']}")
    detail = next((r["summary"] for r in ev.published if r["summary"]), "")
    if ev.exploited is not None and not detail:
        detail = ev.exploited["summary"]
    tail = f' Matched your watchlist entry "{ev.entry}" on {ev.matched}. Sources: {", ".join(sources)}.'
    url = nvd.DETAIL_URL.format(ev.key) if is_cve else osv.PAGE_URL.format(ev.key)
    base_rank = (score["epss"] if score else 0.0, cvss[0] if cvss else 0.0)
    out = []
    stages = []
    if ev.published:
        first = min(ev.published, key=lambda r: r["happened_at"])
        stages.append((NEW, first, "new vulnerability" + (f", {facts[0]}" if facts else "")))
    if ev.exploited is not None:
        stages.append((EXPLOITED, ev.exploited, "exploited in the wild (CISA KEV)"))
    for stage, row, what in stages:
        happened = parse_iso_utc(row["happened_at"])
        raw = {"kind": "alert", "key": ev.key, "stage": stage, "entry": ev.entry, "matched": ev.matched,
               "sources": sources, "epss": score, "cvss": list(cvss) if cvss else None}
        item = make_item(
            channel="security", source=SOURCE, native_id=f"{ev.key}/{stage}", happened_at=happened,
            fetched_at=now, title=f"{ev.entry} · {ev.key} — {what}", url=url,
            summary=(f"{'; '.join(facts)}. " if facts else "") + detail + tail,
            severity="exploited" if stage == EXPLOITED else (facts[0] if facts else None),
            licence=LICENCE, raw=raw, basis="inferred", lang="en",
        )
        out.append(Alert(item, _day(row["happened_at"], stage), (stage == EXPLOITED, *base_rank)))
    return out


def _overflow(day: str, hidden: list[Alert], now: datetime) -> Item:
    keys = ", ".join(sorted({a.item.title.split(" — ")[0] for a in hidden})[:20])
    return make_item(
        channel="security", source=SOURCE, native_id=f"overflow/{day}",
        happened_at=max(parse_iso_utc(a.item.happened_at) for a in hidden), fetched_at=now,
        title=f"+{len(hidden)} more matches for your stack on {day} (at most {CAP_PER_DAY} alerts a day)",
        url=None, summary=f"Also matched: {keys}.", severity=None, licence=LICENCE,
        raw={"kind": "overflow", "day": day, "count": len(hidden)}, basis="inferred", lang="en",
    )


def derive(store, now: datetime, path: Path) -> list[Item]:
    entries = watchlist.load(path)
    if not entries:
        log.debug("%s: no watchlist entries in %s; no alerts", SOURCE, path)
        return []
    alerts = [a for ev in gather(store, entries, now).values() for a in _alerts(store, ev, now)]
    shown_ids, shown_per_day = set(), {}
    for row in _rows(store, SOURCE, now):
        data = _raw(row)
        if data.get("kind") == "alert" and row["id"] not in shown_ids:
            shown_ids.add(row["id"])
            day = _day(row["happened_at"], data.get("stage", NEW))
            shown_per_day[day] = shown_per_day.get(day, 0) + 1
    items: list[Item] = []
    by_day: dict[str, list[Alert]] = {}
    for alert in alerts:
        by_day.setdefault(alert.day, []).append(alert)
    for day, group in sorted(by_day.items()):
        room = CAP_PER_DAY - shown_per_day.get(day, 0)
        hidden = []
        for alert in sorted(group, key=lambda a: (a.rank, a.item.id), reverse=True):
            if alert.item.id in shown_ids:
                items.append(alert.item)  # once shown it stays; its facts are refreshed
            elif room > 0:
                items.append(alert.item)
                room -= 1
            else:
                hidden.append(alert)
        if hidden:
            items.append(_overflow(day, hidden, now))
    return items


def collector(path: Path) -> Collector:
    return Collector(
        source=SOURCE,
        channel="security",
        url="",  # nothing is fetched
        interval_s=15 * 60,
        licence=LICENCE,
        parse_records=lambda data, fetched_at: [],
        derive=partial(_derive_logged, path=path),
        panel=Panel(id="my-stack", en="Your stack — alerts", es="Tu stack — alertas",
                    window=timedelta(days=14), limit=30, date_only=True),
    )


def _derive_logged(store, now: datetime, *, path: Path) -> list[Item]:
    items = derive(store, now, path)
    if items:
        log.info("%s: %d alerts and summaries", SOURCE, len(items))
    return items
