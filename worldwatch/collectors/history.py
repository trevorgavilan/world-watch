"""A year of daily history behind the prices fetched hourly (Task 5, the terminal's charts): the New York
listings, gold and Trevor's tickers, and the crypto pairs, all from Twelve Data, once a day.

GET https://api.twelvedata.com/time_series?symbol=A,B&interval=1day&outputsize=365, the key in the header,
one credit per symbol → {symbol: {"meta", "values": [{"datetime": "2026-11-11", "open", "high", "low",
"close", "volume"}], "status": "ok"}} (one symbol answers the inner object). Today's bar is still moving;
it is updated in place the next day. Checked 2026-11-11.

Crypto's hourly price is CoinGecko's, but CoinGecko's keyless history (`/coins/<id>/market_chart`)
answered 429 to every call after the first on 2026-11-11, so crypto's past comes from Twelve Data too:
BTC/USD, ETH/USD and SOL/USD are Binance's close, the peso pairs Twelve Data's own "Synthetic" rate.
The chart names both (markets.view.HISTORY_NOTE). Items carry the same instrument id as the hourly
prices, under this collector's source, dated by the day (00:00 UTC).
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

SOURCE = "twelvedata-history"
BASE = "https://api.twelvedata.com/time_series"
CRYPTO = {"bitcoin": "BTC", "ethereum": "ETH", "solana": "SOL"}  # CoinGecko's coin id -> Twelve Data's symbol


def instruments(path: Path) -> list[tuple[str, object]]:
    """(Twelve Data symbol, instrument) for everything with a daily history here."""
    pairs = [(i.key, i) for i in twelvedata.instruments(path)]
    for inst in by_source(coingecko.SOURCE):
        coin, currency = inst.key.split("/")
        if coin in CRYPTO:
            pairs.append((f"{CRYPTO[coin]}/{currency.upper()}", inst))
    return pairs


def _urls(path: Path, last_ok: datetime | None, now: datetime) -> list[str]:
    symbols = [symbol for symbol, _ in instruments(path)]
    return [f"{BASE}?" + urlencode({"symbol": ",".join(symbols[n:n + twelvedata.BATCH]), "interval": "1day",
                                    "outputsize": "365"}, safe=",/")
            for n in range(0, len(symbols), twelvedata.BATCH)]


def _bar(inst, symbol: str, bar: dict, fetched_at: datetime):
    day = datetime.strptime(str(bar["datetime"])[:10], "%Y-%m-%d").replace(tzinfo=timezone.utc)
    return observation(inst, value=bar.get("close"), at=day, fetched_at=fetched_at, licence=twelvedata.LICENCE,
                       stamp=f"{day:%Y-%m-%d}", source=SOURCE,
                       record={"symbol": symbol, **{k: bar.get(k) for k in ("datetime", "open", "high", "low", "close",
                                                                             "volume")}})


def parse_records(path: Path, data: object, fetched_at: datetime, url: str | None = None) -> list:
    if not isinstance(data, dict):
        raise ParseError(f"{SOURCE}: not an object")
    if data.get("code") == 429:
        raise RateLimited(f"{SOURCE}: out of credits for now", 60.0)
    if data.get("code") == 401:
        raise ParseError(f"{SOURCE}: the key was refused")
    asked = (parse_qs(urlsplit(url or "").query).get("symbol") or [""])[0].split(",")
    answers = {asked[0]: data} if len(asked) == 1 else data
    by_symbol = dict(instruments(path))
    builds = []
    for symbol in asked:
        series, inst = answers.get(symbol), by_symbol.get(symbol)
        if not isinstance(series, dict) or inst is None:
            continue
        if series.get("status") != "ok" or not isinstance(series.get("values"), list):
            log.info("%s: no history for %s (%s)", SOURCE, symbol, str(series.get("message", ""))[:120])
            continue
        builds += [partial(_bar, inst, symbol, bar, fetched_at) for bar in series["values"] if isinstance(bar, dict)]
    return builds


def collector(path: Path) -> Collector:
    return Collector(
        source=SOURCE,
        channel="markets",
        url=BASE,
        interval_s=24 * 60 * 60,
        licence=twelvedata.LICENCE,
        parse_records=partial(parse_records, path),
        url_for=partial(_urls, path),
        headers=twelvedata._headers,
        parse_with_url=True,
    )
