"""NASA FIRMS — active fire detections from VIIRS on NOAA-20, the last 24 hours, Central America file.

File: https://firms.modaps.eosdis.nasa.gov/data/active_fire/noaa-20-viirs-c2/csv/J1_VIIRS_C2_Central_America_24h.csv
— no key (the MAP_KEY is only for the area API). FIRMS's FAQ: the 24 h / 48 h / 7 day CSV files are
updated every 60 minutes; near-real-time data arrives within ~3 hours of the pass. The region runs
from Mexico to Panama and the Caribbean; only the Mexico box is kept, and only nominal or high
confidence. Times are UTC (acq_date + acq_time HHMM).
Credit (FIRMS FAQ): "NASA FIRMS"; NASA shares its data fully and openly.
"""

from __future__ import annotations

import csv
import io
from datetime import datetime, timedelta, timezone
from functools import partial

from ..item import make_item
from ..views import Layer
from . import Collector, ParseError, usgs

SOURCE = "nasa-firms"
URL = ("https://firms.modaps.eosdis.nasa.gov/data/active_fire/noaa-20-viirs-c2/csv/"
       "J1_VIIRS_C2_Central_America_24h.csv")
LICENCE = "NASA FIRMS (LANCE / ESDIS) — open data"
COLUMNS = {"latitude", "longitude", "acq_date", "acq_time", "satellite", "confidence", "frp"}
KEPT_CONFIDENCE = {"nominal", "high", "n", "h"}
MAX_ROWS = 200_000
FRP_FULL = 100.0  # fire radiative power (MW) shown at full size


def decode_csv(payload: bytes, source: str) -> list[dict]:
    try:
        text = payload.decode("utf-8")
    except UnicodeDecodeError as err:
        raise ParseError(f"{source}: not UTF-8") from err
    reader = csv.DictReader(io.StringIO(text))
    if not reader.fieldnames or not COLUMNS <= set(reader.fieldnames):
        raise ParseError(f"{source}: not the FIRMS CSV ({(text[:80])!r})")
    rows = []
    for row in reader:
        rows.append(row)
        if len(rows) > MAX_ROWS:
            raise ParseError(f"{source}: more than {MAX_ROWS} rows")
    return rows


def _build(row: dict, fetched_at: datetime):
    lat, lon = float(row["latitude"]), float(row["longitude"])
    hhmm = row["acq_time"].strip().zfill(4)
    happened = datetime.strptime(f"{row['acq_date']} {hhmm}", "%Y-%m-%d %H%M").replace(tzinfo=timezone.utc)
    frp = float(row["frp"])
    return make_item(
        channel="hazards",
        source=SOURCE,
        native_id=f"{row['satellite']}/{row['acq_date']}/{hhmm}/{lat:.5f},{lon:.5f}",
        happened_at=happened,
        fetched_at=fetched_at,
        title=f"Fire detected (VIIRS {row['satellite']}), {frp:g} MW",
        url=None,
        summary=f"Fire radiative power {frp:g} MW; confidence {row['confidence']}; "
                f"{'night' if row.get('daynight') == 'N' else 'day'} pass.",
        lat=lat,
        lon=lon,
        severity=f"FRP {frp:g} MW",
        licence=LICENCE,
        raw=row,
        lang="en",
    )


def parse_records(rows: object, fetched_at: datetime) -> list:
    if not isinstance(rows, list):
        raise ParseError(f"{SOURCE}: not the FIRMS CSV")
    builders = []
    for row in rows:
        try:
            if str(row["confidence"]).strip().lower() not in KEPT_CONFIDENCE:
                continue
            if not usgs.near_mexico(float(row["latitude"]), float(row["longitude"])):
                continue
        except (KeyError, TypeError, ValueError):
            continue  # malformed row: skipped, the rest still count
        builders.append(partial(_build, row, fetched_at))
    return builders


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
