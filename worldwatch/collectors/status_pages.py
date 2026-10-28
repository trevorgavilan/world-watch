"""Official status pages: the outages that CVE feeds can't show, for services with nothing of
Trevor's to patch (GitHub, Cloudflare, Claude, Google Workspace).

Each page answers one fixed question — its own recent incidents — so nothing about the watchlist
goes into a request (D-20); `my_stack` matches the names below against it on this PC.

- Atlassian Statuspage (GitHub, Cloudflare, Claude): `<page>/api/v2/incidents.json`, "the 50 most
  recent incidents" including unresolved ones (each page's /api docs). No key, no stated limit, no
  licence stated: shown with a link back to the incident. Impact is none / minor / major / critical.
- Google Workspace Status Dashboard: `incidents.json`, the "JSON History" link Google's help points
  programmatic users to, schema at `incidents.schema.json`. Impact is SERVICE_INFORMATION /
  SERVICE_DISRUPTION / SERVICE_OUTAGE, read here as none / minor / major.

Every incident is stored reduced to the same shape (`raw`): service, the names it can match
([vendor, product] pairs: the service itself and each affected component or product), impact,
status, when it began and ended, and the newest update's words.
"""

from __future__ import annotations

import re
from datetime import datetime, timedelta, timezone
from functools import partial

from .. import watchlist
from ..item import InvalidItem, make_item
from ..views import Panel
from . import Collector, ParseError

IMPACTS = ("none", "minor", "major", "critical")
GOOGLE_IMPACT = {"SERVICE_INFORMATION": "none", "SERVICE_DISRUPTION": "minor", "SERVICE_OUTAGE": "major"}
INCIDENT_ID = re.compile(r"[A-Za-z0-9]{6,40}")  # goes into the link: never trust it raw
MAX_NAMES = 30
UPDATE_CHARS = 600
INTERVAL_S = 15 * 60
LICENCE = "{}'s public status page (no licence stated; shown with a link to the incident)"


def _time(value: object) -> datetime:
    """Statuspage's '2026-10-28T14:12:53.814Z' and Google's '2026-09-25T15:47:00+00:00'."""
    if not isinstance(value, str):
        raise InvalidItem(f"no time: {value!r}")
    moment = datetime.fromisoformat(value.replace("Z", "+00:00"))
    if moment.tzinfo is None:
        raise InvalidItem(f"time without a zone: {value!r}")
    return moment.astimezone(timezone.utc)


def _iso(value: object) -> str | None:
    return _time(value).strftime("%Y-%m-%dT%H:%M:%SZ") if value else None


def _text(value: object) -> str:
    return value.strip() if isinstance(value, str) else ""


def _pair(vendor: str, name: str) -> list[str]:
    """[vendor, name], or ["", name] when the name already starts with the vendor ("Google Drive")."""
    named = watchlist.norm(name)
    return ["", name] if named == watchlist.norm(vendor) or named.startswith(watchlist.norm(vendor) + " ") \
        else [vendor, name]


def _names(vendor: str, product: str, parts: list) -> list[list[str]]:
    """The service itself, then each affected part under the service's vendor."""
    names = [_pair(vendor, product)]
    for part in parts:
        pair = _pair(vendor, _text(part)) if _text(part) else None
        if pair and pair not in names:
            names.append(pair)
    return names[:MAX_NAMES]


def _incident_item(*, source, service, native_id, url, began, ended, impact, status, title, names,
                   update, fetched_at):
    if impact not in IMPACTS:
        raise InvalidItem(f"unknown impact {impact!r}")
    state = "resolved" if ended else (status or "open")
    words = f"{service}: {'no' if impact == 'none' else impact} impact, {state}." + (f" {update}" if update else "")
    return make_item(
        channel="status", source=source, native_id=native_id, happened_at=_time(began),
        fetched_at=fetched_at, title=f"{service} — {title}", url=url, summary=words,
        severity=None if impact == "none" else f"{impact} impact", licence=LICENCE.format(service),
        raw={"kind": "incident", "service": service, "id": native_id, "names": names, "impact": impact,
             "status": state, "began": _iso(began), "ended": _iso(ended), "update": update},
        lang="en",
    )


# --- Atlassian Statuspage --------------------------------------------------------------------

