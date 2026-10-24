"""The runner: each cycle, fetch every source that is due, store what it sends,
and schedule its next turn. A failure backs off; it never stops the other sources.
"""

from __future__ import annotations

import logging
import time
from dataclasses import dataclass
from datetime import datetime, timedelta, timezone
from typing import Callable

from .collectors import Collector, ParseError
from .http import FetchError, RateLimited
from .item import iso_utc, parse_iso_utc
from .store import Store

log = logging.getLogger(__name__)

RETRY_BASE_S = 120          # network or server trouble: 2 min, 4, 8 … up to an hour
RETRY_MAX_S = 3600
RATE_LIMIT_BASE_S = 15 * 60  # told to slow down: 15 min, 30, 60 … up to 6 hours
RATE_LIMIT_MAX_S = 6 * 3600
ERROR_MAX = 500


@dataclass(frozen=True)
class RunResult:
    source: str
    ok: bool
    n_items: int
    error: str | None


def failure_delay_s(fail_count: int, *, rate_limited: bool, retry_after_s: float | None) -> float:
    exponent = min(max(fail_count - 1, 0), 20)
    if rate_limited:
        delay = min(RATE_LIMIT_BASE_S * 2 ** exponent, RATE_LIMIT_MAX_S)
        if retry_after_s:
            delay = max(delay, min(retry_after_s, RATE_LIMIT_MAX_S))
        return delay
    return min(RETRY_BASE_S * 2 ** exponent, RETRY_MAX_S)


def is_due(store: Store, collector: Collector, now: datetime) -> bool:
    state = store.source_state(collector.source)
    return state is None or parse_iso_utc(state["next_due"]) <= now


def run_source(store: Store, collector: Collector, fetcher, now: datetime) -> RunResult:
    state = store.source_state(collector.source)
    fails = state["fail_count"] if state else 0
    try:
        payload = fetcher.get(collector.url)
        items = collector.parse(payload, now)
        store.save_items(items)
    except Exception as err:  # noqa: BLE001 — one broken source must never stop the run
        fails += 1
        rate_limited = isinstance(err, RateLimited)
        expected = isinstance(err, (FetchError, ParseError))
        message = (str(err) or type(err).__name__)[:ERROR_MAX]
        if not expected:
            message = f"{type(err).__name__}: {message}"[:ERROR_MAX]
            log.exception("%s: unexpected error", collector.source)
        else:
            log.warning("%s: %s (failure %d in a row)", collector.source, message, fails)
        delay = failure_delay_s(fails, rate_limited=rate_limited,
                                retry_after_s=getattr(err, "retry_after_s", None))
        store.record_run(collector.source, now, datetime.now(timezone.utc), ok=False, n_items=0,
                         error=message, next_due=iso_utc(now + timedelta(seconds=delay)), fail_count=fails)
        return RunResult(collector.source, False, 0, message)
    store.record_run(collector.source, now, datetime.now(timezone.utc), ok=True, n_items=len(items),
                     error=None, next_due=iso_utc(now + timedelta(seconds=collector.interval_s)), fail_count=0)
    log.info("%s: %d items", collector.source, len(items))
    return RunResult(collector.source, True, len(items), None)


def run_once(store: Store, collectors: list[Collector], fetcher, now: datetime) -> list[RunResult]:
    return [run_source(store, c, fetcher, now) for c in collectors if is_due(store, c, now)]


def run_loop(store: Store, collectors: list[Collector], fetcher, *,
             after_cycle: Callable[[list[RunResult]], None] | None = None,
             now: Callable[[], datetime] = lambda: datetime.now(timezone.utc),
             sleep: Callable[[float], None] = time.sleep,
             tick_s: float = 60, stop_at: datetime | None = None) -> None:
    """Run cycles until stop_at (forever when None). after_cycle runs when a source was fetched."""
    while stop_at is None or now() < stop_at:
        results = run_once(store, collectors, fetcher, now())
        if results and after_cycle:
            try:
                after_cycle(results)
            except Exception:  # noqa: BLE001 — a failed Recon build must not stop collection
                log.exception("after-cycle step failed")
        sleep(tick_s)
