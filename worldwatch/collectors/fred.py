"""FRED (Federal Reserve Bank of St. Louis) API — US indices, rates, oil and gas, the dollar (Task 5).

GET https://api.stlouisfed.org/fred/series/observations?series_id=<id>&api_key=<key>&file_type=json
&observation_start=<yyyy-mm-dd>; JSON {"observations": [{"date": "2026-11-06", "value": "4.86"}, …]};
a day with no number has the value "." (skipped). One request per series, a second apart.
Terms (fred.stlouisfed.org/docs/api/terms_of_use.html): show "This product uses the FRED® API but is
not endorsed or certified by the Federal Reserve Bank of St. Louis."; keep each series' copyright
notice; series marked copyright (S&P, Dow Jones, Nasdaq, Cboe) are for personal use only — this is a
private viewer. FRED's website itself must not be scraped (fred.stlouisfed.org/legal): API only.
The key: WW_FRED_KEY. FRED takes it only in the URL (Trevor's OK, 2026-11-10, D-25): the URL is never
logged or stored, and any text that leaves the process has the key masked (keys.redact).
"""

from __future__ import annotations

from datetime import datetime, timedelta, timezone
from functools import partial
from urllib.parse import parse_qs, urlencode, urlsplit

from ..keys import MissingKey, get_key
from ..item import make_item
from ..markets import observation
from ..markets.catalog import by_source
from . import Collector, ParseError

SOURCE = "fred"
BASE = "https://api.stlouisfed.org/fred/series/observations"
KEY_NAME = "WW_FRED_KEY"
LICENCE = ("This product uses the FRED® API but is not endorsed or certified by the Federal Reserve Bank of "
           "St. Louis. Series © their owners (S&P Dow Jones Indices, Nasdaq, Cboe); personal use")
INSTRUMENTS = by_source(SOURCE)
FIRST_REACH = timedelta(days=400)
OVERLAP = timedelta(days=14)


def _url_for(last_ok: datetime | None, now: datetime) -> list[str]:
    key = get_key(KEY_NAME)
    if key is None:
        raise MissingKey(f"needs {KEY_NAME} (a Windows user environment variable Trevor creates)")
    start = (now - FIRST_REACH) if last_ok is None else min(last_ok - OVERLAP, now - OVERLAP)
    return [f"{BASE}?" + urlencode({"series_id": i.key, "api_key": key, "file_type": "json",
                                    "observation_start": f"{start:%Y-%m-%d}"}) for i in INSTRUMENTS]


def _build(inst, point: dict, fetched_at: datetime):
    day = datetime.strptime(str(point["date"]), "%Y-%m-%d").replace(tzinfo=timezone.utc)
    return observation(inst, value=point["value"], at=day, fetched_at=fetched_at, licence=LICENCE,
                       stamp=f"{day:%Y-%m-%d}", record={"series_id": inst.key, "date": point["date"],
                                                         "value": point["value"]})


def series_of(url: str) -> str | None:
    return (parse_qs(urlsplit(url).query).get("series_id") or [None])[0]


def parse_records(data: object, fetched_at: datetime, url: str | None = None) -> list:
    """FRED's answer doesn't name its series: the URL that asked for it does."""
    inst = next((i for i in INSTRUMENTS if i.key == series_of(url or "")), None)
    if inst is None:
        raise ParseError(f"{SOURCE}: an answer for a series we didn't ask for")
    if not isinstance(data, dict) or not isinstance(data.get("observations"), list):
        raise ParseError(f"{SOURCE}: no observations for {inst.key}")
    return [partial(_build, inst, p, fetched_at) for p in data["observations"] if isinstance(p, dict)]


COLLECTOR = Collector(
    source=SOURCE,
    channel="markets",
    url=BASE,
    interval_s=6 * 60 * 60,
    licence=LICENCE,
    parse_records=parse_records,
    url_for=_url_for,
    parse_with_url=True,
)


# The economic calendar's US data releases: FRED's release ids, checked against fred/releases with the key.
RELEASES = {
    10: ("Consumer prices (CPI)", "Precios al consumidor (CPI)"),
    50: ("Jobs report (Employment Situation)", "Informe de empleo (Employment Situation)"),
    53: ("Gross domestic product (GDP)", "Producto interno bruto (PIB)"),
    54: ("Personal income and spending (PCE prices)", "Ingreso y gasto personal (precios PCE)"),
    9: ("Retail sales", "Ventas minoristas"),
}
CALENDAR_SOURCE = "fred-calendar"
CALENDAR_BASE = "https://api.stlouisfed.org/fred/release/dates"  # one release per request: the all-releases
# list held 1,405 dates for 60 days (2026-11-11), past its 1,000 limit
CALENDAR_AHEAD = timedelta(days=60)


def _calendar_url(last_ok: datetime | None, now: datetime) -> list[str]:
    key = get_key(KEY_NAME)
    if key is None:
        raise MissingKey(f"needs {KEY_NAME} (a Windows user environment variable Trevor creates)")
    return [f"{CALENDAR_BASE}?" + urlencode({
        "release_id": str(rid), "api_key": key, "file_type": "json", "realtime_start": f"{now:%Y-%m-%d}",
        "realtime_end": f"{now + CALENDAR_AHEAD:%Y-%m-%d}", "include_release_dates_with_no_data": "true",
        "sort_order": "asc"}) for rid in RELEASES]


def _release(entry: dict, fetched_at: datetime):
    en, es = RELEASES[entry["release_id"]]
    day = datetime.strptime(str(entry["date"]), "%Y-%m-%d").replace(tzinfo=timezone.utc)
    return make_item(channel="markets", source=CALENDAR_SOURCE, native_id=f"{entry['release_id']}/{entry['date']}",
                     happened_at=day, fetched_at=fetched_at, title=en,
                     url=f"https://fred.stlouisfed.org/releases/{entry['release_id']}",
                     summary=f"Scheduled release, as FRED lists it (release {entry['release_id']})", licence=LICENCE,
                     raw={"es": es, **{k: entry.get(k) for k in ("release_id", "release_name", "date")}}, lang="en")


def parse_calendar(data: object, fetched_at: datetime) -> list:
    if not isinstance(data, dict) or not isinstance(data.get("release_dates"), list):
        raise ParseError(f"{CALENDAR_SOURCE}: no release_dates")
    return [partial(_release, e, fetched_at) for e in data["release_dates"]
            if isinstance(e, dict) and e.get("release_id") in RELEASES]


CALENDAR = Collector(
    source=CALENDAR_SOURCE,
    channel="markets",
    url=CALENDAR_BASE,
    interval_s=24 * 60 * 60,
    licence=LICENCE,
    parse_records=parse_calendar,
    url_for=_calendar_url,
)
