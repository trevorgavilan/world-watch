"""NVD CVE API 2.0 (NIST) — every newly published CVE, with the products it names.

Docs: https://nvd.nist.gov/developers/vulnerabilities and .../developers/start-here (checked 2026-10-28)
Base URL https://services.nvd.nist.gov/rest/json/cves/2.0. Date ranges at most 120 days, ISO 8601;
pages of up to 2,000 (startIndex / resultsPerPage / totalResults). No key: 5 requests in a rolling
30 s; NIST asks for at most one automated update every two hours and six seconds between requests.
Terms: NIST data is public domain; apps must show "This product uses data from the NVD API but is
not endorsed or certified by the NVD." No key is used (D-20), so nothing about Trevor is sent.

We ask for CVEs *published* since the last good fetch (with an overlap), not every modification:
the product names the vendor filed (`affected`) arrive with the CVE itself, and exploitation is
CISA KEV's job. A record keeps only what matching and the page need.
"""

from __future__ import annotations

from datetime import datetime, timedelta, timezone
from functools import partial
from urllib.parse import parse_qs, urlencode, urlsplit

from ..item import InvalidItem, make_item
from ..views import Panel
from . import Collector, ParseError, decode_json
from .cisa_kev import CVE_PATTERN

SOURCE = "nvd-cves"
LICENCE = "US public domain (NVD, NIST) — this product uses data from the NVD API but is not endorsed or certified by the NVD"
BASE = "https://services.nvd.nist.gov/rest/json/cves/2.0"
DETAIL_URL = "https://nvd.nist.gov/vuln/detail/{}"

OVERLAP = timedelta(hours=3)        # a record that reached the API a little after its published time
FIRST_RUN = timedelta(days=7)
CATCH_UP_MAX = timedelta(days=30)   # the alerts look back 30 days; the API allows 120
MAX_PAGES = 20                      # 40,000 CVEs: far over any month


def _stamp(moment: datetime) -> str:
    return moment.astimezone(timezone.utc).strftime("%Y-%m-%dT%H:%M:%S.000Z")


def url_for(last_ok: datetime | None, now: datetime) -> list[str]:
    if last_ok is None or last_ok > now:  # first run, or a clock that ran ahead
        start = now - FIRST_RUN
    else:
        start = max(last_ok - OVERLAP, now - CATCH_UP_MAX)
    return [page_url(start, now, 0)]


def page_url(start: datetime, end: datetime, index: int) -> str:
    query = urlencode({"pubStartDate": _stamp(start), "pubEndDate": _stamp(end), "startIndex": index})
    return f"{BASE}?{query}&noRejected"


def follow(payload: bytes, url: str, last_ok, now) -> list[str]:
    """The next page, while the API says there are more results than this page reached."""
    data = decode_json(payload, SOURCE)
    query = parse_qs(urlsplit(url).query)
    try:
        start = int(query["startIndex"][0])  # where we asked to start, not what the page claims
        per_page, total = int(data["resultsPerPage"]), int(data["totalResults"])
    except (KeyError, IndexError, TypeError, ValueError) as err:
        raise ParseError(f"{SOURCE}: no paging fields") from err
    if start >= total:
        return []
    if per_page <= 0:
        raise ParseError(f"{SOURCE}: an empty page at {start} of {total}")
    following = start + per_page
    if following >= total:
        return []
    if following // per_page >= MAX_PAGES:
        raise ParseError(f"{SOURCE}: {total} results is more than {MAX_PAGES} pages")
    return [f"{BASE}?" + urlencode({"pubStartDate": query["pubStartDate"][0], "pubEndDate": query["pubEndDate"][0],
                                     "startIndex": following}) + "&noRejected"]


def _nvd_time(text: object) -> datetime:
    """NVD times are UTC without a zone: "2026-10-21T14:17:09.357"."""
    if not isinstance(text, str):
        raise InvalidItem("no time")
    return datetime.fromisoformat(text[:19]).replace(tzinfo=timezone.utc)


