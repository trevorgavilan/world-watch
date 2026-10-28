"""One adapter per source. Each is a Collector: where to fetch, how often,
and `parse` turning the raw bytes into Items. Fetching is kept outside `parse`,
so tests can feed saved real responses and the live feed through the same code.
"""

from __future__ import annotations

import json
import logging
from dataclasses import dataclass
from datetime import datetime
from pathlib import Path
from typing import Callable

from ..http import RateLimited
from ..item import Item
from ..views import Layer, Panel

log = logging.getLogger(__name__)

RATE_LIMIT_TEXT = "Please limit requests"


class ParseError(Exception):
    """The payload was not what the source documents; nothing was stored."""


@dataclass(frozen=True)
class Collector:
    source: str
    channel: str
    url: str
    interval_s: int
    licence: str
    parse_records: Callable[[object, datetime], list]  # decoded JSON -> builders
    # (last good fetch or None, now) -> URLs: lets a source catch up after the PC was off for a while.
    # A run counts only when every URL answered, so a failed catch-up keeps the old mark.
    url_for: Callable[[datetime | None, datetime], list[str]] | None = None
    layer: Layer | None = None  # how the source shows on the Board (views.py); None: not on the globe
    panel: Panel | None = None
    # (payload, its URL, last good fetch, now) -> more URLs for the same run: the next page of a paged
    # API, or the records a listing names. Each must answer too, or the run fails and the mark stays.
    follow: Callable[[bytes, str, datetime | None, datetime], list[str]] | None = None
    follow_optional: bool = False  # a follow-up that fails is skipped and logged (one bad record of many)
    min_retry_s: int = 0  # never retry sooner than this after a failure (NVD: two hours)
    decode: Callable[[bytes, str], object] | None = None  # (payload, source) -> data; JSON when None
    # (store, now) -> Items worked out from what is already stored, instead of fetching (the watchlist).
    derive: Callable[[object, datetime], list[Item]] | None = None

    def fetch_urls(self, last_ok: datetime | None, now: datetime) -> list[str]:
        return list(self.url_for(last_ok, now)) if self.url_for else [self.url]

    def parse(self, payload: bytes, fetched_at: datetime) -> list[Item]:
        data = (self.decode or decode_json)(payload, self.source)
        items: list[Item] = []
        skipped = 0
        for build in self.parse_records(data, fetched_at):
            try:
                items.append(build())
            except Exception as err:  # noqa: BLE001 — one odd record (an overflowing time…) never sinks the batch
                skipped += 1
                log.debug("%s: skipped a record: %s", self.source, err)
        if skipped:
            log.info("%s: skipped %d malformed records", self.source, skipped)
        return items


def decode_json(payload: bytes, source: str) -> object:
    try:
        text = payload.decode("utf-8")
    except UnicodeDecodeError as err:
        raise ParseError(f"{source}: not UTF-8") from err
    if text.lstrip().startswith(RATE_LIMIT_TEXT):  # GDELT sometimes says "slow down" with a 200
        raise RateLimited(f"{source}: rate-limit text with HTTP 200", None)
    try:
        # strict=False: GDELT titles sometimes carry raw control characters.
        return json.loads(text, strict=False)
    except json.JSONDecodeError as err:
        raise ParseError(f"{source}: not JSON ({text[:80]!r})") from err


def all_collectors(base: Path | None = None) -> list[Collector]:
    """The sources in the run. GDELT is parked (D-16): it refused most calls; its adapter and
    tests stay, and it returns by adding `*gdelt.COLLECTORS` here. The status pages (Task 3b) feed the same alerts. The watchlist alerts come first,
    so they lead the Board (the runner still derives them after the fetches); their list lives in
    `<base>/watchlist.txt` (D-20)."""
    from . import cisa_kev, epss, my_stack, nvd, osv, status_pages, usgs

    watchlist = (base or Path(__file__).resolve().parents[2] / "data") / "watchlist.txt"
    return [my_stack.collector(watchlist), usgs.COLLECTOR, cisa_kev.COLLECTOR, nvd.COLLECTOR, osv.COLLECTOR,
            epss.COLLECTOR, *status_pages.COLLECTORS]
