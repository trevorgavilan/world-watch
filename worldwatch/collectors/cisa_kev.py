"""CISA Known Exploited Vulnerabilities — CVEs confirmed exploited in the wild.

Feed: https://www.cisa.gov/sites/default/files/feeds/known_exploited_vulnerabilities.json
Schema: .../feeds/known_exploited_vulnerabilities_schema.json
Licence: CC0 1.0 (license.txt beside the feed); no use of the CISA logo or DHS seal.
The whole catalogue (~1,800 entries) comes each time; storing is an upsert.
"""

from __future__ import annotations

import re
from datetime import datetime, timezone
from functools import partial

from ..item import InvalidItem, make_item
from . import Collector, ParseError

SOURCE = "cisa-kev"
LICENCE = "CC0 1.0 (CISA KEV)"
CVE_URL = "https://www.cve.org/CVERecord?id={}"
CVE_PATTERN = re.compile(r"CVE-[0-9]{4}-[0-9]{4,19}")  # the schema's own pattern


def _build(vuln: dict, fetched_at: datetime):
    cve = vuln["cveID"]
    if not isinstance(cve, str) or not CVE_PATTERN.fullmatch(cve):
        raise InvalidItem(f"bad CVE id {cve!r}")
    added = datetime.strptime(vuln["dateAdded"], "%Y-%m-%d").replace(tzinfo=timezone.utc)
    ransomware = vuln.get("knownRansomwareCampaignUse") == "Known"
    vendor = f"{vuln.get('vendorProject', '')} {vuln.get('product', '')}".strip()
    summary = vuln.get("shortDescription", "")
    if vuln.get("dueDate"):
        summary = f"{summary} Federal fix-by date: {vuln['dueDate']}."
    return make_item(
        channel="security",
        source=SOURCE,
        native_id=cve,
        happened_at=added,
        fetched_at=fetched_at,
        title=f"{cve} — {vuln.get('vulnerabilityName') or vendor}",
        url=CVE_URL.format(cve),
        summary=summary,
        severity="ransomware: known" if ransomware else None,
        licence=LICENCE,
        raw=vuln,
        lang="en",
    )


def parse_records(data: object, fetched_at: datetime) -> list:
    if not isinstance(data, dict) or not isinstance(data.get("vulnerabilities"), list):
        raise ParseError(f"{SOURCE}: no 'vulnerabilities' list")
    return [
        partial(_build, vuln, fetched_at)
        for vuln in data["vulnerabilities"]
        if isinstance(vuln, dict)
    ]


COLLECTOR = Collector(
    source=SOURCE,
    channel="security",
    url="https://www.cisa.gov/sites/default/files/feeds/known_exploited_vulnerabilities.json",
    interval_s=6 * 3600,
    licence=LICENCE,
    parse_records=parse_records,
)
