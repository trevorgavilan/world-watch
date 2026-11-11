"""Banco de México SIE API — the peso's FIX and Mexican interest rates (Task 5).

GET /SieAPIRest/service/v1/series/<ids>/datos/<yyyy-MM-dd>/<yyyy-MM-dd> (up to 20 ids, comma
separated), the token in the `Bmx-Token` header (the API also takes it in the URL; we never do).
JSON: {"bmx": {"series": [{"idSerie", "titulo", "datos": [{"fecha": "dd/mm/yyyy", "dato": "18.6226"}]}]}}.
Limits (doc/limiteConsultas): 200 queries in 5 minutes and 10,000 a day for historical data; we make
one query per collector per hour. The first run reaches back a year for the chart; later runs the
last two weeks, so a late revision or a missed day is picked up.
The key: WW_BANXICO_TOKEN, a Windows user environment variable Trevor creates (64 characters).
"""

from __future__ import annotations

from datetime import datetime, timedelta, timezone
from functools import partial

from ..keys import require_key
from ..markets import observation
from ..markets.catalog import by_source
from ..views import Panel
from . import Collector, ParseError

BASE = "https://www.banxico.org.mx/SieAPIRest/service/v1/series/"
KEY_NAME = "WW_BANXICO_TOKEN"
LICENCE = "Fuente: Banco de México, Sistema de Información Económica (SIE)"
FIRST_REACH = timedelta(days=400)
OVERLAP = timedelta(days=14)


def _headers() -> dict[str, str]:
    token = require_key(KEY_NAME)
    return {"Bmx-Token": token, "Accept": "application/json"}


def _url_for(ids: list[str], last_ok: datetime | None, now: datetime) -> list[str]:
    start = (now - FIRST_REACH) if last_ok is None else min(last_ok - OVERLAP, now - OVERLAP)
    return [f"{BASE}{','.join(ids)}/datos/{start:%Y-%m-%d}/{now:%Y-%m-%d}"]


def _build(inst, point: dict, fetched_at: datetime):
    day = datetime.strptime(str(point["fecha"]), "%d/%m/%Y").replace(tzinfo=timezone.utc)
    return observation(inst, value=point["dato"], at=day, fetched_at=fetched_at, licence=LICENCE,
                       stamp=f"{day:%Y-%m-%d}", record={"idSerie": inst.key, **point})


def parse_records(instruments, data: object, fetched_at: datetime) -> list:
    try:
        series = data["bmx"]["series"]
    except (TypeError, KeyError) as err:
        if isinstance(data, dict) and "error" in data:
            said = data["error"].get("mensaje", "error") if isinstance(data["error"], dict) else data["error"]
            raise ParseError(f"banxico: the API said {str(said)[:120]!r}") from err
        raise ParseError("banxico: no bmx.series in the answer") from err
    if not isinstance(series, list):
        raise ParseError("banxico: series is not a list")
    by_key = {i.key: i for i in instruments}
    builds = []
    for entry in series:
        inst = by_key.get(entry.get("idSerie")) if isinstance(entry, dict) else None
        if inst is None or not isinstance(entry.get("datos"), list):
            continue  # a series we didn't ask for, or one with no data in the range
        builds += [partial(_build, inst, p, fetched_at) for p in entry["datos"] if isinstance(p, dict)]
    return builds  # "N/E" (no data that day) fails in observation() and is skipped


def _collector(source: str, interval_s: int, panel=None) -> Collector:
    instruments = by_source(source)
    ids = [i.key for i in instruments]
    return Collector(
        source=source,
        channel="markets",
        url=f"{BASE}{','.join(ids)}/datos",
        interval_s=interval_s,
        licence=LICENCE,
        parse_records=partial(parse_records, instruments),
        url_for=partial(_url_for, ids),
        headers=_headers,
        panel=panel,
    )


PESO = _collector("banxico-peso", 60 * 60,
                  Panel(id="peso", en="The peso — US dollar in pesos (Banxico FIX)", es="El peso — dólar en pesos (FIX de Banxico)",
                        window=timedelta(days=14), limit=10, date_only=True))
RATES = _collector("banxico-rates", 3 * 60 * 60)
COLLECTORS = [PESO, RATES]
