"""Trevor's market lines, in `data/markets.txt` (git-ignored, written by hand, never by the Board):

    peso above 19.50     an alert when the FIX closes above 19.50 pesos per dollar
    peso below 17.80     … or below 17.80
    watch NVDA           a ticker for the watchlist (Twelve Data, US listings)

'#' starts a comment. A line that doesn't read is skipped and named on the markets page. The file is
a boundary: everything in it is checked before use; tickers are the only part that leaves the PC
(they go to Twelve Data, which must know what to quote).
"""

from __future__ import annotations

import re
from dataclasses import dataclass, field
from decimal import Decimal
from pathlib import Path

from . import number

MAX_BYTES = 20_000
MAX_WATCH = 20      # with the fixed symbols, a run stays inside the free plan's 800 a day
MAX_LINES = 10
PESO = re.compile(r"peso\s+(above|below)\s+(\S+)", re.IGNORECASE)
WATCH = re.compile(r"watch\s+([A-Za-z][A-Za-z0-9.\-]{0,9})", re.IGNORECASE)
PESO_RANGE = (Decimal("5"), Decimal("60"))  # a line outside this is a typo, not a peso level

TEMPLATE = """# World Watch — your market lines (information only, never advice)
# peso above 19.50   → an alert on the Board when the FIX is above 19.50 pesos per dollar
# peso below 17.80   → … or below 17.80
# watch NVDA         → a US-listed ticker on the markets page (Twelve Data)
peso above 19.50
peso below 17.80
"""


@dataclass(frozen=True)
class PesoLine:
    side: str  # "above" or "below"
    level: Decimal

    @property
    def text(self) -> str:
        return f"peso {self.side} {self.level}"

    def crossed(self, fix: Decimal) -> bool:
        return fix > self.level if self.side == "above" else fix < self.level


@dataclass
class Rules:
    peso: list[PesoLine] = field(default_factory=list)
    watch: list[str] = field(default_factory=list)
    problems: list[str] = field(default_factory=list)


def parse(text: str) -> Rules:
    rules = Rules()
    for n, raw in enumerate(text.splitlines(), 1):
        line = raw.split("#", 1)[0].strip()
        if not line:
            continue
        if m := PESO.fullmatch(line):
            try:
                level = number(m.group(2))
            except ValueError:
                rules.problems.append(f"line {n}: not a number")
                continue
            if not PESO_RANGE[0] <= level <= PESO_RANGE[1]:
                rules.problems.append(f"line {n}: {level} is not a peso level (5 to 60)")
            elif len(rules.peso) >= MAX_LINES:
                rules.problems.append(f"line {n}: more than {MAX_LINES} peso lines")
            else:
                line_ = PesoLine(m.group(1).lower(), level)
                if line_ not in rules.peso:
                    rules.peso.append(line_)
        elif m := WATCH.fullmatch(line):
            symbol = m.group(1).upper()
            if len(rules.watch) >= MAX_WATCH:
                rules.problems.append(f"line {n}: more than {MAX_WATCH} tickers")
            elif symbol not in rules.watch:
                rules.watch.append(symbol)
        else:
            rules.problems.append(f"line {n}: not understood")
    return rules


def load(path: Path) -> Rules:
    """The rules in the file; none (and one problem) when it is missing, too big or not UTF-8."""
    try:
        if path.stat().st_size > MAX_BYTES:
            return Rules(problems=[f"{path.name} is over {MAX_BYTES} bytes; not read"])
        return parse(path.read_text(encoding="utf-8-sig"))
    except FileNotFoundError:
        return Rules(problems=[f"no {path.name} yet"])
    except (OSError, UnicodeDecodeError):
        return Rules(problems=[f"{path.name} could not be read (UTF-8 text only)"])


def ensure(path: Path) -> None:
    """The first start writes the file with Trevor's two peso lines (2026-11-10); never overwrites it."""
    try:
        with path.open("x", encoding="utf-8") as handle:
            handle.write(TEMPLATE)
    except FileExistsError:
        pass
