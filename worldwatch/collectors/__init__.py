"""One adapter per source. Each is a Collector: where to fetch, how often,
and `parse` turning the raw bytes into Items. Fetching is kept outside `parse`,
so tests can feed saved real responses and the live feed through the same code.
"""

from __future__ import annotations

import json
import logging
from dataclasses import dataclass
from datetime import datetime
from typing import Callable

from ..item import InvalidItem, Item

log = logging.getLogger(__name__)


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

    def parse(self, payload: bytes, fetched_at: datetime) -> list[Item]:
        data = decode_json(payload, self.source)
        items: list[Item] = []
        skipped = 0
        for build in self.parse_records(data, fetched_at):
            try:
                items.append(build())
            except (InvalidItem, KeyError, TypeError, ValueError) as err:
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
    try:
        # strict=False: GDELT titles sometimes carry raw control characters.
        return json.loads(text, strict=False)
    except json.JSONDecodeError as err:
        raise ParseError(f"{source}: not JSON ({text[:80]!r})") from err


def all_collectors() -> list[Collector]:
    from . import cisa_kev, gdelt, usgs

    return [usgs.COLLECTOR, cisa_kev.COLLECTOR, *gdelt.COLLECTORS]
