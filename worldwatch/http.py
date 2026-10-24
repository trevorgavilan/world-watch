"""Polite HTTP GET for public feeds: a User-Agent, a timeout, a size cap,
a minimum gap per host, and 429 reported as RateLimited so the runner backs off.
"""

from __future__ import annotations

import time
import urllib.error
import urllib.request
from urllib.parse import urlsplit

USER_AGENT = "world-watch/0.1 (private personal reader; one request per feed per interval)"
TIMEOUT_S = 30
MAX_BYTES = 25 * 1024 * 1024

# GDELT asks for at most one request every 5 seconds; leave a margin.
HOST_MIN_GAP_S = {"api.gdeltproject.org": 6.0}


class FetchError(Exception):
    """The network or the server failed; nothing was stored."""


class RateLimited(FetchError):
    def __init__(self, message: str, retry_after_s: float | None) -> None:
        super().__init__(message)
        self.retry_after_s = retry_after_s


def _retry_after(value: str | None) -> float | None:
    if value and value.strip().isdigit():
        return float(value.strip())
    return None


class Fetcher:
    def __init__(self, sleep=time.sleep, clock=time.monotonic) -> None:
        self._sleep = sleep
        self._clock = clock
        self._last_by_host: dict[str, float] = {}

    def _wait_for_host(self, host: str) -> None:
        gap = HOST_MIN_GAP_S.get(host)
        last = self._last_by_host.get(host)
        if gap and last is not None:
            remaining = gap - (self._clock() - last)
            if remaining > 0:
                self._sleep(remaining)
        self._last_by_host[host] = self._clock()

    def get(self, url: str) -> bytes:
        host = urlsplit(url).hostname or ""
        self._wait_for_host(host)
        request = urllib.request.Request(url, headers={"User-Agent": USER_AGENT})
        try:
            with urllib.request.urlopen(request, timeout=TIMEOUT_S) as response:
                body = response.read(MAX_BYTES + 1)
        except urllib.error.HTTPError as err:
            if err.code == 429:
                raise RateLimited(f"429 from {host}", _retry_after(err.headers.get("Retry-After"))) from err
            raise FetchError(f"HTTP {err.code} from {host}") from err
        except (urllib.error.URLError, TimeoutError, OSError) as err:
            raise FetchError(f"network error for {host}: {err}") from err
        if len(body) > MAX_BYTES:
            raise FetchError(f"response from {host} is over {MAX_BYTES} bytes")
        return body
