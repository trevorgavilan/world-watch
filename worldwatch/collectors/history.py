"""A year of daily history for the prices fetched hourly (Task 5, the terminal's charts): crypto from
CoinGecko, the New York listings and gold from Twelve Data. Once a day each; the items are dated by
the day (00:00 UTC) and carry the same instrument id as the hourly prices, under their own source.

CoinGecko (keyless): /api/v3/coins/<coin>/market_chart?vs_currency=<usd|mxn>&days=365&interval=daily
→ {"prices": [[unix ms, price], …]}: one point per day at 00:00 UTC, plus a last one for "now" (skipped:
the hourly collector has it). Six requests a day, 3 s apart.
Twelve Data: /time_series?symbol=A,B&interval=1day&outputsize=365, the key in the header; one credit
per symbol → {symbol: {"meta", "values": [{"datetime": "2026-11-11", "open", "high", "low", "close",
"volume"}], "status": "ok"}} (one symbol answers the inner object). Today's bar is still moving; it is
updated in place the next day. Checked 2026-11-11.
"""

from __future__ import annotations

import logging
from datetime import datetime, timezone
from functools import partial
from pathlib import Path
from urllib.parse import parse_qs, urlencode, urlsplit

from ..http import RateLimited
from ..markets import observation
from ..markets.catalog import by_source
from . import Collector, ParseError, coingecko, twelvedata

log = logging.getLogger(__name__)

CG_SOURCE = "coingecko-history"
CG_BASE = "https://api.coingecko.com/api/v3/coins/"
TD_SOURCE = "twelvedata-history"
TD_BASE = "https://api.twelvedata.com/time_series"
DAY_MS = 86_400_000


def _cg_urls(last_ok: datetime | None, now: datetime) -> list[str]:
    return [f"{CG_BASE}{i.key.split('/')[0]}/market_chart?" + urlencode(
        {"vs_currency": i.key.split("/")[1], "days": "365", "interval": "daily"}) for i in by_source(coingecko.SOURCE)]


def _cg_inst(url: str):
    parts = urlsplit(url)
    coin = parts.path.rstrip("/").split("/")[-2]
    currency = (parse_qs(parts.query).get("vs_currency") or [""])[0]
    return next((i for i in by_source(coingecko.SOURCE) if i.key == f"{coin}/{currency}"), None)


def _cg_point(inst, point, fetched_at: datetime):
    stamp, price = point
    if isinstance(stamp, bool) or not isinstance(stamp, int) or stamp % DAY_MS:
        raise ValueError("not a day's point")  # the last point is "now", not a day
    day = datetime.fromtimestamp(stamp / 1000, tz=timezone.utc)
    return observation(inst, value=price, at=day, fetched_at=fetched_at, licence=coingecko.LICENCE,
                       stamp=f"{day:%Y-%m-%d}", record={"day_ms": stamp, "price": price}, source=CG_SOURCE)


def parse_cg(data: object, fetched_at: datetime, url: str | None = None) -> list:
    inst = _cg_inst(url or "")
    if inst is None:
        raise ParseError(f"{CG_SOURCE}: an answer for a coin we didn't ask for")
    if not isinstance(data, dict) or not isinstance(data.get("prices"), list):
        raise ParseError(f"{CG_SOURCE}: no prices for {inst.key}")
    return [partial(_cg_point, inst, p, fetched_at) for p in data["prices"] if isinstance(p, list) and len(p) == 2]


COINGECKO = Collector(
    source=CG_SOURCE,
    channel="markets",
    url=CG_BASE,
    interval_s=24 * 60 * 60,
    licence=coingecko.LICENCE,
    parse_records=parse_cg,
    url_for=_cg_urls,
    parse_with_url=True,
    follow_optional=True,
    each_optional=True,
)


def _td_urls(path: Path, last_ok: datetime | None, now: datetime) -> list[str]:
    symbols = [i.key for i in twelvedata.instruments(path)]
    return [f"{TD_BASE}?" + urlencode({"symbol": ",".join(symbols[n:n + twelvedata.BATCH]), "interval": "1day",
                                       "outputsize": "365"}, safe=",/")
            for n in range(0, len(symbols), twelvedata.BATCH)]


def _td_bar(inst, bar: dict, fetched_at: datetime):
    day = datetime.strptime(str(bar["datetime"])[:10], "%Y-%m-%d").replace(tzinfo=timezone.utc)
    return observation(inst, value=bar.get("close"), at=day, fetched_at=fetched_at, licence=twelvedata.LICENCE,
                       stamp=f"{day:%Y-%m-%d}", source=TD_SOURCE,
                       record={k: bar.get(k) for k in ("datetime", "open", "high", "low", "close", "volume")})


def parse_td(path: Path, data: object, fetched_at: datetime, url: str | None = None) -> list:
    if not isinstance(data, dict):
        raise ParseError(f"{TD_SOURCE}: not an object")
    if data.get("code") == 429:
        raise RateLimited(f"{TD_SOURCE}: out of credits for now", 60.0)
    asked = (parse_qs(urlsplit(url or "").query).get("symbol") or [""])[0].split(",")
    answers = {asked[0]: data} if len(asked) == 1 else data
    by_key = {i.key: i for i in twelvedata.instruments(path)}
    builds = []
    for symbol in asked:
        series, inst = answers.get(symbol), by_key.get(symbol)
        if not isinstance(series, dict) or inst is None:
            continue
        if series.get("status") != "ok" or not isinstance(series.get("values"), list):
            log.info("%s: no history for %s (%s)", TD_SOURCE, symbol, str(series.get("message", ""))[:120])
            continue
        builds += [partial(_td_bar, inst, bar, fetched_at) for bar in series["values"] if isinstance(bar, dict)]
    return builds


def twelvedata_history(path: Path) -> Collector:
    return Collector(
        source=TD_SOURCE,
        channel="markets",
        url=TD_BASE,
        interval_s=24 * 60 * 60,
        licence=twelvedata.LICENCE,
        parse_records=partial(parse_td, path),
        url_for=partial(_td_urls, path),
        headers=twelvedata._headers,
        parse_with_url=True,
    )