def _statuspage_build(incident: dict, fetched_at: datetime, *, source, service, vendor, product, page):
    native = incident["id"]
    if not isinstance(native, str) or not INCIDENT_ID.fullmatch(native):
        raise InvalidItem(f"bad incident id {native!r}")
    updates = [u for u in incident.get("incident_updates") or [] if isinstance(u, dict)]
    newest = max(updates, key=lambda u: _text(u.get("created_at")), default={})
    parts = [c.get("name") for c in incident.get("components") or [] if isinstance(c, dict)]
    return _incident_item(
        source=source, service=service, native_id=native, url=f"{page}/incidents/{native}",
        began=incident.get("started_at") or incident.get("created_at"), ended=incident.get("resolved_at"),
        impact=incident.get("impact"), status=_text(incident.get("status")), title=_text(incident.get("name")),
        names=_names(vendor, product, parts), update=_text(newest.get("body"))[:UPDATE_CHARS],
        fetched_at=fetched_at,
    )


def _statuspage_records(data: object, fetched_at: datetime, **site) -> list:
    if not isinstance(data, dict) or not isinstance(data.get("incidents"), list):
        raise ParseError(f"{site['source']}: no 'incidents' list")
    return [partial(_statuspage_build, i, fetched_at, **site) for i in data["incidents"] if isinstance(i, dict)]


def statuspage(source: str, service: str, page: str, *, vendor: str = "", product: str | None = None,
               panel_id: str) -> Collector:
    site = dict(source=source, service=service, vendor=vendor, product=product or service, page=page)
    return Collector(
        source=source, channel="status", url=f"{page}/api/v2/incidents.json", interval_s=INTERVAL_S,
        licence=LICENCE.format(service), parse_records=partial(_statuspage_records, **site),
        panel=Panel(id=panel_id, en=f"{service} status", es=f"Estado de {service}",
                    window=timedelta(days=14), limit=12),
    )


# --- Google Workspace Status Dashboard -------------------------------------------------------

GOOGLE_SOURCE = "google-workspace-status"
GOOGLE_PAGE = "https://www.google.com/appsstatus/dashboard"


def _google_build(incident: dict, fetched_at: datetime):
    native = incident["id"]
    if not isinstance(native, str) or not INCIDENT_ID.fullmatch(native):
        raise InvalidItem(f"bad incident id {native!r}")
    products = [p.get("title") for p in incident.get("affected_products") or [] if isinstance(p, dict)]
    newest = incident.get("most_recent_update") if isinstance(incident.get("most_recent_update"), dict) else {}
    summary = _text(newest.get("text")) or _text(incident.get("external_desc"))
    return _incident_item(
        source=GOOGLE_SOURCE, service="Google Workspace", native_id=native,
        url=f"{GOOGLE_PAGE}/incidents/{native}", began=incident.get("begin"), ended=incident.get("end"),
        impact=GOOGLE_IMPACT.get(incident.get("status_impact")), status=_text(newest.get("status")).lower().replace("_", " "),
        title=_text(incident.get("service_name")) or "incident",
        names=_names("Google", "Google Workspace", products), update=summary[:UPDATE_CHARS],
        fetched_at=fetched_at,
    )


def _google_records(data: object, fetched_at: datetime) -> list:
    if not isinstance(data, list):
        raise ParseError(f"{GOOGLE_SOURCE}: not a list of incidents")
    return [partial(_google_build, i, fetched_at) for i in data if isinstance(i, dict)]


GITHUB = statuspage("github-status", "GitHub", "https://www.githubstatus.com", vendor="GitHub",
                    panel_id="github-status")
CLOUDFLARE = statuspage("cloudflare-status", "Cloudflare", "https://www.cloudflarestatus.com",
                        vendor="Cloudflare", panel_id="cloudflare-status")
CLAUDE = statuspage("claude-status", "Claude", "https://status.claude.com", vendor="Anthropic",
                    product="Claude", panel_id="claude-status")
GOOGLE = Collector(
    source=GOOGLE_SOURCE, channel="status", url=f"{GOOGLE_PAGE}/incidents.json", interval_s=INTERVAL_S,
    licence=LICENCE.format("Google Workspace"), parse_records=_google_records,
    panel=Panel(id="google-workspace-status", en="Google Workspace status", es="Estado de Google Workspace",
                window=timedelta(days=30), limit=12),
)
COLLECTORS = [GITHUB, CLOUDFLARE, CLAUDE, GOOGLE]
SOURCES = tuple(c.source for c in COLLECTORS)
