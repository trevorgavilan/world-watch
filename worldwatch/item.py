"""The adapter contract: every collector turns a source's records into Items.

Everything a source sends is untrusted. `make_item` is the boundary: it cleans
and caps every text field, accepts only http(s) links, and refuses a record
that lacks what the contract needs (D-8: source, event time, fetch time,
licence, and whether it is reported or inferred).
"""

from __future__ import annotations

import hashlib
import html
import json
import re
from dataclasses import dataclass
from datetime import datetime, timezone
from html.parser import HTMLParser
from urllib.parse import urlsplit

TITLE_MAX = 300
SUMMARY_MAX = 1000
URL_MAX = 2000
RAW_MAX = 64_000

BASES = ("reported", "inferred")
LANGS = ("en", "es")

_CONTROL = re.compile(r"[\x00-\x08\x0b\x0c\x0e-\x1f\x7f]")
_SPACE = re.compile(r"\s+")


class InvalidItem(ValueError):
    """A record that cannot become an Item; the collector skips it."""


@dataclass(frozen=True)
class Item:
    id: str
    channel: str
    source: str
    happened_at: str  # ISO 8601 UTC, "2026-10-23T23:30:00Z"
    fetched_at: str
    title: str
    url: str | None
    summary: str
    lat: float | None
    lon: float | None
    country: str | None
    severity: str | None
    licence: str
    basis: str  # "reported" (the source says so) or "inferred" (we worked it out)
    lang: str | None
    raw: str  # the original record as JSON, so a better parser can re-run


class _TextOnly(HTMLParser):
    def __init__(self) -> None:
        super().__init__(convert_charrefs=True)
        self.parts: list[str] = []

    def handle_data(self, data: str) -> None:
        self.parts.append(data)


def clean_text(value: object, limit: int) -> str:
    """Plain text: tags stripped, entities decoded, control chars removed, capped."""
    if value is None:
        return ""
    text = str(value)
    if "<" in text:
        parser = _TextOnly()
        parser.feed(text)
        parser.close()
        text = "".join(parser.parts)
    text = html.unescape(text)
    text = _CONTROL.sub("", text)
    text = _SPACE.sub(" ", text).strip()
    if len(text) > limit:
        text = text[: limit - 1].rstrip() + "…"
    return text


def clean_url(value: object) -> str | None:
    """An http(s) URL with a host, or None. Anything else (javascript:, data:) is dropped."""
    if not isinstance(value, str):
        return None
    url = value.strip()
    if not url or len(url) > URL_MAX or _CONTROL.search(url) or " " in url:
        return None
    try:
        parts = urlsplit(url)
    except ValueError:
        return None
    if parts.scheme.lower() not in ("http", "https") or not parts.hostname:
        return None
    return url


def iso_utc(moment: datetime) -> str:
    if moment.tzinfo is None:
        raise InvalidItem("naive datetime")
    return moment.astimezone(timezone.utc).strftime("%Y-%m-%dT%H:%M:%SZ")


def parse_iso_utc(text: str) -> datetime:
    return datetime.strptime(text, "%Y-%m-%dT%H:%M:%SZ").replace(tzinfo=timezone.utc)


def item_id(source: str, native_id: str) -> str:
    return hashlib.sha256(f"{source}\x1f{native_id}".encode("utf-8")).hexdigest()[:32]


def _coord(value: object, low: float, high: float) -> float | None:
    if isinstance(value, bool) or not isinstance(value, (int, float)):
        return None
    number = float(value)
    if number != number or not low <= number <= high:  # NaN or out of range
        return None
    return number


def make_item(
    *,
    channel: str,
    source: str,
    native_id: str,
    happened_at: datetime,
    fetched_at: datetime,
    title: object,
    url: object,
    summary: object,
    licence: str,
    raw: object,
    lat: object = None,
    lon: object = None,
    country: object = None,
    severity: object = None,
    basis: str = "reported",
    lang: str | None = None,
) -> Item:
    if not native_id:
        raise InvalidItem("no native id")
    if not licence:
        raise InvalidItem("no licence")
    if basis not in BASES:
        raise InvalidItem(f"basis must be one of {BASES}")
    if lang is not None and lang not in LANGS:
        lang = None
    clean_title = clean_text(title, TITLE_MAX)
    if not clean_title:
        raise InvalidItem("no title")
    point_lat = _coord(lat, -90.0, 90.0)
    point_lon = _coord(lon, -180.0, 180.0)
    if point_lat is None or point_lon is None:
        point_lat = point_lon = None
    raw_json = json.dumps(raw, ensure_ascii=False, sort_keys=True, default=str)
    if len(raw_json) > RAW_MAX:
        raw_json = json.dumps({"truncated": True, "head": raw_json[:RAW_MAX]})
    return Item(
        id=item_id(source, str(native_id)),
        channel=channel,
        source=source,
        happened_at=iso_utc(happened_at),
        fetched_at=iso_utc(fetched_at),
        title=clean_title,
        url=clean_url(url),
        summary=clean_text(summary, SUMMARY_MAX),
        lat=point_lat,
        lon=point_lon,
        country=clean_text(country, 80) or None,
        severity=clean_text(severity, 80) or None,
        licence=licence,
        basis=basis,
        lang=lang,
        raw=raw_json,
    )
