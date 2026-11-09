"""NOAA SWPC — space weather alerts, watches and warnings (geomagnetic storms, radio blackouts…).

JSON: https://services.swpc.noaa.gov/products/alerts.json (listed on spaceweather.gov's Data
Access page as the JSON service) — about a month of messages, each {product_id, issue_datetime
(UTC), message}. Space weather has no place on the globe: a panel, not a layer.
Terms: US Government work, public domain; SWPC asks for credit ("Space Weather Prediction Center,
NOAA") and that changed material never be passed off as official.
"""

from __future__ import annotations

import re
from datetime import datetime, timedelta, timezone
from functools import partial

from ..item import make_item
from ..views import Panel
from . import Collector, ParseError

SOURCE = "noaa-swpc"
URL = "https://services.swpc.noaa.gov/products/alerts.json"
PAGE_URL = "https://www.spaceweather.gov/products/alerts-watches-and-warnings"
LICENCE = "NOAA Space Weather Prediction Center — US public domain"
SERIAL = re.compile(r"Serial Number:\s*(\d+)")
SCALE = re.compile(r"NOAA Scale:\s*([GSR]\d)\b")
HEADLINE = re.compile(r"^(?:[A-Z][A-Z ]*):\s+\S")  # "WARNING: Geomagnetic K-index of 4 expected"
HEADER_KEYS = ("Space Weather Message Code", "Serial Number", "Issue Time")


def _headline(lines: list[str]) -> tuple[str, int]:
    for n, line in enumerate(lines):
        if HEADLINE.match(line) and not line.startswith(HEADER_KEYS):
            return line, n
    raise ValueError("no headline")


def _build(record: dict, fetched_at: datetime):
    message = str(record["message"]).replace("\r", "")
    lines = [line.strip() for line in message.split("\n") if line.strip()]
    headline, at = _headline(lines)
    issued = datetime.strptime(record["issue_datetime"][:19], "%Y-%m-%d %H:%M:%S").replace(tzinfo=timezone.utc)
    serial = SERIAL.search(message)
    scale = SCALE.search(message)
    return make_item(
        channel="hazards",
        source=SOURCE,
        native_id=f"{record['product_id']}/{serial.group(1) if serial else record['issue_datetime']}",
        happened_at=issued,
        fetched_at=fetched_at,
        title=headline.title() if headline.isupper() else headline,
        url=PAGE_URL,
        summary=" ".join(line for line in lines[at + 1:] if not line.startswith(("NOAA Space Weather Scale descriptions",
                                                                               "www.swpc.noaa.gov"))),
        severity=scale.group(1) if scale else record["product_id"],
        licence=LICENCE,
        raw=record,
        lang="en",
    )


def parse_records(data: object, fetched_at: datetime) -> list:
    if not isinstance(data, list):
        raise ParseError(f"{SOURCE}: not a list of messages")
    return [partial(_build, record, fetched_at) for record in data]


COLLECTOR = Collector(
    source=SOURCE,
    channel="hazards",
    url=URL,
    interval_s=30 * 60,
    licence=LICENCE,
    parse_records=parse_records,
    panel=Panel(id="space-weather", en="Space weather (NOAA SWPC)", es="Clima espacial (NOAA SWPC)",
                window=timedelta(days=7), limit=60),
)
