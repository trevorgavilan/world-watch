"""The whole answer of /api/markets, read-only: the numbers (view.py), the peso lines and the alerts
they raised, the calendar, the practice portfolio, the glossary, and the problems found in
data/markets.txt. The page shows it; nothing here writes.
"""

from __future__ import annotations

from datetime import datetime, timedelta
from pathlib import Path

from ..item import iso_utc
from ..store import Store
from . import CHANNEL, calendar, glossary, paper, rules
from .catalog import watch_instrument
from .view import markets_view

ALERT_SOURCE = "peso-alert"
ALERT_WINDOW = timedelta(days=30)
STATEMENTS_SOURCE = "fed-press"
STATEMENTS = 5
NOT_SHOWN = {"peso-alert", "fed-press", "fred-calendar"}  # their own blocks, not number tiles


def _rows(store: Store, source: str, now: datetime, window: timedelta, limit: int) -> list[dict]:
    return [{"title": r["title"], "summary": r["summary"], "url": r["url"], "at": r["happened_at"],
             "fetched_at": r["fetched_at"], "basis": r["basis"], "source": r["source"]}
            for r in store.items_between(source, iso_utc(now - window), iso_utc(now + timedelta(minutes=5)),
                                         limit=limit)]


def markets_body(store: Store, collectors: list, data_dir: Path, now: datetime) -> dict:
    sources = [c.source for c in collectors if c.channel == CHANNEL]
    number_sources = [s for s in sources if s not in NOT_SHOWN]
    lines = rules.load(data_dir / "markets.txt")
    watch = [watch_instrument(s) for s in lines.watch] if "twelvedata" in sources else []
    try:
        book = paper.summary(paper.load(data_dir / "paper.json"), store, now)
        book_problem = None
    except (paper.PaperError, ValueError, KeyError, TypeError) as err:
        book, book_problem = None, str(err)[:200]
    extra = {
        "lines": [line.text for line in lines.peso],
        "watch": lines.watch,
        "problems": lines.problems,
        "alerts": _rows(store, ALERT_SOURCE, now, ALERT_WINDOW, 10) if ALERT_SOURCE in sources else [],
        "statements": _rows(store, STATEMENTS_SOURCE, now, timedelta(days=90), STATEMENTS)
        if STATEMENTS_SOURCE in sources else [],
        "calendar": calendar.upcoming(store, now),
        "paper": book,
        "paper_problem": book_problem,
        "glossary": glossary.glossary(),
    }
    return markets_view(store, number_sources, now, watch=watch, extra=extra)
