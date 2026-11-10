"""What the Board's endpoints answer, read from the store. Generic: a source shows here only
through the Layer and Panel it registered on its Collector (views.py)."""

from __future__ import annotations

import json
import re
from datetime import datetime, timedelta

from ..collectors import Collector
from ..item import clean_url, iso_utc
from ..recon import CREDITS, _status
from ..store import Store

ID = re.compile(r"[a-z0-9][a-z0-9-]{0,40}")
FUTURE_SLACK = timedelta(minutes=5)  # a clock a little ahead never hides the newest item
ITEM_ID = re.compile(r"[A-Za-z0-9_-]{1,64}")  # an item's id in /api/items/<id>; nothing else reaches the query
RECORD_FIELDS = 80   # the source's own record, flattened: enough for any feed we read, never a flood
RECORD_DEPTH = 4
RECORD_KEY = 80
RECORD_TEXT = 300


class Registry:
    """Every layer and panel in the run, checked once at start: ids unique and URL-safe."""

    def __init__(self, collectors: list[Collector]) -> None:
        self.collectors = list(collectors)
        self.layers: dict[str, Collector] = {}
        self.panels: dict[str, Collector] = {}
        self.sources: dict[str, Collector] = {c.source: c for c in self.collectors}
        for c in self.collectors:
            for kind, view, table in (("layer", c.layer, self.layers), ("panel", c.panel, self.panels)):
                if view is None:
                    continue
                if not ID.fullmatch(view.id):
                    raise ValueError(f"{c.source}: {kind} id {view.id!r} must be lowercase letters, digits and '-'")
                if view.id in table:
                    raise ValueError(f"{c.source}: {kind} id {view.id!r} is already taken")
                table[view.id] = c

    def layer(self, layer_id: str) -> Collector | None:
        return self.layers.get(layer_id)

    def panel(self, panel_id: str) -> Collector | None:
        return self.panels.get(panel_id)

    def board(self, store: Store, now: datetime) -> dict:
        return {
            "now": iso_utc(now),
            "layers": [{"id": c.layer.id, "source": c.source, "en": c.layer.en, "es": c.layer.es}
                       for c in self.layers.values()],
            "panels": [{"id": c.panel.id, "source": c.source, "en": c.panel.en, "es": c.panel.es,
                        "date_only": c.panel.date_only} for c in self.panels.values()],
            "sources": [freshness(store, c, now) for c in self.collectors],
        }


def freshness(store: Store, collector: Collector, now: datetime) -> dict:
    status = _status(store, collector, now)
    state = store.source_state(collector.source)
    credit = _credit(collector.source)
    return {
        "source": collector.source,
        "last_ok_at": iso_utc(status.last_ok) if status.last_ok else None,
        "stale": status.stale,
        "last_error": status.error,
        "interval_s": collector.interval_s,
        "last_count": state["last_count"] if state else None,
        "credit": credit[0] if credit else None,
        "credit_url": clean_url(credit[1]) if credit else None,
    }


def _credit(source: str) -> tuple[str, str] | None:
    return next(((text, url) for prefix, text, url in CREDITS if source.startswith(prefix)), None)


def record_fields(raw: str) -> list[list[str]]:
    """The source's own record, as it arrived, flattened to [name, text] pairs for the pop-up card:
    nested names dotted ("properties." dropped: GeoJSON's wrapper), empty values left out, every
    name and value capped. It is data like any source text: the page sets it with textContent."""
    try:
        record = json.loads(raw)
    except (TypeError, ValueError):
        return []
    out: list[list[str]] = []

    def text(value) -> str:
        if isinstance(value, bool):
            return "true" if value else "false"
        if isinstance(value, list):
            return ", ".join(text(v) for v in value)
        return str(value)

    def walk(name: str, value, depth: int) -> None:
        if len(out) >= RECORD_FIELDS or value is None or value in ("", [], {}):
            return
        if isinstance(value, dict) and depth < RECORD_DEPTH:
            for key, inner in value.items():
                walk(f"{name}.{key}" if name else str(key), inner, depth + 1)
        elif isinstance(value, list) and depth < RECORD_DEPTH and any(isinstance(v, (dict, list)) for v in value):
            for i, inner in enumerate(value[:10]):
                walk(f"{name}[{i}]", inner, depth + 1)
        else:
            key = name.removeprefix("properties.") or "value"
            out.append([key[:RECORD_KEY], text(value)[:RECORD_TEXT]])

    walk("", record, 0)
    return out


def item_detail(store: Store, registry: Registry, item_id: str) -> dict | None:
    """Everything we hold about one item, for the pop-up card. Only a source in this run answers."""
    row = store.item(item_id)
    if row is None:
        return None
    collector = registry.sources.get(row["source"])
    if collector is None:
        return None
    view = collector.layer or collector.panel
    credit = _credit(row["source"])
    return {
        **_common(row),
        "summary": row["summary"],
        "lat": row["lat"],
        "lon": row["lon"],
        "country": row["country"],
        "licence": row["licence"],
        "basis": row["basis"],
        "lang": row["lang"],
        "kind": view.en if view else None,
        "credit": credit[0] if credit else None,
        "credit_url": clean_url(credit[1]) if credit else None,
        "record": record_fields(row["raw"]),
    }


def _rows(store: Store, source: str, now: datetime, window: timedelta, limit: int, *, positioned: bool = False):
    return store.items_between(source, iso_utc(now - window), iso_utc(now + FUTURE_SLACK), limit=limit,
                               positioned=positioned)


def _common(row) -> dict:
    """D-8: every item carries its source and both times. The link is re-checked: an old row or a bug
    upstream never puts a javascript: link on the page."""
    return {
        "id": row["id"],
        "source": row["source"],
        "title": row["title"],
        "url": clean_url(row["url"]),
        "happened_at": row["happened_at"],
        "fetched_at": row["fetched_at"],
        "severity": row["severity"],
    }


def layer_points(store: Store, collector: Collector, now: datetime) -> dict:
    layer = collector.layer
    points = [{**_common(row), "lat": row["lat"], "lon": row["lon"],
               "weight": min(max(float(layer.weight(row)), 0.0), 1.0)}
              for row in _rows(store, collector.source, now, layer.window, layer.limit, positioned=True)]
    return {"layer": layer.id, "points": points}


def panel_entries(store: Store, collector: Collector, now: datetime) -> dict:
    panel = collector.panel
    entries = [{**_common(row), "summary": row["summary"]}
               for row in _rows(store, collector.source, now, panel.window, panel.limit)]
    return {"panel": panel.id, "date_only": panel.date_only, "entries": entries}
