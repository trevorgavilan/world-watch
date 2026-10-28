"""OSV.dev (Google) — open-source advisories, here the Bitnami ecosystem: server software by its
plain name (php, python, nginx…), the closest OSV comes to "what I run".

Docs: https://google.github.io/osv.dev/data/ (checked 2026-10-28). Bulk files over plain HTTPS at
storage.googleapis.com/osv-vulnerabilities/<ECOSYSTEM>/: `modified_id.csv` lists every record as
`<modified ISO time>,<id>`, newest first; each record is `<ID>.json` (OSV schema). No key, no
stated rate limit. Licences are per data source (Bitnami's is Apache 2.0); each record is linked.
We read the public listing and fetch the records changed since the last run. Nothing is asked by
name, so the watchlist never leaves the PC (the API's query-by-package would send it).
"""

from __future__ import annotations

import csv
import io
import logging
import re
from datetime import datetime, timedelta, timezone
from functools import partial

from ..item import InvalidItem, make_item
from ..views import Panel
from . import Collector, ParseError, decode_json
from .cisa_kev import CVE_PATTERN

log = logging.getLogger(__name__)

SOURCE = "osv-bitnami"
ECOSYSTEM = "Bitnami"
LICENCE = "OSV.dev, Bitnami Vulnerability Database (Apache 2.0)"
BUCKET = "https://storage.googleapis.com/osv-vulnerabilities"
LISTING = f"{BUCKET}/{ECOSYSTEM}/modified_id.csv"
PAGE_URL = "https://osv.dev/vulnerability/{}"

# An id names a file in our URL: letters, digits and . _ - only — never a '/' or '..' from the listing.
ID_PATTERN = re.compile(r"[A-Za-z0-9][A-Za-z0-9._-]{0,99}")
OVERLAP = timedelta(hours=1)
FIRST_RUN = timedelta(days=3)
CATCH_UP_MAX = timedelta(days=30)
MAX_RECORDS = 200  # per run; a bigger burst keeps the newest and says so in the log


class Listing(list):
    """The decoded `modified_id.csv`: (modified, id) rows. It names records; it is not one."""


def decode(payload: bytes, source: str) -> object:
    if payload.lstrip()[:1] == b"{":
        return decode_json(payload, source)
    try:
        text = payload.decode("utf-8")
    except UnicodeDecodeError as err:
        raise ParseError(f"{source}: listing is not UTF-8") from err
    rows = Listing()
    for row in csv.reader(io.StringIO(text)):
        if len(row) != 2:
            raise ParseError(f"{source}: listing row is not '<time>,<id>': {row[:3]!r}")
        rows.append((row[0].strip(), row[1].strip()))
    return rows


def _osv_time(text: object) -> datetime:
    """OSV times are RFC 3339 UTC, sometimes with nanoseconds: keep the seconds."""
    if not isinstance(text, str) or len(text) < 19:
        raise InvalidItem(f"bad time {text!r}")
    return datetime.fromisoformat(text[:19]).replace(tzinfo=timezone.utc)


def follow(payload: bytes, url: str, last_ok: datetime | None, now: datetime) -> list[str]:
    """From the listing: the records changed since the last good run (newest first, capped)."""
    if url != LISTING:
        return []
    since = now - FIRST_RUN if last_ok is None or last_ok > now else max(last_ok - OVERLAP, now - CATCH_UP_MAX)
    wanted: list[str] = []
    for modified, record_id in decode(payload, SOURCE):
        try:
            when = _osv_time(modified)
        except (InvalidItem, ValueError):
            continue
        if when < since:
            break  # newest first: everything after this is older
        if ID_PATTERN.fullmatch(record_id) and ".." not in record_id:
            wanted.append(f"{BUCKET}/{ECOSYSTEM}/{record_id}.json")
    if len(wanted) > MAX_RECORDS:
        log.info("%s: %d changed records; fetching the newest %d, skipping the rest",
                 SOURCE, len(wanted), MAX_RECORDS)
        wanted = wanted[:MAX_RECORDS]
    return wanted


def packages(record: dict) -> list[list[str]]:
    found = []
    for affected in record.get("affected") or []:
        package = affected.get("package") if isinstance(affected, dict) else None
        if isinstance(package, dict) and isinstance(package.get("name"), str):
            pair = [str(package.get("ecosystem") or ""), package["name"]]
            if pair not in found:
                found.append(pair)
    return found[:50]


def cve_aliases(record: dict) -> list[str]:
    ids = [record.get("id"), *(record.get("aliases") or [])]
    return [a for a in ids if isinstance(a, str) and CVE_PATTERN.fullmatch(a)]


def _build(record: dict, fetched_at: datetime):
    record_id = record["id"]
    if not isinstance(record_id, str) or not ID_PATTERN.fullmatch(record_id):
        raise InvalidItem(f"bad OSV id {record_id!r}")
    if record.get("withdrawn"):
        raise InvalidItem(f"{record_id} was withdrawn")
    pkgs = packages(record)
    names = ", ".join(name for _, name in pkgs[:3])
    cves = cve_aliases(record)
    reduced = {
        "id": record_id,
        "aliases": [a for a in record.get("aliases") or [] if isinstance(a, str)][:20],
        "cves": cves,
        "published": record.get("published"),
        "modified": record.get("modified"),
        "packages": pkgs,
        "summary": str(record.get("summary") or "")[:500],
    }
    title_cve = f" ({cves[0]})" if cves else ""
    return make_item(
        channel="security",
        source=SOURCE,
        native_id=record_id,
        happened_at=_osv_time(record.get("published") or record.get("modified")),
        fetched_at=fetched_at,
        title=f"{names or record_id}{title_cve} — {record.get('summary') or record_id}",
        url=PAGE_URL.format(record_id),
        summary=record.get("details") or record.get("summary") or "",
        licence=LICENCE,
        raw=reduced,
        lang="en",
    )


def parse_records(data: object, fetched_at: datetime) -> list:
    if isinstance(data, Listing):
        return []
    if not isinstance(data, dict) or "id" not in data:
        raise ParseError(f"{SOURCE}: not an OSV record")
    return [partial(_build, data, fetched_at)]


COLLECTOR = Collector(
    source=SOURCE,
    channel="security",
    url=LISTING,
    interval_s=6 * 3600,
    licence=LICENCE,
    parse_records=parse_records,
    follow=follow,
    follow_optional=True,  # a record gone from the bucket (or odd) is skipped; the listing itself must answer
    decode=decode,
    panel=Panel(id="osv", en="Server software advisories (OSV · Bitnami)",
                es="Avisos de software de servidor (OSV · Bitnami)", window=timedelta(days=7), limit=30),
)
