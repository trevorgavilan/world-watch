"""EPSS (FIRST) — the chance a CVE is exploited in the next 30 days, re-scored daily.

Docs: https://api.first.org/epss and https://api.first.org/ (checked 2026-10-28). Endpoint
https://api.first.org/data/v1/epss (BETA); `days` = days since the CVE was first scored, `epss-gt`
a floor, `limit` up to 10,000. Public: 1,000 requests a minute. FIRST calls the data "freely and
openly accessible"; we credit FIRST and link the CVE.
We ask one fixed question — recently scored CVEs at 10 % or more — so no CVE we care about is ever
named in a request; the watchlist reads the answer locally.
"""

from __future__ import annotations

from datetime import datetime, timedelta, timezone
from functools import partial
from urllib.parse import urlencode

from ..item import InvalidItem, make_item
from ..views import Panel
from . import Collector, ParseError
from .cisa_kev import CVE_PATTERN

SOURCE = "first-epss"
LICENCE = "EPSS by FIRST.org (freely and openly accessible)"
FLOOR = 0.1
DAYS = 30
URL = "https://api.first.org/data/v1/epss?" + urlencode({"days": DAYS, "epss-gt": FLOOR, "limit": 10000})
CVE_URL = "https://www.cve.org/CVERecord?id={}"


def _probability(value: object) -> float:
    number = float(value)  # the API sends strings: "0.999990000"
    if not 0.0 <= number <= 1.0:
        raise InvalidItem(f"probability {value!r} out of range")
    return number


def _build(row: dict, fetched_at: datetime):
    cve = row["cve"]
    if not isinstance(cve, str) or not CVE_PATTERN.fullmatch(cve):
        raise InvalidItem(f"bad CVE id {cve!r}")
    epss = _probability(row["epss"])
    percentile = _probability(row["percentile"])
    scored = datetime.strptime(row["date"], "%Y-%m-%d").replace(tzinfo=timezone.utc)
    return make_item(
        channel="security",
        source=SOURCE,
        native_id=cve,
        happened_at=scored,
        fetched_at=fetched_at,
        title=f"{cve} — {epss:.1%} chance of exploitation in 30 days",
        url=CVE_URL.format(cve),
        summary=f"EPSS {epss:.5f}, higher than {percentile:.2%} of scored CVEs, on {row['date']}.",
        severity=f"EPSS {epss:.1%}",
        licence=LICENCE,
        raw={"cve": cve, "epss": epss, "percentile": percentile, "date": row["date"]},
        lang="en",
    )


def parse_records(data: object, fetched_at: datetime) -> list:
    if not isinstance(data, dict) or data.get("status") != "OK" or not isinstance(data.get("data"), list):
        raise ParseError(f"{SOURCE}: no 'data' list with status OK")
    if isinstance(data.get("total"), int) and data["total"] > len(data["data"]):
        raise ParseError(f"{SOURCE}: {data['total']} scores but only {len(data['data'])} sent")
    return [partial(_build, row, fetched_at) for row in data["data"] if isinstance(row, dict)]


COLLECTOR = Collector(
    source=SOURCE,
    channel="security",
    url=URL,
    interval_s=12 * 3600,  # scores change once a day
    licence=LICENCE,
    parse_records=parse_records,
    panel=Panel(id="epss", en="New CVEs most likely to be exploited (EPSS ≥ 10 %)",
                es="CVE nuevas con más probabilidad de explotación (EPSS ≥ 10 %)",
                window=timedelta(days=3), limit=30, date_only=True),
)
