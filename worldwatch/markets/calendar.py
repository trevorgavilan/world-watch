"""The economic calendar: rate decisions from each central bank's own published calendar (kept here
by hand, re-checked every year: FINDINGS), and US data releases from FRED (collectors/fred.py
CALENDAR, stored as items dated on the release day).

Checked 2026-11-10 against federalreserve.gov/monetarypolicy/fomccalendars.htm (2027: tentative until
the meeting before each one) and Banxico's 2026 calendar PDF (announcements on Thursdays, 13:00 CDMX;
Banxico has not published 2027's yet).
"""

from __future__ import annotations

import json
from datetime import date, datetime, timedelta

from ..item import iso_utc
from ..store import Store

FOMC_PAGE = "https://www.federalreserve.gov/monetarypolicy/fomccalendars.htm"
BANXICO_PAGE = ("https://www.banxico.org.mx/publicaciones-y-prensa/anuncios-de-las-decisiones-de-politica-monetaria/"
                "anuncios-politica-monetaria-t.html")
CHECKED = "2026-11-10"
AHEAD = timedelta(days=60)
RELEASE_SOURCE = "fred-calendar"

# (day the decision is announced, who, note)
DECISIONS: list[tuple[date, str, str]] = [
    *[(date.fromisoformat(d), "fed", note) for d, note in [
        ("2026-12-09", "with projections"), ("2027-01-27", "tentative"), ("2027-03-17", "with projections, tentative"),
        ("2027-04-28", "tentative"), ("2027-06-09", "with projections, tentative"), ("2027-07-28", "tentative"),
        ("2027-09-15", "with projections, tentative"), ("2027-10-27", "tentative"),
        ("2027-12-08", "with projections, tentative")]],
    (date(2026, 12, 17), "banxico", "13:00 CDMX"),
]
WHO = {
    "fed": ("Federal Reserve rate decision (FOMC)", "Decisión de tasas de la Reserva Federal (FOMC)", FOMC_PAGE),
    "banxico": ("Banco de México rate decision", "Decisión de política monetaria de Banco de México", BANXICO_PAGE),
}


def decisions(today: date) -> list[dict]:
    rows = []
    for day, who, note in DECISIONS:
        if today <= day <= today + AHEAD:
            en, es, page = WHO[who]
            rows.append({"day": day.isoformat(), "en": en, "es": es, "note": note, "url": page,
                         "source": who, "checked": CHECKED})
    return rows


def releases(store: Store, now: datetime) -> list[dict]:
    rows = []
    start = iso_utc(datetime.combine(now.date(), datetime.min.time(), now.tzinfo))
    for row in store.items_between(RELEASE_SOURCE, start, iso_utc(now + AHEAD), limit=200, order="happened_at ASC"):
        raw = json.loads(row["raw"])
        rows.append({"day": row["happened_at"][:10], "en": row["title"], "es": raw.get("es", row["title"]),
                     "note": "US data release", "url": row["url"], "source": "fred", "fetched_at": row["fetched_at"]})
    return rows


def upcoming(store: Store, now: datetime) -> list[dict]:
    return sorted(decisions(now.date()) + releases(store, now), key=lambda r: r["day"])
