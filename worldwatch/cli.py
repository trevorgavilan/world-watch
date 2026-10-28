"""Command line: python -m worldwatch <command>

  once            fetch every due source once, then build Recon
  loop [--hours]  keep fetching on each source's interval; rebuild Recon when something arrives
  start           what World Watch.bat runs: serve the Board on 127.0.0.1, catch up, build Recon,
                  open the Board, then keep collecting until the window is closed (which stops both)
  recon [--open]  build Recon from what is stored
  status [--hours] per-source runs, failures and the longest gap — the unattended-run evidence

once, loop and start collect, so only one of them runs at a time (an OS file lock).
"""

from __future__ import annotations

import argparse
import logging
import os
import socket
import sys
import threading
import time
from datetime import datetime, timedelta, timezone
from logging.handlers import RotatingFileHandler
from pathlib import Path

from . import console, recon, runner
from .board import server as board_server
from .collectors import all_collectors
from .http import Fetcher
from .item import iso_utc, parse_iso_utc
from .store import Store

log = logging.getLogger("worldwatch")

HEARTBEAT_S = 3600  # "still collecting" once an hour: a stall shows in the log
REAL_BOARD_PORT = board_server.BOARD_PORT
BOARD_PORT = REAL_BOARD_PORT  # the tests move it to a free port


def home() -> Path:
    return Path(os.environ.get("WORLDWATCH_HOME") or Path(__file__).resolve().parent.parent / "data")


def setup_logging(base: Path) -> None:
    (base / "logs").mkdir(parents=True, exist_ok=True)
    handlers: list[logging.Handler] = [
        RotatingFileHandler(base / "logs" / "worldwatch.log", maxBytes=1_000_000, backupCount=5, encoding="utf-8")
    ]
    if sys.stderr is not None:  # pythonw has no console
        handlers.append(logging.StreamHandler())
    logging.basicConfig(level=logging.INFO, handlers=handlers, force=True,
                        format="%(asctime)s %(levelname)s %(name)s: %(message)s")


class SingleInstance:
    """An OS lock on a file: released by the OS if the process dies, so it never goes stale."""

    def __init__(self, path: Path) -> None:
        self.path = path
        self.handle = None

    def acquire(self) -> bool:
        self.path.parent.mkdir(parents=True, exist_ok=True)
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

    def release(self) -> None:
        if self.handle is None:
            return
        try:
            if os.name == "nt":
                import msvcrt
                self.handle.seek(0)
                msvcrt.locking(self.handle.fileno(), msvcrt.LK_UNLCK, 1)
        finally:
            self.handle.close()  # closing also drops a POSIX flock
            self.handle = None


def _now() -> datetime:
    return datetime.now(timezone.utc)


def wait_for_network(resolve=socket.getaddrinfo, sleep=time.sleep, attempts: int = 12,
                     pause_s: float = 10, host: str = "earthquake.usgs.gov") -> bool:
    """Just after the PC starts the network often isn't up yet: wait (up to ~2 min) until a feed's name resolves.
    A DNS lookup of a feed we read anyway — nothing is probed."""
    for attempt in range(attempts):
        try:
            resolve(host, 443)
            return True
        except OSError:
            if attempt < attempts - 1:
                sleep(pause_s)
    return False


def _build_recon(store: Store, collectors, base: Path) -> Path:
    html_path, _ = recon.build(store, collectors, _now(), base / "recon")
    log.info("Recon written: %s", html_path)
    return html_path


def _open(target: Path | str) -> None:
    """A file we wrote, or the Board's own 127.0.0.1 address."""
    if hasattr(os, "startfile"):
        os.startfile(str(target))  # noqa: S606 — our own file or our own local page
    else:
        log.info("open it: %s", target)


def board_url(port: int) -> str:
    return f"http://{board_server.BOARD_HOST}:{port}/"


def _start_board(store_path: Path, collectors, recon_dir: Path):
    """A thread of this process (D-18): it ends when the window closes. None if it cannot listen."""
    try:
        srv = board_server.make_server(store_path, collectors, recon_dir, port=BOARD_PORT)
    except OSError as err:
        log.warning("Board not started (port %d in use?): %s — opening Recon instead", BOARD_PORT, err)
        return None
    except ValueError:  # a source registered a bad or duplicate layer/panel id: still collect
        log.exception("Board not started — opening Recon instead")
        return None
    threading.Thread(target=srv.serve_forever, name="board", daemon=True).start()
    log.info("Board at %s", board_url(srv.server_port))
    return srv


