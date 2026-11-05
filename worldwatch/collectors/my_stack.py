"""Alerts for "my stack": security items from NVD, OSV and CISA KEV whose products match a name
in the local watchlist (worldwatch/watchlist.py), with EPSS when FIRST has scored the CVE.

Nothing is fetched: this collector works from the store (`derive`), so it runs after the others.
An alert is one (vulnerability, stage): "new" when NVD or OSV publishes it, "exploited" when CISA
lists it — the second is news even when the first was already shown. At most CAP_PER_DAY alerts per
day — the evidence's own UTC date, which is also the date the Board and Recon show (KEV gives only
a date). Once shown an alert stays, on the day it was shown under, and the rest of a day fold into
one "+N more" line. Every alert is basis "inferred": the match is ours, the facts are the sources'.

Outages come the same way from the official status pages (status_pages.py): one alert per incident
with some impact (minor or worse) on a service or part whose name is on the watchlist. Minor ones
share the daily cap; when a day has more than the cap the order is: exploited, then new
vulnerabilities (by EPSS, then CVSS), then minor outages. A major or critical outage always shows
and takes none of the 5: Trevor can be away for days, and it must not hide in "+N more". One that
names no part reaches a list that watches any part of that service (D-21).

Taking a name off the watchlist takes its alerts and the "+N more" lines off the Board and frees
their day; an empty or unreadable list, or one with a line it can't use, removes nothing.
"""

from __future__ import annotations

import json
import logging
from dataclasses import dataclass, field, replace
from datetime import datetime, timedelta
from functools import partial
from pathlib import Path

from .. import watchlist
from ..item import Item, item_id, iso_utc, make_item, parse_iso_utc
from ..views import Panel
from . import Collector, cisa_kev, epss, nvd, osv, status_pages

log = logging.getLogger(__name__)

SOURCE = "my-stack"
LICENCE = ("worked out here from NVD (public domain), OSV.dev, CISA KEV (CC0) and EPSS (FIRST) data, "
           "and the services' own status pages")
LOOKBACK = timedelta(days=30)
CAP_PER_DAY = 5
FUTURE_SLACK = timedelta(minutes=5)
SCAN_LIMIT = 100_000
NEW, EXPLOITED, OUTAGE = "new", "exploited", "outage"
# Which alerts win a crowded day: a higher tier first (exploited 3, new CVE 1, minor outage 0).
OUTAGE_WEIGHT = {"minor": 0.5, "major": 0.75, "critical": 1.0}  # impact "none" raises no alert
BIG_OUTAGES = ("major", "critical")  # over the cap: never competes for the 5
PANEL_LIMIT = 300  # 30 days of 5 alerts and a "+N more" line, and room for the big outages


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
    """The first (watchlist entry, advisory's words) that match. Each name is normalised once."""
    names = []
    for pair in pairs if isinstance(pairs, list) else []:
        if isinstance(pair, (list, tuple)) and len(pair) == 2:
            name = watchlist.Name.of(*pair)
            if name is not None:
                names.append(name)
    for entry in entries:
        for name in names:
            if entry.hit(name):
                return entry.name, name.label
    return None


def _text(value: object) -> str:
    return value if isinstance(value, str) else ""


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
        data = _raw(row)
        hit = _match(entries, data.get("products"))
        if hit:
            note(_text(data.get("id")) or row["id"], row, hit)
    for row in _rows(store, osv.SOURCE, now):
        data = _raw(row)
        hit = _match(entries, data.get("packages"))
        if hit:
            cves = [c for c in data.get("cves") or [] if _text(c)]
            note(cves[0] if cves else _text(data.get("id")) or row["id"], row, hit)
    for row in _rows(store, cisa_kev.SOURCE, now):
        data = _raw(row)
        cve = _text(data.get("cveID"))
        if not cve:
            continue
        hit = _match(entries, [[data.get("vendorProject") or "", data.get("product")]])
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
    over_cap: bool = False


def _day(happened_at: str) -> str:
    return happened_at[:10]  # UTC: the date the Board and Recon show for this date-only panel


def _epss(store, cve: str, now: datetime) -> dict | None:
    """FIRST's latest score for the CVE as of `now` (a replay never sees a later score)."""
    row = store.db.execute("SELECT raw FROM items WHERE id = ? AND happened_at <= ?",
                           (item_id(epss.SOURCE, cve), iso_utc(now + FUTURE_SLACK))).fetchone()
    return _raw(row) if row else None


def _detail(row) -> str:
    """The advisory's own words: NVD's description (its summary already leads with the CVSS)."""
    if row["source"] == nvd.SOURCE:
        return _text(_raw(row).get("description"))[:600]
    return row["summary"]


def _best_cvss(rows) -> tuple[float, str] | None:
    scores = []
    for row in rows:
        score = _raw(row).get("cvss") if row["source"] == nvd.SOURCE else None
        if isinstance(score, list) and len(score) == 2 and isinstance(score[0], (int, float)):
            scores.append((float(score[0]), str(score[1])))
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
    detail = next((_detail(r) for r in ev.published if _detail(r)), "")
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
        out.append(Alert(item, _day(item.happened_at), (3 if stage == EXPLOITED else 1, *base_rank)))
    return out


