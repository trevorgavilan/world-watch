"""Command line: python -m worldwatch <command>

  once            fetch every due source once, then build Recon
  loop [--hours]  keep fetching on each source's interval; rebuild Recon when something arrives
  logon           what the logon task runs: fetch, build Recon, open it, then loop (one copy only)
  recon [--open]  build Recon from what is stored
  status [--hours] per-source runs, failures and the longest gap — the unattended-run evidence
"""

from __future__ import annotations

import argparse
import logging
import os
import sys
from datetime import datetime, timedelta, timezone
from logging.handlers import RotatingFileHandler
from pathlib import Path

from . import recon, runner
from .collectors import all_collectors
from .http import Fetcher
from .item import iso_utc, parse_iso_utc
from .store import Store

log = logging.getLogger("worldwatch")


def home() -> Path:
    return Path(os.environ.get("WORLDWATCH_HOME") or Path(__file__).resolve().parent.parent / "data")


def setup_logging(base: Path) -> None:
    (base / "logs").mkdir(parents=True, exist_ok=True)
    handlers: list[logging.Handler] = [
        RotatingFileHandler(base / "logs" / "worldwatch.log", maxBytes=1_000_000, backupCount=5, encoding="utf-8")
    ]
    if sys.stderr is not None:  # pythonw has no console
        handlers.append(logging.StreamHandler())
    logging.basicConfig(level=logging.INFO, handlers=handlers,
                        format="%(asctime)s %(levelname)s %(name)s: %(message)s")


class SingleInstance:
    """An OS lock on a file: released by the OS if the process dies, so it never goes stale."""

    def __init__(self, path: Path) -> None:
        self.path = path
        self.handle = None

    def acquire(self) -> bool:
        self.handle = open(self.path, "a+b")
        try:
            if os.name == "nt":
                import msvcrt
                self.handle.seek(0)
                msvcrt.locking(self.handle.fileno(), msvcrt.LK_NBLCK, 1)
            else:
                import fcntl
                fcntl.flock(self.handle.fileno(), fcntl.LOCK_EX | fcntl.LOCK_NB)
        except OSError:
            self.handle.close()
            self.handle = None
            return False
        return True


def _now() -> datetime:
    return datetime.now(timezone.utc)


def _build_recon(store: Store, collectors, base: Path) -> Path:
    html_path, _ = recon.build(store, collectors, _now(), base / "recon")
    log.info("Recon written: %s", html_path)
    return html_path


def _open(path: Path) -> None:
    if hasattr(os, "startfile"):
        os.startfile(path)  # noqa: S606 — our own generated file
    else:
        log.info("open it: %s", path)


def cmd_once(store, collectors, base, args) -> int:
    results = runner.run_once(store, collectors, Fetcher(), _now())
    _build_recon(store, collectors, base)
    return 0 if all(r.ok for r in results) else 1


def cmd_loop(store, collectors, base, args) -> int:
    stop_at = _now() + timedelta(hours=args.hours) if args.hours else None
    runner.run_loop(store, collectors, Fetcher(), stop_at=stop_at,
                    after_cycle=lambda results: _build_recon(store, collectors, base))
    return 0


def cmd_logon(store, collectors, base, args) -> int:
    lock = SingleInstance(base / "worldwatch.lock")
    if not lock.acquire():
        log.info("already running; opening the latest Recon only")
        latest = base / "recon" / "recon-latest.html"
        if latest.exists():
            _open(latest)
        return 0
    runner.run_once(store, collectors, Fetcher(), _now())
    _open(_build_recon(store, collectors, base))
    runner.run_loop(store, collectors, Fetcher(),
                    after_cycle=lambda results: _build_recon(store, collectors, base))
    return 0


def cmd_recon(store, collectors, base, args) -> int:
    path = _build_recon(store, collectors, base)
    if args.open:
        _open(path)
    print(path)
    return 0


def cmd_status(store, collectors, base, args) -> int:
    now = _now()
    start = now - timedelta(hours=args.hours)
    runs = store.runs_since(iso_utc(start))
    print(f"Runs since {iso_utc(start)} ({args.hours} h): {len(runs)}  ·  items stored: {store.count_items()}")
    for c in collectors:
        mine = [r for r in runs if r["source"] == c.source]
        ok_times = [parse_iso_utc(r["started_at"]) for r in mine if r["ok"]]
        points = [start, *ok_times, now]
        gap = max(b - a for a, b in zip(points, points[1:]))
        fails = sum(1 for r in mine if not r["ok"])
        last_err = next((r["error"] for r in reversed(mine) if not r["ok"]), "")
        print(f"  {c.source:18} ok {len(ok_times):4}  failed {fails:3}  longest gap {gap}  "
              f"(interval {timedelta(seconds=c.interval_s)})  {last_err[:80]}")
    return 0


def main(argv: list[str] | None = None) -> int:
    parser = argparse.ArgumentParser(prog="worldwatch", description=__doc__,
                                     formatter_class=argparse.RawDescriptionHelpFormatter)
    sub = parser.add_subparsers(dest="command", required=True)
    sub.add_parser("once")
    loop = sub.add_parser("loop")
    loop.add_argument("--hours", type=float, default=None)
    sub.add_parser("logon")
    rec = sub.add_parser("recon")
    rec.add_argument("--open", action="store_true")
    status = sub.add_parser("status")
    status.add_argument("--hours", type=float, default=24.0)
    args = parser.parse_args(argv)
    if sys.stdout is not None and hasattr(sys.stdout, "reconfigure"):
        sys.stdout.reconfigure(encoding="utf-8", errors="replace")  # the Windows console defaults to cp1252

    base = home()
    setup_logging(base)
    store = Store(base / "worldwatch.sqlite3")
    commands = {"once": cmd_once, "loop": cmd_loop, "logon": cmd_logon, "recon": cmd_recon, "status": cmd_status}
    try:
        return commands[args.command](store, all_collectors(), base, args)
    except KeyboardInterrupt:
        return 130
    finally:
        store.close()
