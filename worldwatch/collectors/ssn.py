"""Servicio Sismológico Nacional (UNAM) — the latest quakes it located, as RSS.

Feed: http://www.ssn.unam.mx/rss/ultimos-sismos.xml (linked from www.ssn.unam.mx; the site's
https refused connections on 2026-11-09). The last 15 quakes: a busy day has more, so it is read
every 5 minutes; after the PC was off USGS's catch-up covers M3.5+ around Mexico.
Each item: "<magnitude>, <place>" as the title, "Fecha:YYYY-MM-DD HH:MM:SS (Hora de México)",
"Lat/Lon" and "Profundidad" in the description, geo:lat / geo:long. Mexico City time is UTC-6 all
year since 2022. No event id: a quake is its time to the second.
Terms (www.ssn.unam.mx/aviso-legal, "Términos de Libre Uso"): free use for any purpose; citing the
source is the only requirement; never present it as UNAM's official position.
"""

from __future__ import annotations

import re
import xml.etree.ElementTree as ET
from datetime import datetime, timedelta, timezone
from functools import partial
from urllib.parse import quote

from ..item import make_item
from ..views import Layer
from . import Collector, ParseError, usgs

SOURCE = "ssn-quakes"
URL = "http://www.ssn.unam.mx/rss/ultimos-sismos.xml"
LICENCE = ("Servicio Sismológico Nacional (SSN), Instituto de Geofísica, UNAM — free use with credit "
           "(Términos de Libre Uso)")
MEXICO_TIME = timezone(timedelta(hours=-6), "CDMX")
GEO = "{http://www.w3.org/2003/01/geo/wgs84_pos#}"
WHEN = re.compile(r"Fecha:\s*(\d{4}-\d{2}-\d{2} \d{2}:\d{2}:\d{2})")
DEPTH = re.compile(r"Profundidad:\s*([\d.]+)\s*km")
TITLE = re.compile(r"^\s*([\d.]+)\s*,\s*(.+)$")
DECLARED = re.compile(r"""^﻿?\s*<\?xml[^>]*\bencoding\s*=\s*["']([^"']+)["']""")


def decode_rss(payload: bytes, source: str) -> ET.Element:
    """An RSS document, or ParseError. Only UTF-8 is read, and a DTD or entity declaration is refused
    before parsing: the feed never needs one, and it is how XML bombs work (the feed is plain http,
    so anyone on the path could send one). Another encoding could hide the declaration from the check."""
    try:
        text = payload.decode("utf-8")
    except UnicodeDecodeError as err:
        raise ParseError(f"{source}: not UTF-8") from err
    declared = DECLARED.match(text)
    if "\x00" in text or (declared and declared.group(1).lower().replace("_", "-") != "utf-8"):
        raise ParseError(f"{source}: only UTF-8 XML is read")
    upper = text.upper()
    if "<!DOCTYPE" in upper or "<!ENTITY" in upper:
        raise ParseError(f"{source}: XML with a DTD or entities refused")
    try:
        root = ET.fromstring(payload)
    except ET.ParseError as err:
        raise ParseError(f"{source}: not XML ({err})") from err
    if root.tag != "rss" or root.find("channel") is None:
        raise ParseError(f"{source}: not an RSS feed")
    return root


def _text(node: ET.Element, tag: str) -> str:
    found = node.find(tag)
    return (found.text or "").strip() if found is not None else ""


def _build(node: ET.Element, fetched_at: datetime):
    title, description = _text(node, "title"), _text(node, "description")
    match = TITLE.match(title)
    when = WHEN.search(description)
    if not match or not when:
        raise ValueError("no magnitude or no time")
    mag = float(match.group(1))
    place = re.sub(r"\s+", " ", match.group(2)).strip()
    happened = datetime.strptime(when.group(1), "%Y-%m-%d %H:%M:%S").replace(tzinfo=MEXICO_TIME)
    lat, lon = float(_text(node, f"{GEO}lat")), float(_text(node, f"{GEO}long"))
    depth = DEPTH.search(description)
    link = _text(node, "link")
    return make_item(
        channel="hazards",
        source=SOURCE,
        native_id=happened.astimezone(timezone.utc).strftime("%Y-%m-%dT%H:%M:%SZ"),
        happened_at=happened,
        fetched_at=fetched_at,
        title=f"M{mag:.1f} — {place}",
        url=quote(link, safe=":/?&=%#") if link else None,  # the feed's links carry raw spaces
        summary=f"Profundidad {float(depth.group(1)):.0f} km." if depth else "",
        lat=lat,
        lon=lon,
        severity=f"M{mag:.1f}",
        licence=LICENCE,
        raw={"title": title, "description": description, "link": link, "lat": lat, "lon": lon, "mag": mag},
        lang="es",
    )


def parse_records(root: object, fetched_at: datetime) -> list:
    if not isinstance(root, ET.Element):
        raise ParseError(f"{SOURCE}: not an RSS feed")
    return [partial(_build, node, fetched_at) for node in root.iter("item")]


COLLECTOR = Collector(
    source=SOURCE,
    channel="hazards",
    url=URL,
    interval_s=5 * 60,
    licence=LICENCE,
    parse_records=parse_records,
    decode=decode_rss,
    layer=Layer(id="ssn-quakes", en="Quakes in Mexico (SSN)", es="Sismos en México (SSN)",
                window=timedelta(days=7), limit=1000, weight=usgs.weight),
)
