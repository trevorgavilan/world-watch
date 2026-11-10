"""Markets (Task 5): information and education only, never advice (VISION rule 7).

Every number is a stored Item of channel "markets": one per instrument per day (daily series) or per
hour (prices fetched more often, updated in place through the hour). Its raw record carries the
instrument's id, the value as the source wrote it, and the change the source reported, if any.
"""

from __future__ import annotations

from datetime import datetime
from decimal import Decimal, InvalidOperation

from ..item import make_item
from .catalog import Instrument

CHANNEL = "markets"
DISCLAIMER_EN = "Information only, not investment advice. Check the source before acting on any number."
DISCLAIMER_ES = "Solo información, no es asesoría de inversión. Revisa la fuente antes de usar cualquier cifra."


def number(text: object) -> Decimal:
    """A finite number from a source's text, or ValueError: "N/E", "", "." and NaN never become a value."""
    if isinstance(text, bool) or text is None:
        raise ValueError("no number")
    try:
        value = Decimal(str(text).strip().replace(",", ""))
    except InvalidOperation as err:
        raise ValueError(f"not a number: {text!r}") from err
    if not value.is_finite():
        raise ValueError("not finite")
    return value


def observation(inst: Instrument, *, value: object, at: datetime, fetched_at: datetime, licence: str,
                stamp: str, record: object, change_pct: object = None):
    """An Item for one observation. `stamp` names it (the day, or the hour), so a re-fetch updates it."""
    figure = number(value)
    raw = {"instrument": inst.id, "value": str(figure), "record": record}
    if change_pct is not None:
        raw["change_pct"] = str(number(change_pct))
    return make_item(
        channel=CHANNEL,
        source=inst.source,
        native_id=f"{inst.id}/{stamp}",
        happened_at=at,
        fetched_at=fetched_at,
        title=f"{inst.en}: {figure:,.{inst.decimals}f} {inst.unit_en}".strip(),
        url=inst.page,
        summary=inst.delay_en,
        licence=licence,
        raw=raw,
        lang="en",
    )
