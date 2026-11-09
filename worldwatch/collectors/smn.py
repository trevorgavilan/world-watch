"""SMN / CONAGUA — today's weather forecast for Mexico City's 16 alcaldías.

Web service (smn.conagua.gob.mx/es/web-service-api, "PronosticoPorMunicipiosGZ"):
https://smn.conagua.gob.mx/tools/GUI/webservices/?method=1 — a gzip of every municipality's forecast
for 4 days (~0.3 MB packed, ~5 MB unpacked), updated hourly. Only CDMX (ides 9) is kept.
Terms (smn.conagua.gob.mx/es/terminos-y-condiciones): public domain, open use with explicit credit;
never pose as an official channel; respect the update cycle — so it is read every 3 hours.
A forecast is for a day (dloc "YYYYMMDDT00", Mexico City time): an item per alcaldía and day.
"""

from __future__ import annotations

import gzip
import io
import json
import zlib
from datetime import datetime, timedelta, timezone
from functools import partial

from ..item import make_item
from ..views import Panel
from . import Collector, ParseError

SOURCE = "smn-cdmx"
URL = "https://smn.conagua.gob.mx/tools/GUI/webservices/?method=1"
LICENCE = "Servicio Meteorológico Nacional (SMN) / CONAGUA — dominio público, con crédito"
CDMX_STATE = "9"
MEXICO_TIME = timezone(timedelta(hours=-6), "CDMX")
MAX_UNPACKED = 64 * 1024 * 1024  # a gzip bomb stops here (the real file is ~5 MB)


def decode_gzip_json(payload: bytes, source: str) -> object:
    try:
        reader = gzip.GzipFile(fileobj=io.BytesIO(payload))
        text = reader.read(MAX_UNPACKED + 1)
    except (OSError, EOFError, zlib.error) as err:
        raise ParseError(f"{source}: not gzip ({err})") from err
    if len(text) > MAX_UNPACKED:
        raise ParseError(f"{source}: unpacks to more than {MAX_UNPACKED} bytes")
    try:
        return json.loads(text.decode("utf-8"))
    except (UnicodeDecodeError, json.JSONDecodeError) as err:
        raise ParseError(f"{source}: not JSON inside the gzip") from err


def _num(record: dict, key: str) -> float:
    return float(str(record[key]).strip())


def _build(record: dict, fetched_at: datetime):
    day = datetime.strptime(record["dloc"][:8], "%Y%m%d").replace(tzinfo=MEXICO_TIME)
    name = record["nmun"]
    tmin, tmax, rain_p, rain_mm = _num(record, "tmin"), _num(record, "tmax"), _num(record, "probprec"), _num(record, "prec")
    return make_item(
        channel="hazards",
        source=SOURCE,
        native_id=f"{record['ides']}-{record['idmun']}/{record['dloc'][:8]}",
        happened_at=day,
        fetched_at=fetched_at,
        title=f"{name}: {tmin:.0f}–{tmax:.0f} °C, {str(record.get('desciel') or '').strip()}",
        url="https://smn.conagua.gob.mx/es/pronosticos/pronostico-del-tiempo-por-municipios",
        summary=(f"Lluvia {rain_p:.0f}% ({rain_mm:g} mm). Viento del {record.get('dirvienc')} "
                 f"{_num(record, 'velvien'):.0f} km/h, rachas {_num(record, 'raf'):.0f} km/h. "
                 f"Nubosidad {_num(record, 'cc'):.0f}%."),
        lat=_num(record, "lat"),
        lon=_num(record, "lon"),
        severity=f"lluvia {rain_p:.0f}%",
        licence=LICENCE,
        raw=record,
        lang="es",
    )


def parse_records(data: object, fetched_at: datetime) -> list:
    if not isinstance(data, list):
        raise ParseError(f"{SOURCE}: not a list of forecasts")
    return [partial(_build, r, fetched_at) for r in data
            if isinstance(r, dict) and str(r.get("ides")).strip() == CDMX_STATE]


COLLECTOR = Collector(
    source=SOURCE,
    channel="hazards",
    url=URL,
    interval_s=3 * 60 * 60,
    licence=LICENCE,
    parse_records=parse_records,
    decode=decode_gzip_json,
    # A forecast is dated at its day's start in CDMX: 24 h back shows exactly today's.
    panel=Panel(id="cdmx-weather", en="CDMX weather today (SMN)", es="Clima en CDMX hoy (SMN)",
                window=timedelta(hours=24), limit=20, date_only=True),
)
