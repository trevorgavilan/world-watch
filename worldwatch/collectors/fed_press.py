"""Federal Reserve Board — monetary policy press releases (FOMC statements, minutes), Task 5's
"why it moved (reported)": what the central bank itself said, until the news channel (Task 7b).

RSS 2.0, UTF-8: https://www.federalreserve.gov/feeds/press_monetary.xml (listed on
federalreserve.gov/feeds/feeds.htm); each item has title, link, guid, description, category and
pubDate (RFC 822, GMT). Board publications are US Government works, public domain.
"""

from __future__ import annotations

from datetime import datetime, timedelta, timezone
from email.utils import parsedate_to_datetime
from functools import partial

from ..item import make_item
from ..views import Panel
from . import Collector, ParseError, decode_xml

SOURCE = "fed-press"
URL = "https://www.federalreserve.gov/feeds/press_monetary.xml"
LICENCE = "Board of Governors of the Federal Reserve System — US public domain"
MAX_ITEMS = 50


def _text(node, tag: str) -> str:
    found = node.find(tag)
    return (found.text or "").strip() if found is not None else ""


def _build(node, fetched_at: datetime):
    when = parsedate_to_datetime(_text(node, "pubDate"))
    if when.tzinfo is None:
        when = when.replace(tzinfo=timezone.utc)
    link = _text(node, "link")
    return make_item(channel="markets", source=SOURCE, native_id=_text(node, "guid") or link, happened_at=when,
                     fetched_at=fetched_at, title=_text(node, "title"), url=link,
                     summary=_text(node, "description"), severity=_text(node, "category") or None,
                     licence=LICENCE, raw={k: _text(node, k) for k in ("title", "link", "guid", "category", "pubDate")},
                     lang="en")


def parse_records(root, fetched_at: datetime) -> list:
    channel = root.find("channel") if root.tag == "rss" else None
    if channel is None:
        raise ParseError(f"{SOURCE}: not an RSS feed")
    return [partial(_build, node, fetched_at) for node in channel.findall("item")[:MAX_ITEMS]]


COLLECTOR = Collector(
    source=SOURCE,
    channel="markets",
    url=URL,
    interval_s=2 * 60 * 60,
    licence=LICENCE,
    parse_records=parse_records,
    decode=decode_xml,
    panel=Panel(id="fed-statements", en="Why it moved — the Fed's own statements",
                es="Por qué se movió — comunicados de la Fed", window=timedelta(days=90),
                limit=10),
)
