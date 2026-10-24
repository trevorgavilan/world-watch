# World Watch

A private, read-only reader of public feeds that builds **Morning Recon**: one page, phone-ready,
English and Spanish. Plan and decisions live in the Nematic Vault (`WORLD WATCH HANDOFF`).

**v0 (Task 2):** three keyless sources and a no-model Recon.

| Source | What | Every | Licence |
|---|---|---|---|
| `usgs-quakes` | USGS M2.5+ past-week GeoJSON; keeps M4.5+ anywhere, sig ≥ 600, M3.5+ around Mexico | 15 min | US public domain |
| `cisa-kev` | CISA Known Exploited Vulnerabilities, whole catalogue | 6 h | CC0 1.0 |
| `gdelt-aljazeera`, `gdelt-mx` | GDELT DOC 2.0 article lists: Al Jazeera (EN), Mexican outlets (ES), last 24 h | 1 h | cite GDELT; headlines and links only |

Standard library only — Python 3.13, nothing to install.

## Run it

From `D:\TREVOR DATA\world-watch\`:

```
python -m worldwatch once          # fetch what is due, build Recon
python -m worldwatch recon --open  # build Recon from what is stored and open it
python -m worldwatch loop          # keep collecting (Ctrl+C to stop); --hours N to stop after N hours
python -m worldwatch status        # last 24 h: runs, failures, longest gap per source
```

**At logon** the Scheduled Task "World Watch (logon)" runs `pythonw -m worldwatch logon`: it fetches,
builds today's Recon, opens it in the browser, then keeps collecting until logoff. Only one copy runs.
Register or remove it with `tools\register-logon-task.ps1` (see the script's header).

Output, all under `data\` (not in git):

- `data\recon\recon-YYYY-MM-DD.html` + `.md`, and `recon-latest.html` — dated by Mexico City time
- `data\worldwatch.sqlite3` — the store (WAL); `data\logs\worldwatch.log` — rotating log

`WORLDWATCH_HOME` moves `data\` elsewhere (the tests and trial runs use a temp folder).

## Test it

```
python -m unittest discover -s tests -t .              # offline: saved real responses
set WW_LIVE=1 && python -m unittest discover -s tests -t .   # also hit the live feeds
python tools\mutants.py                                # planted bugs: all must be caught
```

## How it fits together

- `worldwatch/item.py` — the adapter contract (`Item`); `make_item` is the boundary where every
  field from a source is cleaned, capped and validated (http/https links only).
- `worldwatch/collectors/` — one module per source: its URL, interval, licence and `parse`.
- `worldwatch/http.py` — polite GET: User-Agent, timeout, 25 MB cap, a 6 s gap per GDELT request, 429 → back off.
- `worldwatch/store.py` — SQLite schema (items, source_state, runs).
- `worldwatch/runner.py` — per-source intervals; failures back off (2 min doubling to 1 h; 429: 15 min doubling to 6 h)
  and never stop the other sources.
- `worldwatch/recon*.py` — Recon: self-contained HTML (strict CSP, no outside requests) and its Markdown twin.

Rules that are not optional: public feeds only, no scanning of anyone (D-7); every item shows its
source, event time, fetch time and licence, and says whether it is reported or inferred (D-8);
no keys or personal data in code, logs or commits. Third-party code: see `NOTICE`.
