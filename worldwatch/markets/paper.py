"""The practice portfolio (Q18): play money in pesos, priced from the numbers World Watch already
stored. It never talks to a broker, places no order anywhere and moves no money; it is a file,
`data/paper.json`, written only by the `paper` command (the Board can't write, D-17).

A buy of a dollar-priced asset converts at the newest stored FIX. Only things that can be bought
directly are tradable: US-listed shares and ETFs (Twelve Data) and crypto (CoinGecko) — not an index
or a rate.
"""

from __future__ import annotations

import json
import os
from dataclasses import dataclass
from datetime import datetime, timedelta
from decimal import Decimal, InvalidOperation
from pathlib import Path

from ..item import iso_utc
from ..store import Store
from . import number
from .catalog import INSTRUMENTS, Instrument, watch_instrument

START_MXN = Decimal("100000")
TRADABLE = ("twelvedata", "coingecko")
PRICE_FRESH = timedelta(days=5)
MAX_TRADES = 5000
MAX_BYTES = 2_000_000
FIX_ID = "usd-mxn-fix"
RECENT = 20  # the newest trades the page lists


class PaperError(ValueError):
    """A trade that can't be made (no price, not enough play money, a typo); nothing is written."""


@dataclass(frozen=True)
class Price:
    value: Decimal
    currency: str
    at: str


def empty() -> dict:
    return {"start_mxn": str(START_MXN), "trades": []}


def load(path: Path) -> dict:
    try:
        if path.stat().st_size > MAX_BYTES:
            raise PaperError(f"{path.name} is too big to be a practice ledger")
        book = json.loads(path.read_text(encoding="utf-8"))
    except FileNotFoundError:
        return empty()
    except (OSError, UnicodeDecodeError, json.JSONDecodeError) as err:
        raise PaperError(f"{path.name} could not be read: {err}") from err
    if not isinstance(book, dict) or not isinstance(book.get("trades"), list):
        raise PaperError(f"{path.name} is not a practice ledger")
    try:
        number(book.get("start_mxn"))
    except ValueError as err:
        raise PaperError(f"{path.name}: the starting amount is not a number") from err
    for n, t in enumerate(book["trades"], 1):
        _check_trade(t, f"{path.name}, trade {n}")
    return book


def _check_trade(t: object, where: str) -> None:
    """A hand-edited or damaged entry stops here, never deeper in the sums (or the markets page)."""
    if not isinstance(t, dict) or t.get("side") not in ("buy", "sell"):
        raise PaperError(f"{where}: not a buy or a sell")
    if t.get("by", "you") not in BY:
        raise PaperError(f"{where}: made by someone unknown")
    if not isinstance(t.get("instrument"), str) or not isinstance(t.get("key", ""), str):
        raise PaperError(f"{where}: no instrument")
    for name in ("qty", "price", "fx"):
        try:
            if number(t.get(name)) <= 0:
                raise ValueError
        except ValueError as err:
            raise PaperError(f"{where}: {name} is not a positive number") from err


def save(path: Path, book: dict) -> None:
    path.parent.mkdir(parents=True, exist_ok=True)
    temp = path.with_suffix(".tmp")
    temp.write_text(json.dumps(book, indent=1), encoding="utf-8")
    os.replace(temp, path)  # all or nothing: a crash never leaves half a ledger


def find(name: str, watch: list[str] = ()) -> Instrument:
    wanted = name.strip().lower()
    pool = INSTRUMENTS + [watch_instrument(s) for s in watch]
    for inst in pool:
        if inst.source in TRADABLE and wanted in (inst.id, inst.key.lower()):
            return inst
    tradable = sorted({i.id for i in pool if i.source in TRADABLE})
    raise PaperError(f"{name!r} is not something the practice portfolio can hold; try one of: {', '.join(tradable)}")


def latest_price(store: Store, instrument_id: str, source: str, now: datetime) -> Price | None:
    rows = store.items_between(source, iso_utc(now - PRICE_FRESH), iso_utc(now + timedelta(minutes=5)), limit=5000)
    for row in rows:  # newest first
        try:
            raw = json.loads(row["raw"])
            if raw.get("instrument") == instrument_id:
                return Price(number(raw["value"]), "", row["happened_at"])
        except (ValueError, KeyError, TypeError):
            continue
    return None


def currency_of(inst: Instrument) -> str:
    return "MXN" if inst.unit_en == "MXN" else "USD"


