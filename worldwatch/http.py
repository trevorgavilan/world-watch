"""Polite HTTP GET for public feeds: a User-Agent, a timeout, a size cap,
a minimum gap per host, and 429 reported as RateLimited so the runner backs off.
"""

from __future__ import annotations

import http.client
import time
import urllib.error
import urllib.request
from urllib.parse import urlsplit

USER_AGENT = "world-watch/0.1 (private personal reader; one request per feed per interval)"
TIMEOUT_S = 30           # per socket operation
TOTAL_DEADLINE_S = 120   # for the whole body
MAX_BYTES = 25 * 1024 * 1024
CHUNK_BYTES = 64 * 1024

# GDELT asks for at most one request every 5 seconds, NIST for six seconds between NVD requests;
# OSV's bucket states no limit, so a second between record files. Leave a margin.
HOST_MIN_GAP_S = {"api.gdeltproject.org": 6.0, "services.nvd.nist.gov": 6.5, "storage.googleapis.com": 1.0}


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
                return _read_capped(response, host)
        except urllib.error.HTTPError as err:
            if err.code == 429:
                raise RateLimited(f"429 from {host}", _retry_after(err.headers.get("Retry-After"))) from err
            raise FetchError(f"HTTP {err.code} from {host}") from err
        except (urllib.error.URLError, http.client.HTTPException, TimeoutError, OSError) as err:
            raise FetchError(f"network error for {host}: {err!r}") from err


def _read_capped(response, host: str) -> bytes:
    """Read in chunks against a size cap and a whole-request deadline (the socket timeout is per read)."""
    deadline = time.monotonic() + TOTAL_DEADLINE_S
    chunks: list[bytes] = []
    size = 0
    while chunk := response.read(CHUNK_BYTES):
        size += len(chunk)
        if size > MAX_BYTES:
            raise FetchError(f"response from {host} is over {MAX_BYTES} bytes")
        if time.monotonic() > deadline:
            raise FetchError(f"response from {host} passed the {TOTAL_DEADLINE_S} s deadline")
        chunks.append(chunk)
    expected = (response.headers.get("Content-Length") or "").strip()
    if expected.isdigit() and int(expected) != size:  # the connection dropped mid-body
        raise FetchError(f"response from {host} was cut short ({size} of {expected} bytes)")
    return b"".join(chunks)
