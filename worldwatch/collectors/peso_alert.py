"""Peso alerts — worked out from the stored FIX and Trevor's lines in data/markets.txt (Task 5).

Nothing is fetched. After each cycle, the newest FIX is compared with every `peso above|below`
line; a crossed line is an alert for that FIX's day (inferred: our comparison of Banxico's number).
An alert whose line was taken out of the file is forgotten; one already shown for a past day stays.
Phone delivery comes with Task 8; for now it leads the Board's lists and Morning Recon.
"""

from __future__ import annotations

import json
import logging
from datetime import datetime, timedelta
from functools import partial
from pathlib import Path

from ..item import Item, iso_utc, make_item, parse_iso_utc
from ..markets import CHANNEL, number
from ..markets import rules as market_rules
from ..views import Panel
from . import Collector

log = logging.getLogger(__name__)

SOURCE = "peso-alert"
FIX_SOURCE = "banxico-peso"
FIX_ID = "usd-mxn-fix"
LICENCE = "World Watch, from Banco de México's FIX (SIE) and your lines in data/markets.txt"
LOOKBACK = timedelta(days=10)  # a FIX older than this raises nothing new
PANEL_WINDOW = timedelta(days=30)


def latest_fix(store, now: datetime):
    rows = store.items_between(FIX_SOURCE, iso_utc(now - LOOKBACK), iso_utc(now + timedelta(minutes=5)), limit=50)
    for row in rows:  # newest first
        try:
            raw = json.loads(row["raw"])
            if raw.get("instrument") == FIX_ID:
                return parse_iso_utc(row["happened_at"]), number(raw["value"])
        except (ValueError, KeyError, TypeError):
            continue
    return None


def _line_key(text: object):
    parsed = market_rules.parse(str(text or "")).peso
    return parsed[0].key if parsed else None


def derive(store, now: datetime, path: Path) -> list[Item]:
    rules = market_rules.load(path)
    found = latest_fix(store, now)
    if rules.readable:  # a file that can't be read right now (mid-save, missing) never wipes past alerts
        wanted = {line.key for line in rules.peso}
        stale = [row["id"] for row in store.items_between(SOURCE, "0000", "9999", limit=500)
                 if _line_key(json.loads(row["raw"]).get("line")) not in wanted]
        store.forget_items(SOURCE, stale)
    if found is None:
        return []
    day, fix = found
    items = []
    for line in rules.peso:
        if not line.crossed(fix):
            continue
        word_en, word_es = ("above", "arriba de") if line.side == "above" else ("below", "abajo de")
        items.append(make_item(
            channel=CHANNEL, source=SOURCE, native_id=f"{line.key[0]} {line.key[1]:f}/{day:%Y-%m-%d}", happened_at=day,
            fetched_at=now, url="https://www.banxico.org.mx/tipcamb/main.do?page=tip&idioma=sp",
            title=f"Peso past your line: the FIX is {fix} pesos per dollar, {word_en} {line.level}",
            summary=(f"El FIX del {day:%d/%m/%Y} es {fix} pesos por dólar, {word_es} tu línea de {line.level}. "
                     "Information only, not advice."),
            severity="your line", licence=LICENCE, basis="inferred", lang="en",
            raw={"line": line.text, "fix": str(fix), "day": f"{day:%Y-%m-%d}"},
        ))
    if items:
        log.info("%s: %d lines crossed", SOURCE, len(items))
    return items


def collector(path: Path) -> Collector:
    return Collector(
        source=SOURCE,
        channel=CHANNEL,
        url="",  # nothing is fetched
        interval_s=15 * 60,
        licence=LICENCE,
        parse_records=lambda data, fetched_at: [],
        derive=partial(derive, path=path),
        panel=Panel(id="peso-alerts", en="Peso — your lines crossed", es="Peso — tus líneas cruzadas",
                    window=PANEL_WINDOW, limit=20, date_only=True),
    )
