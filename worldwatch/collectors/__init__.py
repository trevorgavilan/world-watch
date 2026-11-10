"""One adapter per source. Each is a Collector: where to fetch, how often,
and `parse` turning the raw bytes into Items. Fetching is kept outside `parse`,
so tests can feed saved real responses and the live feed through the same code.
"""

from __future__ import annotations

import json
import logging
import re
import xml.etree.ElementTree as ET
from dataclasses import dataclass
from datetime import datetime
from pathlib import Path
from typing import Callable

from ..http import RateLimited
from ..item import Item
from ..views import Layer, Panel

log = logging.getLogger(__name__)

RATE_LIMIT_TEXT = "Please limit requests"
XML_DECLARED = re.compile(r"""^﻿?\s*<\?xml[^>]*\bencoding\s*=\s*["']([^"']+)["']""")


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
    each_optional: bool = False  # with follow_optional: the first URL may fail too; the run fails only if none answers
    min_retry_s: int = 0  # never retry sooner than this after a failure (NVD: two hours)
    decode: Callable[[bytes, str], object] | None = None  # (payload, source) -> data; JSON when None
    # (store, now) -> Items worked out from what is already stored, instead of fetching (the watchlist).
    derive: Callable[[object, datetime], list[Item]] | None = None
    # () -> the source's own request headers (an API key); raises keys.MissingKey while the key is not set.
    headers: Callable[[], dict[str, str]] | None = None
    parse_with_url: bool = False  # parse_records(data, fetched_at, url): the answer doesn't say what it is (FRED)

    def request_headers(self) -> dict[str, str] | None:
        return self.headers() if self.headers else None

    def fetch_urls(self, last_ok: datetime | None, now: datetime) -> list[str]:
        return list(self.url_for(last_ok, now)) if self.url_for else [self.url]

    def parse(self, payload: bytes, fetched_at: datetime, url: str | None = None) -> list[Item]:
        data = (self.decode or decode_json)(payload, self.source)
        items: list[Item] = []
        skipped = 0
        builds = self.parse_records(data, fetched_at, url) if self.parse_with_url else self.parse_records(data, fetched_at)
        for build in builds:
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


def decode_xml(payload: bytes, source: str) -> ET.Element:
    """An XML document's root, or ParseError. Only UTF-8 is read, and a DTD or entity declaration is
    refused before parsing: no feed we read needs one, and it is how XML bombs work. Another encoding
    could hide the declaration from the check."""
    try:
        text = payload.decode("utf-8")
    except UnicodeDecodeError as err:
        raise ParseError(f"{source}: not UTF-8") from err
    declared = XML_DECLARED.match(text)
    if "\x00" in text or (declared and declared.group(1).lower().replace("_", "-") != "utf-8"):
        raise ParseError(f"{source}: only UTF-8 XML is read")
    upper = text.upper()
    if "<!DOCTYPE" in upper or "<!ENTITY" in upper:
        raise ParseError(f"{source}: XML with a DTD or entities refused")
    try:
        return ET.fromstring(payload)
    except ET.ParseError as err:
        raise ParseError(f"{source}: not XML ({err})") from err


def all_collectors(base: Path | None = None) -> list[Collector]:
    """The sources in the run. GDELT is parked (D-16): it refused most calls; its adapter and
    tests stay, and it returns by adding `*gdelt.COLLECTORS` here. The status pages (Task 3b) feed the same alerts. Task 4 adds the hazards and Mexico sources, and
    the near-CDMX quake alerts worked out from USGS and the SSN. The Middle East watch adds the live streams
    and FIRMS heat detections in the region. Task 5 adds the markets sources (information only)
    and the peso alerts worked out from Trevor's lines. The watchlist alerts come first,
    so they lead the Board (the runner still derives them after the fetches); their list lives in
    `<base>/watchlist.txt` (D-20)."""
    from . import (banxico, cisa_kev, coingecko, eonet, epss, fed_press, firms, fred, gdacs, live_streams, my_stack,
                   near_cdmx, nvd, osv, peso_alert, smn, ssn, status_pages, swpc, twelvedata, usgs)

    data = base or Path(__file__).resolve().parents[2] / "data"
    watchlist = data / "watchlist.txt"
    markets = data / "markets.txt"  # Task 5: Trevor's peso lines and tickers
    return [my_stack.collector(watchlist), peso_alert.collector(markets), near_cdmx.COLLECTOR, usgs.COLLECTOR, ssn.COLLECTOR, cisa_kev.COLLECTOR,
            nvd.COLLECTOR, osv.COLLECTOR, epss.COLLECTOR, *status_pages.COLLECTORS,
            gdacs.COLLECTOR, eonet.COLLECTOR, firms.COLLECTOR, swpc.COLLECTOR, smn.COLLECTOR,
            *live_streams.COLLECTORS, firms.MIDEAST_COLLECTOR,
            *banxico.COLLECTORS, fred.COLLECTOR, fred.CALENDAR, coingecko.COLLECTOR, twelvedata.collector(markets),
            fed_press.COLLECTOR]
