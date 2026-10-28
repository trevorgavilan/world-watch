"""Planted bugs: each mutant breaks one rule that matters; the suite must catch every one.

    python tools/mutants.py

Copies the code to a temp folder per mutant, applies one edit, runs the tests,
and expects them to fail. Exit 0 only when every mutant is caught.
"""

from __future__ import annotations

import shutil
import subprocess
import sys
import tempfile
from pathlib import Path

ROOT = Path(__file__).resolve().parent.parent

MUTANTS = [
    ("links: javascript: accepted", "worldwatch/item.py",
     'not in ("http", "https")', 'not in ("http", "https", "javascript")'),
    ("render: title not escaped", "worldwatch/recon_html.py",
     'title = escape(row["title"])', 'title = row["title"]'),
    ("store: re-save overwrites first fetch time", "worldwatch/store.py",
     'if c not in ("id", "fetched_at")', 'if c != "id"'),
    ("runner: backoff never grows", "worldwatch/runner.py",
     "return min(RETRY_BASE_S * 2 ** exponent, RETRY_MAX_S)", "return RETRY_BASE_S"),
    ("runner: 429 treated as an ordinary error", "worldwatch/runner.py",
     "rate_limited = isinstance(err, RateLimited)", "rate_limited = False"),
    ("runner: a bug in one source stops the run", "worldwatch/runner.py",
     "except Exception as err:  # noqa", "except (FetchError, ParseError) as err:  # noqa"),
    ("runner: not-due sources fetched anyway", "worldwatch/runner.py",
     "return next_due <= now or next_due > now + horizon", "return True"),
    ("collectors: one odd record sinks the batch", "worldwatch/collectors/__init__.py",
     "except Exception as err:  # noqa: BLE001 — one odd record", "except (KeyError, ValueError) as err:  # noqa: BLE001 — one odd record"),
    ("kev: CVE id not validated", "worldwatch/collectors/cisa_kev.py",
     "if not isinstance(cve, str) or not CVE_PATTERN.fullmatch(cve):", "if False:"),
    ("runner: a failing cycle ends the loop", "worldwatch/runner.py",
     "except Exception:  # noqa: BLE001 — a locked database", "except ValueError:  # noqa: BLE001 — a locked database"),
    ("recon: CSP allows any inline script", "worldwatch/recon_html.py",
     "f\"script-src 'sha256-{_hash(SCRIPT)}'; ", "\"script-src 'unsafe-inline'; \" f\""),
    ("recon: stale never flagged within a day", "worldwatch/recon.py",
     "stale = now - last_ok > timedelta(seconds=collector.interval_s * STALE_FACTOR)",
     "stale = now - last_ok > timedelta(days=1)"),
    ("markdown: link syntax not escaped", "worldwatch/recon_md.py",
     r'_MD_SPECIAL = re.compile(r"([\\`*_{}\[\]()#+!|<>~])")', r'_MD_SPECIAL = re.compile(r"([\\`*_#+!|<>~])")'),
    ("recon: date-only KEV shifted to CDMX time", "worldwatch/recon.py",
     'DATE_ONLY_SOURCES = {"cisa-kev"}', "DATE_ONLY_SOURCES = set()"),
    ("http: 429 not recognised", "worldwatch/http.py",
     "if err.code == 429:", "if err.code == 999:"),
    # D-18: started by World Watch.bat whenever the PC is on — catch up after any gap, say when alive.
    ("usgs: a long gap never catches up", "worldwatch/collectors/usgs.py",
     "if last_ok is None or now - last_ok <= CATCH_UP_AFTER:", "if True:"),
    ("usgs: catch-up starts exactly at the last fetch, no overlap", "worldwatch/collectors/usgs.py",
     "start = max(last_ok - CATCH_UP_MARGIN, now - CATCH_UP_MAX)", "start = max(last_ok, now - CATCH_UP_MAX)"),
    ("usgs: catch-up window not capped", "worldwatch/collectors/usgs.py",
     "start = max(last_ok - CATCH_UP_MARGIN, now - CATCH_UP_MAX)", "start = last_ok - CATCH_UP_MARGIN"),
    ("runner: last good fetch ignored when choosing the URL", "worldwatch/runner.py",
     "for url in collector.fetch_urls(last_ok, now):", "for url in [collector.url]:"),
    ("usgs: catch-up asks M3.5+ worldwide (over the query cap)", "worldwatch/collectors/usgs.py",
     '{**common, "minmagnitude": GLOBAL_MIN_MAG},', '{**common, "minmagnitude": MEXICO_MIN_MAG},'),
    ("cli: start leaves the lock held", "worldwatch/cli.py",
     '''        log.info("World Watch stopped")
        lock.release()''', '''        log.info("World Watch stopped")'''),
    ("runner: heartbeat never fires", "worldwatch/runner.py",
     "if heartbeat_s and monotonic() - last_beat >= heartbeat_s:", "if False:"),
    ("runner: waking from sleep not logged", "worldwatch/runner.py",
     "if slept > tick_s + WAKE_GAP_S:", "if False:"),
    # D-17: the Board — local, read-only, nothing from outside, source text is text.
    ("board: Host header not checked (DNS rebinding)", "worldwatch/board/server.py",
     'if (self.headers.get("Host") or "").lower() not in self.server.allowed_hosts:', "if False:"),
    ("board: any port accepted in Host", "worldwatch/board/server.py",
     'if (self.headers.get("Host") or "").lower() not in self.server.allowed_hosts:',
     'if (self.headers.get("Host") or "").lower().split(":")[0] not in ("127.0.0.1", "localhost"):'),
    ("board: listens on any address", "worldwatch/board/server.py",
     "    if host != BOARD_HOST:\n", "    if False:\n"),
    ("board: CSP allows inline script", "worldwatch/board/server.py",
     "script-src 'self'; style-src", "script-src 'self' 'unsafe-inline'; style-src"),
    ("board: POST answered like GET", "worldwatch/board/server.py",
     "do_POST = do_PUT = do_DELETE = do_PATCH = do_OPTIONS = _refuse_write",
     "do_POST = do_GET\n    do_PUT = do_DELETE = do_PATCH = do_OPTIONS = _refuse_write"),
    ("store: the Board's connection can write", "worldwatch/store.py", "?mode=ro", "?mode=rwc"),
    ("board: links not re-checked before the page", "worldwatch/board/data.py",
     '"url": clean_url(row["url"]),', '"url": row["url"],'),
    ("board: JSON not escaped for < > &", "worldwatch/board/server.py",
     'return text.replace("<", ', 'return text.replace("<<", '),
    ("board: impossible coordinates put on the globe", "worldwatch/store.py",
     '"AND lat BETWEEN -90 AND 90 AND lon BETWEEN -180 AND 180 "', '"AND lat IS NOT NULL AND lon IS NOT NULL "'),
    ("board: a panel ignores its window", "worldwatch/board/data.py",
     "store.items_between(source, iso_utc(now - window),", "store.items_between(source, \"0000\","),
    ("board: duplicate layer ids accepted", "worldwatch/board/data.py",
     "if view.id in table:", "if False:"),
    ("board: point labels on (globe.gl renders them as HTML)", "worldwatch/board/static/board.js",
     ".pointLabel(null)", '.pointLabel("title")'),
    ("cli: start never serves the Board", "worldwatch/cli.py",
     'board = _start_board(base / "worldwatch.sqlite3", collectors, base / "recon")', "board = None"),
    ("cli: the Board outlives the window", "worldwatch/cli.py",
     "        _stop_board(board)\n", ""),
]


def run_one(name: str, rel: str, old: str, new: str) -> bool:
    with tempfile.TemporaryDirectory(prefix="ww-mutant-") as tmp:
        work = Path(tmp)
        shutil.copytree(ROOT / "worldwatch", work / "worldwatch")
        shutil.copytree(ROOT / "tests", work / "tests")
        target = work / rel
        text = target.read_text(encoding="utf-8")
        if text.count(old) != 1:
            print(f"  BROKEN MUTANT  {name}: pattern found {text.count(old)} times")
            return False
        target.write_text(text.replace(old, new), encoding="utf-8")
        result = subprocess.run([sys.executable, "-m", "unittest", "discover", "-s", "tests", "-t", "."],
                                cwd=work, capture_output=True, text=True, timeout=300)
        caught = result.returncode != 0
        print(f"  {'caught ' if caught else 'MISSED '}  {name}")
        return caught


def main() -> int:
    results = [run_one(*m) for m in MUTANTS]
    print(f"{sum(results)}/{len(results)} mutants caught")
    return 0 if all(results) else 1


if __name__ == "__main__":
    sys.exit(main())
