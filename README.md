# World Watch

A private, read-only reader of public feeds that builds **Morning Recon**: one page, phone-ready,
English and Spanish. Plan and decisions live in the Nematic Vault (`WORLD WATCH HANDOFF`).

**v0 (Task 2, 2b):** keyless sources, a no-model Recon, and the **Board** — a globe with the quakes
layer, the KEV panel and a freshness bar per source, at `http://127.0.0.1:8420/`. Nothing runs in
the background: you start it.

## Start it

Double-click **`World Watch.bat`** (in this folder). It catches up on whatever happened while the PC
was off — an hour or a month — builds today's Morning Recon, opens it in the browser, and keeps
collecting in that window until you close it. Switch the PC on and off whenever you like:

- USGS: the past-week feed normally; after a gap of more than 6 days, the USGS catalogue query
  fetches what was missed since the last good fetch, with a day of overlap (up to a year back:
  M4.5+ worldwide and M3.5+ around Mexico). CISA KEV is the whole
  catalogue every time, so it never misses anything.
- The window logs "still collecting" once an hour and "woke after …" when the PC comes back from
  sleep, so a stall shows there and in the log.
- Double-clicking it again while it runs only reopens the last Recon (one copy collects at a time).
- The Board runs inside that same window: it opens in the browser once the catch-up is done, reads
  only the local store (read-only), and refreshes every minute. It listens on 127.0.0.1:8420 only
  and answers only to its own name (127.0.0.1 or localhost); no route writes; the page loads
  nothing from the internet (globe.gl and the NASA image are vendored in `worldwatch/board/static/vendor/`
  with their checksums). If port 8420 is taken, World Watch still collects and opens Recon instead.
  Morning Recon is one click away (top right), or at `/recon`.
- Closing the window stops it and logs "World Watch stopped (window closed)"; the store is SQLite
  in WAL mode, so nothing half-written is kept.

| Source | What | Every | Licence |
|---|---|---|---|
| `usgs-quakes` | USGS M2.5+ past-week GeoJSON (catalogue query after a longer gap); keeps M4.5+ anywhere, sig ≥ 600, M3.5+ around Mexico | 15 min | US public domain |
| `cisa-kev` | CISA Known Exploited Vulnerabilities, whole catalogue | 6 h | CC0 1.0 |
| `gdelt-aljazeera`, `gdelt-mx` | **parked (D-16), not in the run:** GDELT DOC 2.0 article lists | 1 h | cite GDELT; headlines and links only |

Standard library only — Python 3.13, nothing to install.

## Other commands

From `D:\TREVOR DATA\world-watch\`:

```
python -m worldwatch start         # what World Watch.bat runs
python -m worldwatch once          # fetch what is due, build Recon
python -m worldwatch recon --open  # build Recon from what is stored and open it
python -m worldwatch loop          # keep collecting (Ctrl+C to stop); --hours N to stop after N hours
python -m worldwatch status        # last 24 h: runs, failures, longest gap per source
```

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
- `worldwatch/views.py` — how a source shows on the Board: a `Layer` (points on the globe) and/or a
  `Panel` (a list), registered on the source's own `Collector` (`layer=`, `panel=`). Adding a source's
  layer or panel touches no Board code.
- `worldwatch/board/` — the Board: `server.py` (127.0.0.1 only, Host check, GET/HEAD only, strict CSP,
  a fixed list of static files), `data.py` (the read-only answers), `static/` (page, script, vendored files).

Rules that are not optional: public feeds only, no scanning of anyone (D-7); every item shows its
source, event time, fetch time and licence, and says whether it is reported or inferred (D-8);
no keys or personal data in code, logs or commits. Third-party code: see `NOTICE`.
