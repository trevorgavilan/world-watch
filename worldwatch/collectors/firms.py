"""NASA FIRMS — active fire / heat detections from VIIRS on NOAA-20, the last 24 hours, two region files.

Files: https://firms.modaps.eosdis.nasa.gov/data/active_fire/noaa-20-viirs-c2/csv/J1_VIIRS_C2_<Region>_24h.csv
— no key (the MAP_KEY is only for the area API). FIRMS's FAQ: the 24 h / 48 h / 7 day CSV files are
updated every 60 minutes; near-real-time data arrives within ~3 hours of the pass. Only nominal or
high confidence is kept. Times are UTC (acq_date + acq_time HHMM).
- Mexico: the Central America file (Mexico to Panama and the Caribbean), only the Mexico box.
- Middle East: the Russia_Asia file (26–143° E, 9–71° N), only the Middle East box. A detection there
  is heat — a fire, a gas flare, an industrial site or a strike; FIRMS doesn't say which, and the
  near-real-time CSV has no type column. It is never presented as a strike.
Credit (FIRMS FAQ): "NASA FIRMS"; NASA shares its data fully and openly.
"""

from __future__ import annotations

import csv
import io
from datetime import datetime, timedelta, timezone
from functools import partial
from typing import Callable

from ..item import make_item
from ..views import Layer
from . import Collector, ParseError, usgs

SOURCE = "nasa-firms"
MIDEAST_SOURCE = "nasa-firms-mideast"
BASE = "https://firms.modaps.eosdis.nasa.gov/data/active_fire/noaa-20-viirs-c2/csv/"
URL = BASE + "J1_VIIRS_C2_Central_America_24h.csv"
MIDEAST_URL = BASE + "J1_VIIRS_C2_Russia_Asia_24h.csv"
LICENCE = "NASA FIRMS (LANCE / ESDIS) — open data"
COLUMNS = {"latitude", "longitude", "acq_date", "acq_time", "satellite", "confidence", "frp"}
KEPT_CONFIDENCE = {"nominal", "high", "n", "h"}
MAX_ROWS = 200_000
FRP_FULL = 100.0  # fire radiative power (MW) shown at full size
HEAT_NOTE = ("A satellite heat detection: a fire, a gas flare, an industrial site or a strike — "
             "FIRMS does not say which.")


def in_mideast(lat: float, lon: float) -> bool:
    """Egypt and Türkiye to Iran, down to Yemen and Oman. South of 22° N only east of 42.5° E
    (Yemen, southern Arabia, Oman), so Sudan's and Eritrea's fires stay out."""
    if 22.0 <= lat <= 42.0:
        return 25.0 <= lon <= 63.5
    if 12.0 <= lat < 22.0:
        return 42.5 <= lon <= 60.0
    return False


def decode_csv(payload: bytes, source: str) -> list[dict]:
    try:
        text = payload.decode("utf-8")
    except UnicodeDecodeError as err:
        raise ParseError(f"{source}: not UTF-8") from err
    reader = csv.DictReader(io.StringIO(text))
    if not reader.fieldnames or not COLUMNS <= set(reader.fieldnames):
        raise ParseError(f"{source}: not the FIRMS CSV ({(text[:80])!r})")
    rows = []
    try:
        for row in reader:
            rows.append(row)
            if len(rows) > MAX_ROWS:
                raise ParseError(f"{source}: more than {MAX_ROWS} rows")
    except csv.Error as err:  # a field over the csv module's limit, a stray NUL…
        raise ParseError(f"{source}: unreadable CSV ({err})") from err
    return rows


def _build(row: dict, fetched_at: datetime, *, source: str = SOURCE, word: str = "Fire", note: str = ""):
    lat, lon = float(row["latitude"]), float(row["longitude"])
    hhmm = row["acq_time"].strip().zfill(4)
    happened = datetime.strptime(f"{row['acq_date']} {hhmm}", "%Y-%m-%d %H%M").replace(tzinfo=timezone.utc)
    frp = float(row["frp"])
    return make_item(
        channel="hazards",
        source=source,
        native_id=f"{row['satellite']}/{row['acq_date']}/{hhmm}/{lat:.5f},{lon:.5f}",
        happened_at=happened,
        fetched_at=fetched_at,
        title=f"{word} detected (VIIRS {row['satellite']}), {frp:g} MW",
        url=None,
        summary=(note + " " if note else "") + f"Fire radiative power {frp:g} MW; confidence {row['confidence']}; "
                f"{'night' if row.get('daynight') == 'N' else 'day'} pass.",
        lat=lat,
        lon=lon,
        severity=f"FRP {frp:g} MW",
        licence=LICENCE,
        raw=row,
        lang="en",
    )


def _records(rows: object, fetched_at: datetime, *, keep: Callable[[float, float], bool], build) -> list:
    if not isinstance(rows, list):
        raise ParseError("nasa-firms: not the FIRMS CSV")
    builders = []
    for row in rows:
        try:
            if str(row["confidence"]).strip().lower() not in KEPT_CONFIDENCE:
                continue
            if not keep(float(row["latitude"]), float(row["longitude"])):
                continue
        except (KeyError, TypeError, ValueError):
            continue  # malformed row: skipped, the rest still count
        builders.append(partial(build, row, fetched_at))
    return builders


parse_records = partial(_records, keep=usgs.near_mexico, build=_build)
parse_mideast = partial(_records, keep=in_mideast,
                        build=partial(_build, source=MIDEAST_SOURCE, word="Heat", note=HEAT_NOTE))


def weight(row) -> float:
    try:
        frp = float((row["severity"] or "").split()[1])
    except (IndexError, ValueError):
        return 0.1
    return min(max(frp / FRP_FULL, 0.05), 1.0)


COLLECTOR = Collector(
    source=SOURCE,
    channel="hazards",
    url=URL,
    interval_s=60 * 60,
    licence=LICENCE,
    parse_records=parse_records,
    decode=decode_csv,
    layer=Layer(id="fires", en="Fires around Mexico (NASA FIRMS)", es="Incendios en y cerca de México (NASA FIRMS)",
                window=timedelta(hours=48), limit=3000, weight=weight),
)

MIDEAST_COLLECTOR = Collector(
    source=MIDEAST_SOURCE,
    channel="hazards",
    url=MIDEAST_URL,
    interval_s=60 * 60,
    licence=LICENCE,
    parse_records=parse_mideast,
    decode=decode_csv,
    layer=Layer(id="heat-mideast", en="Heat, Middle East — not strikes (NASA FIRMS)",
                es="Calor, Medio Oriente — no son ataques (NASA FIRMS)",
                window=timedelta(hours=48), limit=4000, weight=weight),
)
