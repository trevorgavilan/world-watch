"""GDELT DOC 2.0 article lists — v0's news: Al Jazeera in English (D-12's lead
outlet) and Mexican outlets in Spanish. The full outlet list waits on Q16.

Docs: https://blog.gdeltproject.org/gdelt-doc-2-0-api-debuts/
Terms: free for any use; cite the GDELT Project and link gdeltproject.org.
Only title, link, outlet and time are kept — the article belongs to its publisher.
Rate: "one request every 5 seconds", and it answers 429 more often than that
suggests, so intervals are long and the runner backs off.
"""

from __future__ import annotations

from datetime import datetime, timezone
from functools import partial
from urllib.parse import urlencode

from ..item import make_item
from . import Collector, ParseError

LICENCE = "GDELT Project (cite gdeltproject.org); headline and link only, article © its publisher"
API = "https://api.gdeltproject.org/api/v2/doc/doc"
LANGS = {"English": "en", "Spanish": "es"}


def query_url(query: str) -> str:
    params = {
        "query": query,
        "mode": "artlist",
        "format": "json",
        "maxrecords": "75",
        "timespan": "24h",  # a PC that was off overnight still gets the last day
        "sort": "datedesc",
    }
    return f"{API}?{urlencode(params)}"


def _build(source: str, article: dict, fetched_at: datetime):
    seen = datetime.strptime(article["seendate"], "%Y%m%dT%H%M%SZ").replace(tzinfo=timezone.utc)
    return make_item(
        channel="news",
        source=source,
        native_id=article["url"],
        happened_at=seen,
        fetched_at=fetched_at,
        title=article["title"],
        url=article["url"],
        summary=article.get("domain", ""),
        country=article.get("sourcecountry"),
        licence=LICENCE,
        raw=article,
        lang=LANGS.get(article.get("language", "")),
    )


def _parser(source: str):
    def parse_records(data: object, fetched_at: datetime) -> list:
        if not isinstance(data, dict):
            raise ParseError(f"{source}: not a JSON object")
        articles = data.get("articles", [])  # GDELT returns {} when nothing matched
        if not isinstance(articles, list):
            raise ParseError(f"{source}: 'articles' is not a list")
        return [partial(_build, source, a, fetched_at) for a in articles if isinstance(a, dict)]

    return parse_records


def _collector(source: str, query: str) -> Collector:
    return Collector(
        source=source,
        channel="news",
        url=query_url(query),
        interval_s=60 * 60,
        licence=LICENCE,
        parse_records=_parser(source),
    )


COLLECTORS = [
    _collector("gdelt-aljazeera", "domainis:aljazeera.com"),
    _collector("gdelt-mx", "sourcecountry:mexico sourcelang:spanish"),
]
