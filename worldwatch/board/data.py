"""What the Board's endpoints answer, read from the store. Generic: a source shows here only
through the Layer and Panel it registered on its Collector (views.py)."""

from __future__ import annotations

import re
from datetime import datetime, timedelta

from ..collectors import Collector
from ..item import clean_url, iso_utc
from ..recon import CREDITS, _status
from ..store import Store

ID = re.compile(r"[a-z0-9][a-z0-9-]{0,40}")
FUTURE_SLACK = timedelta(minutes=5)  # a clock a little ahead never hides the newest item


class Registry:
    """Every layer and panel in the run, checked once at start: ids unique and URL-safe."""

    def __init__(self, collectors: list[Collector]) -> None:
        self.collectors = list(collectors)
        self.layers: dict[str, Collector] = {}
        self.panels: dict[str, Collector] = {}
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
    credit = next(((text, url) for prefix, text, url in CREDITS if collector.source.startswith(prefix)), None)
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
