"""CoinGecko — crypto prices in US dollars and pesos (Task 5).

JSON: /api/v3/simple/price (docs.coingecko.com), keyless public use: {coin: {usd, usd_24h_change, mxn,
mxn_24h_change, last_updated_at (unix s)}}. One call every 15 minutes is ~2,900 a month, well inside
the free plan. Terms (coingecko.com/en/api_terms §4.4): show "Powered by CoinGecko"; §6.1.1: they
discourage storing data and ask that a cache be refreshed at least every 24 hours — we keep one
number per coin per hour, refreshed every 15 minutes, for the page's small chart.
"""

from __future__ import annotations

from datetime import datetime, timezone
from functools import partial

from ..markets import observation
from ..markets.catalog import by_source
from . import Collector, ParseError

SOURCE = "coingecko"
LICENCE = "Powered by CoinGecko (coingecko.com) — free public API, attribution required"
INSTRUMENTS = by_source(SOURCE)
COINS = sorted({i.key.split("/")[0] for i in INSTRUMENTS})
CURRENCIES = sorted({i.key.split("/")[1] for i in INSTRUMENTS})
URL = ("https://api.coingecko.com/api/v3/simple/price?ids=" + ",".join(COINS) + "&vs_currencies="
       + ",".join(CURRENCIES) + "&include_24hr_change=true&include_last_updated_at=true&precision=full")


def _build(inst, record: dict, fetched_at: datetime):
    coin, currency = inst.key.split("/")
    stamp = record["last_updated_at"]
    if isinstance(stamp, bool) or not isinstance(stamp, int):
        raise ValueError("no update time")
    at = datetime.fromtimestamp(stamp, tz=timezone.utc)
    return observation(inst, value=record[currency], at=at, fetched_at=fetched_at, licence=LICENCE,
                       stamp=at.strftime("%Y-%m-%dT%H"), change_pct=record.get(f"{currency}_24h_change"),
                       record={k: record.get(k) for k in (currency, f"{currency}_24h_change", "last_updated_at")})


def parse_records(data: object, fetched_at: datetime) -> list:
    if not isinstance(data, dict):
        raise ParseError(f"{SOURCE}: not an object of coins")
    builds = []
    for inst in INSTRUMENTS:
        record = data.get(inst.key.split("/")[0])
        if isinstance(record, dict):
            builds.append(partial(_build, inst, record, fetched_at))
    if not builds:
        raise ParseError(f"{SOURCE}: none of our coins in the answer")
    return builds


COLLECTOR = Collector(
    source=SOURCE,
    channel="markets",
    url=URL,
    interval_s=15 * 60,
    licence=LICENCE,
    parse_records=parse_records,
)
