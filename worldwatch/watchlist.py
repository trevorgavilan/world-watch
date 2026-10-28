"""The "my stack" watchlist: names of what Trevor uses, in a plain text file on this PC (D-20).

    # comment
    PHP
    Chrome = google chrome, chromium*
    Windows 11 = microsoft windows 11*, windows 11*

A line is a name, optionally followed by '=' and other names it goes by. A name matches an
advisory's product (or "vendor product") exactly, ignoring case and punctuation; a '*' at the end
also matches longer names that start with those words ("windows 11*" matches "Windows 11 23H2",
not "Windows 110"). Nothing here is ever sent anywhere: the file is read, never fetched with.
"""

from __future__ import annotations

import logging
import re
from dataclasses import dataclass
from pathlib import Path

log = logging.getLogger(__name__)

MAX_ENTRIES = 200
MAX_NAME = 80
MAX_FILE_BYTES = 64_000
MIN_PREFIX = 3  # "w*" would match half the catalogue

_NON_WORD = re.compile(r"[^0-9a-z]+")


def norm(text: str) -> str:
    """Lowercase words: 'PHP Group', 'php_group' and 'php-group' all become 'php group'."""
    return _NON_WORD.sub(" ", text.lower()).strip()


@dataclass(frozen=True)
class Term:
    words: str
    prefix: bool  # ended in '*': also matches longer names starting with these words

    def hits(self, candidate: str) -> bool:
        return candidate == self.words or (self.prefix and candidate.startswith(self.words + " "))


@dataclass(frozen=True)
class Entry:
    name: str
    terms: tuple[Term, ...]

    def matches(self, vendor: str, product: str) -> str | None:
        """The advisory's own words that matched ('PHP Group PHP'), or None."""
        product_n = norm(product or "")
        if not product_n:
            return None
        both = norm(f"{vendor or ''} {product}")
        for term in self.terms:
            if term.hits(product_n) or term.hits(both):
                return " ".join(p for p in (vendor, product) if p and p.lower() != "n/a")
        return None


def _term(raw: str) -> Term | None:
    text = raw.strip()
    prefix = text.endswith("*")
    words = norm(text.rstrip("*"))
    if not words or "*" in text.rstrip("*") or (prefix and len(words) < MIN_PREFIX):
        return None
    return Term(words, prefix)


def parse(text: str) -> list[Entry]:
    entries: list[Entry] = []
    for number, line in enumerate(text.splitlines(), 1):
        line = line.strip()
        if not line or line.startswith("#"):
            continue
        name, _, aliases = line.partition("=")
        name = name.strip()
        if not name or len(name) > MAX_NAME:
            log.warning("watchlist line %d skipped: a name of 1-%d characters is needed", number, MAX_NAME)
            continue
        terms = []
        for raw in [name, *aliases.split(",")] if aliases.strip() else [name]:
            term = _term(raw)
            if term is None:
                if raw.strip():
                    log.warning("watchlist line %d: %r is not a name it can match; skipped", number, raw.strip())
                continue
            if term not in terms:
                terms.append(term)
        if terms:
            entries.append(Entry(name, tuple(terms)))
        if len(entries) >= MAX_ENTRIES:
            log.warning("watchlist: only the first %d entries are used", MAX_ENTRIES)
            break
    return entries


def load(path: Path) -> list[Entry]:
    """The entries, or [] when there is no watchlist yet (then no alert can fire)."""
    try:
        if path.stat().st_size > MAX_FILE_BYTES:
            log.warning("watchlist %s is over %d bytes; not read", path, MAX_FILE_BYTES)
            return []
        return parse(path.read_text(encoding="utf-8-sig"))
    except FileNotFoundError:
        return []
    except (OSError, UnicodeDecodeError) as err:
        log.warning("watchlist %s could not be read: %s", path, err)
        return []