def products(cve: dict) -> list[list[str]]:
    """(vendor, product) pairs: what the vendor filed (`affected`) and NVD's own CPE names."""
    found: list[list[str]] = []
    for block in cve.get("affected") or []:
        for entry in (block.get("affectedData") or []) if isinstance(block, dict) else []:
            if isinstance(entry, dict) and isinstance(entry.get("product"), str):
                found.append([str(entry.get("vendor") or ""), entry["product"]])
    for config in cve.get("configurations") or []:
        for node in (config.get("nodes") or []) if isinstance(config, dict) else []:
            for match in (node.get("cpeMatch") or []) if isinstance(node, dict) else []:
                if not isinstance(match, dict):
                    continue
                parts = str(match.get("criteria", "")).split(":")
                if match.get("vulnerable") and len(parts) > 4 and parts[3] not in ("*", "-"):
                    found.append([parts[3], parts[4]])
    unique: list[list[str]] = []
    for pair in found:
        if pair not in unique:
            unique.append(pair)
    return unique[:50]


def cvss(cve: dict) -> tuple[float, str] | None:
    """The newest CVSS version present: (base score, severity)."""
    metrics = cve.get("metrics") if isinstance(cve.get("metrics"), dict) else {}
    for key in ("cvssMetricV40", "cvssMetricV31", "cvssMetricV30", "cvssMetricV2"):
        for metric in metrics.get(key) or []:
            data = metric.get("cvssData") if isinstance(metric, dict) else None
            if not isinstance(data, dict):
                continue
            score = data.get("baseScore")
            if isinstance(score, (int, float)) and not isinstance(score, bool):
                severity = data.get("baseSeverity") or metric.get("baseSeverity") or ""
                if not isinstance(severity, str):
                    severity = ""
                return float(score), str(severity).lower()
    return None


def _build(vuln: dict, fetched_at: datetime):
    cve = vuln["cve"]
    cve_id = cve["id"]
    if not isinstance(cve_id, str) or not CVE_PATTERN.fullmatch(cve_id):
        raise InvalidItem(f"bad CVE id {cve_id!r}")
    text = next((d.get("value") for d in cve.get("descriptions") or [] if d.get("lang") == "en"), "") or ""
    pairs = products(cve)
    score = cvss(cve)
    named = ", ".join(" ".join(p for p in pair if p and p.lower() != "n/a") for pair in pairs[:3])
    summary = text
    if score:
        summary = f"CVSS {score[0]:g} {score[1]}. {summary}"
    reduced = {
        "id": cve_id,
        "published": cve.get("published"),
        "lastModified": cve.get("lastModified"),
        "vulnStatus": cve.get("vulnStatus"),
        "products": pairs,
        "cvss": list(score) if score else None,
        "cisaExploitAdd": cve.get("cisaExploitAdd"),
        "description": text[:2000],
    }
    return make_item(
        channel="security",
        source=SOURCE,
        native_id=cve_id,
        happened_at=_nvd_time(cve.get("published")),
        fetched_at=fetched_at,
        title=f"{cve_id} — {named or 'product not named yet'}",
        url=DETAIL_URL.format(cve_id),
        summary=summary,
        severity=f"CVSS {score[0]:g} {score[1]}".strip() if score else None,
        licence=LICENCE,
        raw=reduced,
        lang="en",
    )


def parse_records(data: object, fetched_at: datetime) -> list:
    if not isinstance(data, dict) or not isinstance(data.get("vulnerabilities"), list):
        raise ParseError(f"{SOURCE}: no 'vulnerabilities' list")
    return [partial(_build, vuln, fetched_at) for vuln in data["vulnerabilities"]
            if isinstance(vuln, dict) and isinstance(vuln.get("cve"), dict)]


COLLECTOR = Collector(
    source=SOURCE,
    channel="security",
    url=BASE,
    interval_s=2 * 3600,  # NIST: no more than once every two hours
    licence=LICENCE,
    parse_records=parse_records,
    url_for=url_for,
    follow=follow,
    min_retry_s=2 * 3600,  # a failure waits the same two hours: NIST's rule holds when NVD has trouble too
    panel=Panel(id="nvd", en="New CVEs (NVD)", es="CVE nuevas (NVD)", window=timedelta(days=2), limit=40),
)