def _stop_board(srv) -> None:
    if srv is not None:
        srv.shutdown()
        srv.server_close()


def _board_answers(port: int) -> bool:
    """Is the other window's Board up? A connect to our own loopback port, nothing else."""
    try:
        socket.create_connection((board_server.BOARD_HOST, port), timeout=1).close()
        return True
    except OSError:
        return False


def _locked(base: Path) -> SingleInstance | None:
    lock = SingleInstance(base / "worldwatch.lock")
    if lock.acquire():
        return lock
    log.warning("another World Watch is already collecting (another World Watch window?); not starting a second one")
    return None


def cmd_once(store, collectors, base, args) -> int:
    lock = _locked(base)
    if lock is None:
        return 2
    try:
        results = runner.run_once(store, collectors, Fetcher(), _now())
        _build_recon(store, collectors, base)
    finally:
        lock.release()
    return 0 if all(r.ok for r in results) else 1


def cmd_loop(store, collectors, base, args) -> int:
    lock = _locked(base)
    if lock is None:
        return 2
    stop_at = _now() + timedelta(hours=args.hours) if args.hours else None
    try:
        runner.run_loop(store, collectors, Fetcher(), stop_at=stop_at,
                        after_cycle=lambda results: _build_recon(store, collectors, base))
    finally:
        lock.release()
    return 0


def cmd_start(store, collectors, base, args) -> int:
    """The PC is switched on at no fixed time: each start catches up on what was missed
    (a source picks its own catch-up URL from its last good fetch), then keeps collecting."""
    latest = base / "recon" / "recon-latest.html"
    lock = _locked(base)
    if lock is None:
        if _board_answers(REAL_BOARD_PORT):
            print("World Watch is already running in another window; opening its Board.")
            _open(board_url(REAL_BOARD_PORT))
        else:
            print("World Watch is already running in another window; opening the last Recon.")
            if latest.exists():
                _open(latest)
        return 2
    log.info("World Watch started (pid %d)", os.getpid())
    console.setup()
    board = _start_board(base / "worldwatch.sqlite3", collectors, base / "recon")
    try:
        if not wait_for_network():
            log.warning("no network after waiting; building Recon from what is stored")
        fetcher = Fetcher()
        try:
            runner.run_once(store, collectors, fetcher, _now())
        except Exception:  # noqa: BLE001 — still show Recon and keep collecting
            log.exception("first fetch failed")
        try:
            recon_path = _build_recon(store, collectors, base)
        except Exception:  # noqa: BLE001
            log.exception("Recon build failed")
            recon_path = latest if latest.exists() else None
        if board is not None:
            _open(board_url(board.server_port))
        elif recon_path is not None:
            _open(recon_path)
        log.info("collecting until this window is closed")
        runner.run_loop(store, collectors, fetcher, heartbeat_s=HEARTBEAT_S,
                        after_cycle=lambda results: _build_recon(store, collectors, base))
    finally:
        _stop_board(board)
        log.info("World Watch stopped")
        lock.release()
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


COMMANDS = {"once": cmd_once, "loop": cmd_loop, "start": cmd_start, "recon": cmd_recon, "status": cmd_status}


def main(argv: list[str] | None = None) -> int:
    parser = argparse.ArgumentParser(prog="worldwatch", description=__doc__,
                                     formatter_class=argparse.RawDescriptionHelpFormatter)
    sub = parser.add_subparsers(dest="command", required=True)
    sub.add_parser("once")
    loop = sub.add_parser("loop")
    loop.add_argument("--hours", type=float, default=None)
    sub.add_parser("start")
    rec = sub.add_parser("recon")
    rec.add_argument("--open", action="store_true")
    status = sub.add_parser("status")
    status.add_argument("--hours", type=float, default=24.0)
    args = parser.parse_args(argv)
    for stream in (sys.stdout, sys.stderr):  # the Windows console defaults to cp1252; pythonw has neither
        if stream is not None and hasattr(stream, "reconfigure"):
            stream.reconfigure(encoding="utf-8", errors="replace")

    base = home()
    setup_logging(base)
    store = None
    try:
        store = Store(base / "worldwatch.sqlite3")
        return COMMANDS[args.command](store, all_collectors(), base, args)
    except KeyboardInterrupt:
        return 130
    except Exception:  # noqa: BLE001 — under pythonw there is no console: the log is the only witness
        log.exception("World Watch stopped on an unexpected error")
        return 1
    finally:
        if store is not None:
            store.close()