def _in_mxn(store: Store, inst: Instrument, now: datetime) -> tuple[Decimal, Decimal, str]:
    """(price in its currency, the FIX used, when the price is from)."""
    price = latest_price(store, inst.id, inst.source, now)
    if price is None:
        raise PaperError(f"no price for {inst.en} in the last {PRICE_FRESH.days} days; let World Watch fetch first")
    fx = Decimal(1)
    if currency_of(inst) == "USD":
        fix = latest_price(store, FIX_ID, "banxico-peso", now)
        if fix is None:
            raise PaperError("no recent FIX to turn dollars into pesos; let World Watch fetch Banxico first")
        fx = fix.value
    return price.value, fx, price.at


def cash(book: dict) -> Decimal:
    total = number(book["start_mxn"])
    for t in book["trades"]:
        cost = number(t["qty"]) * number(t["price"]) * number(t["fx"])
        total += cost if t["side"] == "sell" else -cost
    return total


def holdings(book: dict) -> dict[str, Decimal]:
    held: dict[str, Decimal] = {}
    for t in book["trades"]:
        qty = number(t["qty"])
        held[t["instrument"]] = held.get(t["instrument"], Decimal(0)) + (qty if t["side"] == "buy" else -qty)
    return {k: v for k, v in held.items() if v != 0}


BY = ("you", "assistant")  # who made the trade: the assistant (a later task) keeps its own scored record


def trade(book: dict, store: Store, side: str, name: str, qty_text: str, now: datetime,
          watch: list[str] = (), by: str = "you") -> dict:
    """A new ledger with the trade added (the old one is not changed)."""
    if side not in ("buy", "sell"):
        raise PaperError("buy or sell")
    if by not in BY:
        raise PaperError(f"a trade is made by one of {BY}")
    inst = find(name, watch)
    try:
        qty = Decimal(qty_text)
    except InvalidOperation as err:
        raise PaperError(f"{qty_text!r} is not a quantity") from err
    if not qty.is_finite() or qty <= 0 or qty > Decimal("1e9"):
        raise PaperError("the quantity must be a positive number")
    if inst.source != "coingecko" and qty != qty.to_integral_value():
        raise PaperError("shares are bought whole")
    if len(book["trades"]) >= MAX_TRADES:
        raise PaperError(f"the ledger is full ({MAX_TRADES} trades)")
    price, fx, price_at = _in_mxn(store, inst, now)
    cost = qty * price * fx
    if side == "buy" and cost > cash(book):
        raise PaperError(f"not enough play money: this costs {cost:,.2f} MXN, cash is {cash(book):,.2f} MXN")
    if side == "sell" and qty > holdings(book).get(inst.id, Decimal(0)):
        raise PaperError(f"you hold {holdings(book).get(inst.id, Decimal(0))} of {inst.id}")
    entry = {"at": iso_utc(now), "by": by, "side": side, "instrument": inst.id, "key": inst.key, "source": inst.source,
             "qty": str(qty),
             "price": str(price), "currency": currency_of(inst), "fx": str(fx), "price_at": price_at}
    return {**book, "trades": [*book["trades"], entry]}


def summary(book: dict, store: Store, now: datetime) -> dict:
    """What the markets page shows: cash, each holding at today's stored price, the total vs the start."""
    rows, total = [], cash(book)
    by_id = {t["instrument"]: t["source"] for t in book["trades"]}
    keys = {t["instrument"]: str(t.get("key", "")) for t in book["trades"]}
    for inst_id, qty in sorted(holdings(book).items()):
        spent = sum((number(t["qty"]) * number(t["price"]) * number(t["fx"]) * (1 if t["side"] == "buy" else -1)
                     for t in book["trades"] if t["instrument"] == inst_id), Decimal(0))
        row = {"id": inst_id, "qty": str(qty), "cost_mxn": f"{spent:.2f}", "value_mxn": None, "price_at": None}
        try:
            inst = next(i for i in INSTRUMENTS if i.id == inst_id) if not inst_id.startswith("watch-") else \
                watch_instrument(inst_id[len("watch-"):].upper())
            price, fx, at = _in_mxn(store, inst, now)
            value = qty * price * fx
            row.update(value_mxn=f"{value:.2f}", price_at=at)
            total += value
        except (PaperError, StopIteration):
            total += spent  # no fresh price: counted at what it cost, and the row says so
        row["source"] = by_id.get(inst_id)
        rows.append(row)
    start = number(book["start_mxn"])
    return {"start_mxn": f"{start:.2f}", "cash_mxn": f"{cash(book):.2f}", "total_mxn": f"{total:.2f}",
            "change_pct": float((total - start) / start * 100) if start else None, "holdings": rows,
            "trades": len(book["trades"]), "last_trade": book["trades"][-1]["at"] if book["trades"] else None,
            "recent": [{k: t.get(k) for k in ("at", "by", "side", "instrument", "qty", "price", "currency", "fx", "price_at")}
                       for t in book["trades"][-RECENT:][::-1]]}