def _no_part_hit(entries, names, impact) -> tuple[str, str] | None:
    """A big outage naming only the service reaches a list of its parts: it may be any of them."""
    if impact not in BIG_OUTAGES or not isinstance(names, list) or len(names) != 1:
        return None
    pair = names[0]
    name = watchlist.Name.of(*pair) if isinstance(pair, list) and len(pair) == 2 else None
    for entry in entries if name else []:
        if entry.watches_part_of(name):
            return entry.name, f"{name.label} (no part named)"
    return None


def _outage_alerts(store, entries, now: datetime) -> list[Alert]:
    """One alert per status-page incident that names a watched service or part of one."""
    out = []
    for source in status_pages.SOURCES:
        for row in _rows(store, source, now):
            data = _raw(row)
            impact = data.get("impact")
            if data.get("kind") != "incident" or impact not in OUTAGE_WEIGHT:
                continue
            hit = _match(entries, data.get("names")) or _no_part_hit(entries, data.get("names"), impact)
            if not hit:
                continue
            entry, matched = hit
            key = f"{source}/{_text(data.get('id')) or row['id']}"
            item = make_item(
                channel="status", source=SOURCE, native_id=f"{key}/{OUTAGE}",
                happened_at=parse_iso_utc(row["happened_at"]), fetched_at=now,
                title=f"{entry} · {row['title'].replace(' — ', ': ', 1)} — {impact} impact,"
                      f" {_text(data.get('status')) or 'open'}",
                url=row["url"], summary=f'{row["summary"]} Matched your watchlist entry "{entry}" on {matched}.'
                                        f" Source: {source}.",
                severity=row["severity"], licence=LICENCE,
                raw={"kind": "alert", "key": key, "stage": OUTAGE, "entry": entry, "matched": matched,
                     "sources": [source], "impact": impact},
                basis="inferred", lang="en",
            )
            out.append(Alert(item, _day(item.happened_at), (0, OUTAGE_WEIGHT[impact], 0.0), impact in BIG_OUTAGES))
    return out


def _overflow(day: str, hidden: list[Alert], now: datetime) -> Item:
    keys = ", ".join(sorted({a.item.title.split(" — ")[0] for a in hidden})[:20])
    return make_item(
        channel="security", source=SOURCE, native_id=f"overflow/{day}",
        happened_at=min(parse_iso_utc(a.item.happened_at) for a in hidden), fetched_at=now,  # below the day's alerts
        title=f"+{len(hidden)} more matches for your stack on {day} (at most {CAP_PER_DAY} alerts a day)",
        url=None, summary=f"Also matched: {keys}.", severity=None, licence=LICENCE,
        raw={"kind": "overflow", "day": day, "count": len(hidden)}, basis="inferred", lang="en",
    )


def derive(store, now: datetime, path: Path) -> list[Item]:
    problems: list[str] = []
    entries = watchlist.load(path, problems)
    if not entries:
        log.debug("%s: no watchlist entries in %s; no alerts", SOURCE, path)
        return []
    alerts = [a for ev in gather(store, entries, now).values() for a in _alerts(store, ev, now)]
    alerts += _outage_alerts(store, entries, now)
    derived = {a.item.id for a in alerts}
    listed = {e.name for e in entries}
    shown: dict[str, str] = {}  # alert id -> the time it was shown under (its day never moves)
    shown_per_day: dict[str, int] = {}
    gone: list[str] = []  # alerts of a name taken off the list
    old_lines: list[str] = []  # "+N more" lines: each run says them afresh
    for row in store.items_between(SOURCE, iso_utc(now - LOOKBACK - timedelta(days=1)),  # frozen times run early
                                   iso_utc(now + FUTURE_SLACK), limit=SCAN_LIMIT):
        data = _raw(row)
        if data.get("kind") == "overflow":
            old_lines.append(row["id"])
        elif data.get("kind") == "alert":
            if not problems and row["id"] not in derived and data.get("entry") not in listed:
                gone.append(row["id"])
                continue
            shown[row["id"]] = row["happened_at"]
            if data.get("impact") not in BIG_OUTAGES:
                shown_per_day[_day(row["happened_at"])] = shown_per_day.get(_day(row["happened_at"]), 0) + 1
    items: list[Item] = []
    by_day: dict[str, list[Alert]] = {}
    for alert in alerts:
        if alert.item.id in shown:
            # Once shown it stays, on its day; its facts are refreshed (an earlier source can't move it).
            items.append(replace(alert.item, happened_at=shown[alert.item.id]))
        else:
            by_day.setdefault(alert.day, []).append(alert)
    for day, group in sorted(by_day.items()):
        room = CAP_PER_DAY - shown_per_day.get(day, 0)
        hidden = []
        for alert in sorted(group, key=lambda a: (a.rank, a.item.happened_at, a.item.id), reverse=True):
            if alert.over_cap:
                items.append(alert.item)
            elif room > 0:
                items.append(alert.item)
                room -= 1
            else:
                hidden.append(alert)
        if hidden:
            items.append(_overflow(day, hidden, now))
    kept = {i.id for i in items}
    store.forget_items(SOURCE, gone + [line for line in old_lines if line not in kept])
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
                    window=LOOKBACK, limit=PANEL_LIMIT, date_only=True),
    )


def _derive_logged(store, now: datetime, *, path: Path) -> list[Item]:
    items = derive(store, now, path)
    if items:
        log.info("%s: %d alerts and summaries", SOURCE, len(items))
    return items
