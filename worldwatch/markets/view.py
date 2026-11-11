"""What /api/markets answers: every instrument with its latest stored number, the change, a short
history for the chart, the source and how late it is; the day's biggest moves (worked out by us);
the peso lines and their alerts; the practice portfolio. Read only from the store.
"""

from __future__ import annotations

import json
from datetime import datetime, timedelta
from decimal import Decimal

from ..item import iso_utc, parse_iso_utc
from ..store import Store
from . import CHANNEL, DISCLAIMER_EN, DISCLAIMER_ES, number
from .catalog import CURVES, GROUPS, INSTRUMENTS, Instrument

HISTORY_DAILY = timedelta(days=400)
HISTORY_POINTS = 120          # the chart's points: enough to see a trend, never a flood
MOVE_FRESH = timedelta(days=5)  # a move counts in "what moved" only when its number is this recent
MOVES = 6
ROWS_PER_SOURCE = 20_000  # the newest rows: daily series reach back 400 days, hourly ones about a month


def _observations(store: Store, sources: list[str], now: datetime) -> dict[str, list[tuple[str, Decimal, dict, str]]]:
    """instrument id -> [(happened_at, value, raw, fetched_at)], oldest first."""
    found: dict[str, list] = {}
    start, end = iso_utc(now - HISTORY_DAILY), iso_utc(now + timedelta(minutes=5))
    for source in sources:
        newest = store.items_between(source, start, end, limit=ROWS_PER_SOURCE, order="happened_at DESC")
        for row in reversed(newest):  # never the oldest N: the store keeps everything, the tiles want today
            if row["channel"] != CHANNEL:
                continue
            try:
                raw = json.loads(row["raw"])
                value = number(raw["value"])
            except (ValueError, KeyError, TypeError):
                continue
            found.setdefault(str(raw.get("instrument")), []).append((row["happened_at"], value, raw, row["fetched_at"]))
    for rows in found.values():  # an instrument's hourly prices and its daily history come from two sources
        rows.sort(key=lambda r: r[0])
    return found


def _change(inst: Instrument, rows: list) -> dict | None:
    latest_at, latest, raw, _ = rows[-1]
    if not inst.daily:
        if "change_pct" not in raw:
            return None
        try:
            pct = number(raw["change_pct"])
        except ValueError:
            return None
        return {"pct": float(pct), "since": "reported"}
    if len(rows) < 2:
        return None
    prev_at, prev, _, _ = rows[-2]
    diff = latest - prev
    change = {"abs": float(diff), "since": prev_at}
    if not inst.points and prev != 0:
        change["pct"] = float(diff / prev * 100)
    return change


def _history(rows: list) -> list[list]:
    step = max(1, len(rows) // HISTORY_POINTS)
    picked = rows[::-1][::step][::-1]  # always keeps the newest
    return [[at, float(value)] for at, value, _, _ in picked[-HISTORY_POINTS:]]


def instrument_view(inst: Instrument, rows: list) -> dict:
    view = {
        "id": inst.id, "group": inst.group, "en": inst.en, "es": inst.es, "source": inst.source,
        "unit_en": inst.unit_en, "unit_es": inst.unit_es, "decimals": inst.decimals, "daily": inst.daily,
        "delay_en": inst.delay_en, "delay_es": inst.delay_es, "page": inst.page, "term": inst.term,
        "points": inst.points, "notice": inst.notice, "history_note": HISTORY_NOTE.get(inst.source, ""), "latest": None, "change": None, "history": [],
    }
    if rows:
        at, value, _, fetched = rows[-1]
        view["latest"] = {"value": f"{value:.{inst.decimals}f}", "at": at, "fetched_at": fetched}
        view["change"] = _change(inst, rows)
        view["history"] = _history(rows)
    return view


def moves(views: list[dict], now: datetime) -> list[dict]:
    """The biggest moves by per cent, among numbers recent enough: our own arithmetic, labelled so."""
    fresh = [v for v in views if v["latest"] and v["change"] and "pct" in v["change"]
             and now - parse_iso_utc(v["latest"]["at"]) <= MOVE_FRESH]
    fresh.sort(key=lambda v: abs(v["change"]["pct"]), reverse=True)
    return [{"id": v["id"], "en": v["en"], "es": v["es"], "pct": v["change"]["pct"], "at": v["latest"]["at"]}
            for v in fresh[:MOVES]]


def markets_view(store: Store, sources: list[str], now: datetime, *, watch: list[Instrument] = (),
                 extra: dict | None = None) -> dict:
    rows = _observations(store, sources, now)
    instruments = [i for i in INSTRUMENTS + list(watch) if i.source in sources]
    views = [instrument_view(i, rows.get(i.id, [])) for i in instruments]
    return {
        "now": iso_utc(now),
        "groups": [{"id": g, "en": en, "es": es, "items": [v for v in views if v["group"] == g]}
                   for g, en, es in GROUPS if any(v["group"] == g for v in views)],
        "moves": moves(views, now),
        "disclaimer_en": DISCLAIMER_EN,
        "disclaimer_es": DISCLAIMER_ES,
        **(extra or {}),
    }


HISTORY_OF = {"coingecko": "twelvedata-history", "twelvedata": "twelvedata-history"}  # an hourly source's daily past
HISTORY_NOTE = {
    "coingecko": "Daily history: Twelve Data (Binance's close; the peso pairs are Twelve Data's synthetic rate). "
                 "The latest price: CoinGecko.",
    "twelvedata": "Daily history and the latest price: Twelve Data (delayed).",
}
CURVE_BACK = timedelta(days=30)
SERIES_POINTS = 3000


def curves(store: Store, sources: list[str], now: datetime) -> list[dict]:
    """Each yield curve: every maturity's newest number and the one about a month before it, each with its
    own date (Mexico's long bonds are auctioned weeks apart)."""
    rows = _observations(store, sources, now)
    out = []
    for curve_id, en, es in CURVES:
        points = []
        for inst in sorted((i for i in INSTRUMENTS if i.curve == curve_id and i.source in sources), key=lambda i: i.years):
            mine = rows.get(inst.id, [])
            if not mine:
                continue
            at, value, _, _ = mine[-1]
            before = [r for r in mine if r[0] <= iso_utc(parse_iso_utc(at) - CURVE_BACK)]
            points.append({"id": inst.id, "years": inst.years, "en": inst.en, "es": inst.es, "value": float(value),
                           "at": at, "before": float(before[-1][1]) if before else None,
                           "before_at": before[-1][0] if before else None})
        if points:
            out.append({"id": curve_id, "en": en, "es": es, "points": points})
    return out


def series(store: Store, inst: Instrument, sources: list[str], now: datetime) -> dict:
    """Everything stored for one instrument in the last 400 days, oldest first: the big chart's points.
    Hourly prices and their daily history come from two sources; a day can hold both."""
    wanted = [s for s in (inst.source, HISTORY_OF.get(inst.source)) if s and s in sources]
    found = store.items_with(wanted, iso_utc(now - HISTORY_DAILY), iso_utc(now + timedelta(minutes=5)),
                             f'"instrument": "{inst.id}"', limit=SERIES_POINTS) if wanted else []
    points = []
    for row in reversed(found):
        try:
            raw = json.loads(row["raw"])
            if raw.get("instrument") == inst.id:
                points.append([row["happened_at"], float(number(raw["value"]))])
        except (ValueError, KeyError, TypeError):
            continue
    points.sort(key=lambda p: p[0])
    return {"id": inst.id, "daily": inst.daily, "decimals": inst.decimals, "points": points,
            "note": HISTORY_NOTE.get(inst.source, "")}
