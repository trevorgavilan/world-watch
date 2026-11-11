"""Twelve Data — Mexican companies listed in New York, gold and silver, and Trevor's watchlist (Task 5).

GET https://api.twelvedata.com/quote?symbol=A,B,C with the key in the header `Authorization: apikey
<key>` (their recommended way; never in the URL). A batch answers {symbol: quote}; one symbol answers
the quote itself; a symbol the plan doesn't cover answers {"code": 4xx, "status": "error"} in its
place. Quote: symbol, name, exchange, datetime, timestamp (the day's bar, unix s), last_quote_at (the price's
moment), close (the latest price; the day's close once is_market_open is false),
previous_close, percent_change, is_market_open. Checked 2026-11-11: XAU/USD is on the free plan, XAG/USD
answers 403 "not available with your plan".
Free (Basic) plan: 8 credits a minute, 800 a day, one credit per symbol; personal, non-commercial use
(twelvedata.com/terms §2.3). So: batches of 8 symbols at least 62 s apart (http.HOST_MIN_GAP_S), once
an hour, at most 30 symbols (720 a day). The key: WW_TWELVEDATA_KEY.
"""

from __future__ import annotations

import logging
from datetime import datetime, timezone
from functools import partial
from pathlib import Path
from urllib.parse import parse_qs, urlencode, urlsplit

from ..http import RateLimited
from ..keys import MissingKey, get_key
from ..markets import observation
from ..markets import rules as market_rules
from ..markets.catalog import by_source, watch_instrument
from . import Collector, ParseError

log = logging.getLogger(__name__)

SOURCE = "twelvedata"
BASE = "https://api.twelvedata.com/quote"
KEY_NAME = "WW_TWELVEDATA_KEY"
LICENCE = "Market data by Twelve Data (twelvedata.com) — free plan, personal non-commercial use, delayed"
BATCH = 8
MAX_SYMBOLS = 30


def instruments(path: Path) -> list:
    fixed = by_source(SOURCE)
    known = {i.key for i in fixed}
    watch = [watch_instrument(s) for s in market_rules.load(path).watch if s not in known]
    return (fixed + watch)[:MAX_SYMBOLS]


def _headers() -> dict[str, str]:
    key = get_key(KEY_NAME)
    if key is None:
        raise MissingKey(f"needs {KEY_NAME} (a Windows user environment variable Trevor creates)")
    return {"Authorization": f"apikey {key}"}


def _url_for(path: Path, last_ok: datetime | None, now: datetime) -> list[str]:
    symbols = [i.key for i in instruments(path)]
    return [f"{BASE}?" + urlencode({"symbol": ",".join(symbols[n:n + BATCH])}, safe=",/")
            for n in range(0, len(symbols), BATCH)]


def _build(inst, quote: dict, fetched_at: datetime):
    # last_quote_at: the moment of the price; timestamp is only the start of the day's bar (the open)
    stamp = quote.get("last_quote_at", quote.get("timestamp"))
    if isinstance(stamp, bool) or not isinstance(stamp, int):
        raise ValueError("no time")
    at = datetime.fromtimestamp(stamp, tz=timezone.utc)
    kept = ("symbol", "name", "exchange", "currency", "datetime", "timestamp", "last_quote_at", "close", "previous_close",
            "change", "percent_change", "is_market_open")
    return observation(inst, value=quote.get("close"), at=at, fetched_at=fetched_at, licence=LICENCE,
                       stamp=at.strftime("%Y-%m-%dT%H"), change_pct=quote.get("percent_change"),
                       record={k: quote.get(k) for k in kept})


def _error(answer: dict) -> str | None:
    if answer.get("status") == "error":
        return f"{answer.get('code')}: {str(answer.get('message', ''))[:160]}"
    return None


def parse_records(path: Path, data: object, fetched_at: datetime, url: str | None = None) -> list:
    if not isinstance(data, dict):
        raise ParseError(f"{SOURCE}: not an object")
    asked = (parse_qs(urlsplit(url or "").query).get("symbol") or [""])[0].split(",")
    if data.get("code") == 429:
        raise RateLimited(f"{SOURCE}: out of credits for now", 60.0)
    if (whole := _error(data)) is not None:
        raise ParseError(f"{SOURCE}: {whole}")
    answers = {asked[0]: data} if len(asked) == 1 else data
    by_key = {i.key: i for i in instruments(path)}
    builds = []
    for symbol in asked:
        quote, inst = answers.get(symbol), by_key.get(symbol)
        if not isinstance(quote, dict) or inst is None:
            continue
        if (problem := _error(quote)) is not None:
            log.info("%s: %s not quoted (%s)", SOURCE, symbol, problem)  # a symbol outside the free plan
            continue
        builds.append(partial(_build, inst, quote, fetched_at))
    return builds


def collector(path: Path) -> Collector:
    return Collector(
        source=SOURCE,
        channel="markets",
        url=BASE,
        interval_s=60 * 60,
        licence=LICENCE,
        parse_records=partial(parse_records, path),
        url_for=partial(_url_for, path),
        headers=_headers,
        parse_with_url=True,
    )
