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
from .catalog import GROUPS, INSTRUMENTS, Instrument

HISTORY_DAILY = timedelta(days=400)
HISTORY_POINTS = 120          # the chart's points: enough to see a trend, never a flood
MOVE_FRESH = timedelta(days=5)  # a move counts in "what moved" only when its number is this recent
MOVES = 6
ROWS_PER_SOURCE = 40_000


def _observations(store: Store, sources: list[str], now: datetime) -> dict[str, list[tuple[str, Decimal, dict, str]]]:
    """instrument id -> [(happened_at, value, raw, fetched_at)], oldest first."""
    found: dict[str, list] = {}
    start, end = iso_utc(now - HISTORY_DAILY), iso_utc(now + timedelta(minutes=5))
    for source in sources:
        for row in store.items_between(source, start, end, limit=ROWS_PER_SOURCE, order="happened_at ASC"):
            if row["channel"] != CHANNEL:
                continue
            try:
                raw = json.loads(row["raw"])
                value = number(raw["value"])
            except (ValueError, KeyError, TypeError):
                continue
            found.setdefault(str(raw.get("instrument")), []).append((row["happened_at"], value, raw, row["fetched_at"]))
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
        "points": inst.points, "latest": None, "change": None, "history": [],
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
