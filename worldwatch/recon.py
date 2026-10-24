"""Morning Recon v0 — picks what the page shows and writes it (HTML + a Markdown twin).

No model: every line is what a source reported (D-8). Times are shown in
Mexico City time, which has been UTC-6 all year since Mexico dropped DST in 2022
(a fixed offset, so no tz database is needed on Windows).
"""

from __future__ import annotations

import contextlib
import os
import tempfile
from dataclasses import dataclass, field
from datetime import datetime, timedelta, timezone
from pathlib import Path

from .collectors import Collector
from .item import iso_utc, parse_iso_utc
from .store import Store

CDMX = timezone(timedelta(hours=-6), "CDMX")
STALE_FACTOR = 3  # a source is stale when its last success is older than 3 intervals

QUAKE_WINDOW = timedelta(hours=24)
KEV_WINDOW = timedelta(days=7)
NEWS_WINDOW = timedelta(hours=24)
QUAKE_LIMIT = 12
KEV_LIMIT = 15
NEWS_LIMIT = 10

CREDITS = [
    ("usgs-quakes", "Credit: U.S. Geological Survey (public domain)", "https://earthquake.usgs.gov/"),
    ("cisa-kev", "CISA Known Exploited Vulnerabilities catalog (CC0 1.0)", "https://www.cisa.gov/known-exploited-vulnerabilities-catalog"),
    ("gdelt", "News lists from the GDELT Project — gdeltproject.org", "https://www.gdeltproject.org/"),
]


@dataclass
class Group:
    en: str
    es: str
    rows: list
    news_lang: str | None = None


@dataclass
class Section:
    key: str
    en: str
    es: str
    groups: list[Group] = field(default_factory=list)


@dataclass
class SourceStatus:
    source: str
    last_ok: datetime | None
    stale: bool
    error: str | None


@dataclass
class Recon:
    now: datetime
    sections: list[Section]
    sources: list[SourceStatus]


def local(moment: datetime) -> datetime:
    return moment.astimezone(CDMX)


def show_time(iso: str) -> str:
    return local(parse_iso_utc(iso)).strftime("%d %b %H:%M")


# Sources that give a date, not a moment: shown as that date, never shifted to CDMX time.
DATE_ONLY_SOURCES = {"cisa-kev"}


def show_event(row) -> str:
    if row["source"] in DATE_ONLY_SOURCES:
        return parse_iso_utc(row["happened_at"]).strftime("%d %b")
    return show_time(row["happened_at"])


def _magnitude(row) -> float:
    try:
        return float((row["severity"] or "M0").split()[0][1:])
    except ValueError:
        return 0.0


def _since(store: Store, source: str, now: datetime, window: timedelta, limit: int):
    return store.items_between(source, iso_utc(now - window), iso_utc(now + timedelta(minutes=5)), limit=limit)


def gather(store: Store, collectors: list[Collector], now: datetime) -> Recon:
    quakes = store.items_between("usgs-quakes", iso_utc(now - QUAKE_WINDOW), iso_utc(now + timedelta(minutes=5)))
    mexico = sorted((q for q in quakes if q["country"] == "MX"), key=_magnitude, reverse=True)
    world = sorted((q for q in quakes if q["country"] != "MX"), key=_magnitude, reverse=True)
    hazards = Section("hazards", "Earthquakes — last 24 h", "Sismos — últimas 24 h", [
        Group("Mexico (USGS place)", "México (lugar según USGS)", mexico[:QUAKE_LIMIT]),
        Group("World — M4.5+, and M3.5+ near Mexico", "Mundo — M4.5+, y M3.5+ cerca de México", world[:QUAKE_LIMIT]),
    ])
    security = Section("security", "Exploited vulnerabilities — added in 7 days",
                       "Vulnerabilidades explotadas — añadidas en 7 días", [
        Group("CISA KEV", "CISA KEV", list(_since(store, "cisa-kev", now, KEV_WINDOW, KEV_LIMIT))),
    ])
    news = Section("news", "News — last 24 h", "Noticias — últimas 24 h", [
        Group("Al Jazeera (English)", "Al Jazeera (inglés)",
              list(_since(store, "gdelt-aljazeera", now, NEWS_WINDOW, NEWS_LIMIT)), news_lang="en"),
        Group("Mexican outlets (Spanish)", "Medios mexicanos (español)",
              list(_since(store, "gdelt-mx", now, NEWS_WINDOW, NEWS_LIMIT)), news_lang="es"),
    ])
    return Recon(now, [hazards, security, news], [_status(store, c, now) for c in collectors])


def _status(store: Store, collector: Collector, now: datetime) -> SourceStatus:
    state = store.source_state(collector.source)
    if state is None or state["last_ok_at"] is None:
        return SourceStatus(collector.source, None, True, state["last_error"] if state else None)
    last_ok = parse_iso_utc(state["last_ok_at"])
    stale = now - last_ok > timedelta(seconds=collector.interval_s * STALE_FACTOR)
    return SourceStatus(collector.source, last_ok, stale, state["last_error"])


def _write_atomic(path: Path, text: str) -> None:
    """Write beside the target under a unique name, then swap it in (two writers never share a temp file)."""
    fd, tmp_name = tempfile.mkstemp(dir=path.parent, prefix=path.name + ".", suffix=".tmp")
    try:
        with os.fdopen(fd, "w", encoding="utf-8", newline="\n") as handle:
            handle.write(text)
        os.replace(tmp_name, path)
    except BaseException:
        with contextlib.suppress(OSError):
            os.unlink(tmp_name)
        raise


def build(store: Store, collectors: list[Collector], now: datetime, out_dir: Path) -> tuple[Path, Path]:
    from .recon_html import render_html
    from .recon_md import render_md

    out_dir.mkdir(parents=True, exist_ok=True)
    recon = gather(store, collectors, now)
    day = local(now).strftime("%Y-%m-%d")
    html_path = out_dir / f"recon-{day}.html"
    md_path = out_dir / f"recon-{day}.md"
    page = render_html(recon)
    _write_atomic(html_path, page)
    _write_atomic(md_path, render_md(recon))
    _write_atomic(out_dir / "recon-latest.html", page)
    return html_path, md_path
