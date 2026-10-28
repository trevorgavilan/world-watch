"""How a source shows on the Board: a layer on the globe and/or a panel beside it (D-17).

A source registers them on its own Collector (`layer=`, `panel=`), so adding a source's layer or
panel touches no Board code. The Board lists every collector in the run and serves what each one
registered; a source with neither leaves no trace on the Board.
"""

from __future__ import annotations

from dataclasses import dataclass
from datetime import timedelta
from typing import Callable


def _no_weight(row) -> float:
    return 0.5


@dataclass(frozen=True)
class Layer:
    """Points on the globe: every stored item of the source with a position, newest first."""

    id: str  # in URLs: /api/layers/<id>; letters, digits and '-' only
    en: str
    es: str
    window: timedelta  # how far back the layer reaches
    limit: int
    weight: Callable[[object], float] = _no_weight  # store row -> 0..1: a point's size and colour


@dataclass(frozen=True)
class Panel:
    """A list of the source's newest items: title, summary, link, when it happened, when fetched."""

    id: str
    en: str
    es: str
    window: timedelta
    limit: int
    date_only: bool = False  # the source reports a day, not a moment (KEV's dateAdded)
