"""Planted bugs: each mutant breaks one rule that matters; the suite must catch every one.

    python tools/mutants.py           every planted bug (~2 h)
    python tools/mutants.py layout strip    only those whose name has one of the words (while working)

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
     'DATE_ONLY_SOURCES = {"cisa-kev", "first-epss", "my-stack", "smn-cdmx"}',
     'DATE_ONLY_SOURCES = {"first-epss", "my-stack", "smn-cdmx"}'),
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
     "queue = deque(collector.fetch_urls(last_ok, now))", "queue = deque([collector.url])"),
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
    # Task 3: the watchlist alerts — exact names, a cap, the time of a replay, safe URLs, every page.
    ("watchlist: a name matches inside longer names (php -> phpMyFAQ)", "worldwatch/watchlist.py",
     "if self.words == name.product or self.words == both:", "if self.words in name.product or self.words == both:"),
    ("watchlist: '*' ignores word boundaries (windows 11* -> Windows 110)", "worldwatch/watchlist.py",
     'if name.product.startswith(self.words + " "):', "if name.product.startswith(self.words):"),
    ("alerts: no cap", "worldwatch/collectors/my_stack.py", "if room > 0:", "if True:"),
    ("alerts: a shown alert moves to another day (and frees room)", "worldwatch/collectors/my_stack.py",
     "items.append(replace(alert.item, happened_at=shown[alert.item.id]))", "items.append(alert.item)"),
    ("alerts: a replay sees a later EPSS score", "worldwatch/collectors/my_stack.py",
     '"SELECT raw FROM items WHERE id = ? AND happened_at <= ?"', '"SELECT raw FROM items WHERE id = ? OR happened_at <= ?"'),
    ("alerts: exploitation is not a second alert", "worldwatch/collectors/my_stack.py",
     "    if ev.exploited is not None:\n        stages.append(", "    if False:\n        stages.append("),
    ("osv: listing ids not checked before they become URLs", "worldwatch/collectors/osv.py",
     'if ID_PATTERN.fullmatch(record_id) and ".." not in record_id:', "if True:"),
    ("osv: one missing record fails the whole run", "worldwatch/collectors/osv.py",
     "    follow_optional=True,", "    follow_optional=False,"),
    ("nvd: only the first page is read", "worldwatch/collectors/nvd.py",
     "    if following >= total:\n        return []", "    if True:\n        return []"),
    ("nvd: paging trusts the page's own startIndex", "worldwatch/collectors/nvd.py",
     'start = int(query["startIndex"][0])', 'start = int(data["startIndex"])'),
    ("nvd: a failure is retried before two hours", "worldwatch/collectors/nvd.py",
     "    min_retry_s=2 * 3600,", "    min_retry_s=0,"),
    ("runner: follow-up URLs ignored", "worldwatch/runner.py",
     "queue.extend(collector.follow(payload, url, last_ok, now))", "pass"),
    ("runner: no cap on URLs per run", "worldwatch/runner.py",
     "if fetched > MAX_URLS_PER_RUN:", "if False:"),
    ("runner: the alerts collector fetches instead of deriving", "worldwatch/runner.py",
     "        if collector.derive:\n", "        if False:\n"),
    ("alerts: an odd advisory field stops every alert", "worldwatch/watchlist.py",
     "if not isinstance(product, str) or not isinstance(vendor, (str, type(None))):", "if not product:"),
    # Task 3b: status-page outages — safe links, honest state, exact names, the shared cap.
    ("status: incident ids not checked before they become links", "worldwatch/collectors/status_pages.py",
     "if not isinstance(native, str) or not INCIDENT_ID.fullmatch(native):", "if not isinstance(native, str):"),
    ("status: the feed's own link is trusted", "worldwatch/collectors/status_pages.py",
     'url=f"{page}/incidents/{native}"', 'url=incident.get("shortlink")'),
    ("status: an open incident is called resolved", "worldwatch/collectors/status_pages.py",
     'state = "resolved" if ended else (status or "open")', 'state = "resolved"'),
    ("status: the fetch time, not when it began", "worldwatch/collectors/status_pages.py",
     'began=incident.get("started_at") or incident.get("created_at")', "began=fetched_at.isoformat()"),
    ("status: the oldest update shown as the newest", "worldwatch/collectors/status_pages.py",
     "newest = max(updates,", "newest = min(updates,"),
    ("status: affected parts ignored", "worldwatch/collectors/status_pages.py",
     'parts = [c.get("name") for c in incident.get("components") or [] if isinstance(c, dict)]', "parts = []"),
    ("status: a part loses its service's name (Copilot, not GitHub Copilot)", "worldwatch/collectors/status_pages.py",
     'else f"{product} {part}"', "else part"),
    ("google: an outage read as no impact", "worldwatch/collectors/status_pages.py",
     '"SERVICE_OUTAGE": "major"', '"SERVICE_OUTAGE": "none"'),
    ("alerts: an incident with no impact alerts", "worldwatch/collectors/my_stack.py",
     'OUTAGE_WEIGHT = {"minor": 0.5,', 'OUTAGE_WEIGHT = {"none": 0.1, "minor": 0.5,'),
    ("alerts: every incident alerts, watchlist or not", "worldwatch/collectors/my_stack.py",
     '            if not hit:\n                continue\n            entry, matched = hit\n',
     '            entry, matched = hit or (entries[0].name, "anything")\n'),
    ("alerts: an outage replay sees later incidents", "worldwatch/collectors/my_stack.py",
     "        for row in _rows(store, source, now):", '        for row in store.items_between(source, "", "9999", limit=SCAN_LIMIT):'),
    ("alerts: outages get a cap of their own", "worldwatch/collectors/my_stack.py",
     "out.append(Alert(item, _day(item.happened_at), (0, OUTAGE_WEIGHT", 'out.append(Alert(item, "outages", (0, OUTAGE_WEIGHT'),
    # Away for days: big outages over the cap, the Board's reach, names taken off the list.
    ("alerts: a big outage stays under the cap", "worldwatch/collectors/my_stack.py",
     "            if alert.over_cap:\n", "            if False:\n"),
    ("alerts: a big outage uses up the 5", "worldwatch/collectors/my_stack.py",
     'if data.get("impact") not in BIG_OUTAGES:\n', "if True:\n"),
    ("alerts: a minor outage naming no part reaches a list of parts", "worldwatch/collectors/my_stack.py",
     "if impact not in BIG_OUTAGES or not isinstance(names, list)", "if not isinstance(names, list)"),
    ("alerts: a big outage naming no part misses a list of parts", "worldwatch/collectors/my_stack.py",
     ' or _no_part_hit(entries, data.get("names"), impact)', ""),
    ("alerts: any list hears of a no-part outage, not only that service's", "worldwatch/watchlist.py",
     'term.words.startswith(service.product + " ")', "bool(term.words)"),
    ("alerts: the Board stops short of the 30 days", "worldwatch/collectors/my_stack.py",
     "window=LOOKBACK, limit=PANEL_LIMIT", "window=timedelta(days=14), limit=30"),
    ("alerts: a removed name stays on the Board", "worldwatch/collectors/my_stack.py",
     "store.forget_items(SOURCE, gone + [", "store.forget_items(SOURCE, ["),
    ("alerts: a removed name keeps its day full", "worldwatch/collectors/my_stack.py",
     '                gone.append(row["id"])\n                continue\n', '                gone.append(row["id"])\n'),
    ("alerts: an old +N line stays", "worldwatch/collectors/my_stack.py",
     "[line for line in old_lines if line not in kept]", "[]"),
    ("alerts: a renamed entry loses its alerts", "worldwatch/collectors/my_stack.py",
     'if not problems and row["id"] not in derived and', 'if not problems and'),
    ("alerts: a line it can't use removes alerts", "worldwatch/collectors/my_stack.py",
     'if not problems and row["id"] not in derived', 'if row["id"] not in derived'),
    ("alerts: forgetting reaches other sources' records", "worldwatch/store.py",
     '"DELETE FROM items WHERE id = ? AND source = ?", [(i, source) for i in ids]', '"DELETE FROM items WHERE id = ?", [(i,) for i in ids]'),
    ("alerts: Recon cuts the week short", "worldwatch/recon.py",
     "ALERT_LIMIT = 100", "ALERT_LIMIT = 15"),
    ("alerts: an unreadable list wipes the alerts", "worldwatch/collectors/my_stack.py",
     "    if not entries:\n        log.debug(", "    if False:\n        log.debug("),
    ("wiring: the status pages are not in the run", "worldwatch/collectors/__init__.py",
     "epss.COLLECTOR, *status_pages.COLLECTORS,", "epss.COLLECTOR,"),
    # Board layout: a split kept per browser and always sane, lists that fold, a one-row strip, D-17 intact.
    ("layout: the dragged split is not remembered", "worldwatch/board/static/board.js",
     "if (state.side !== null) remember(SIDE_KEY, String(state.side));", ""),
    ("layout: a stored split is used unchecked", "worldwatch/board/static/board.js",
     "return raw !== null && /^\\d{1,5}$/.test(raw) ? Number(raw) : null;",
     "return raw === null ? null : Number(raw);"),
    ("layout: the split is not clamped (the globe or the lists vanish)", "worldwatch/board/static/board.js",
     "return Math.round(Math.max(SIDE_MIN, Math.min(wanted, room - GLOBE_MIN)));", "return Math.round(wanted);"),
    ("layout: a smaller window keeps a split that no longer fits", "worldwatch/board/static/board.js",
     'window.addEventListener("resize", applySide);', ""),
    ("layout: the map is not redrawn when the divider moves", "worldwatch/board/static/map.js",
     "new ResizeObserver(resize).observe(box);", 'window.addEventListener("resize", resize);'),
    ("layout: the divider ignores the keyboard", "worldwatch/board/static/board.js",
     "const step = { ArrowLeft: KEY_STEP, ArrowRight: -KEY_STEP, Home: Infinity, End: -Infinity }[e.key];",
     "const step = 0;"),
    ("layout: folds are not remembered", "worldwatch/board/static/board.js",
     "remember(FOLD_KEY, JSON.stringify([...state.folded]));", ""),
    ("layout: junk in the stored folds stops the page", "worldwatch/board/static/board.js",
     "    try {\n      const ids = JSON.parse(recall(FOLD_KEY));\n"
     "      return new Set(Array.isArray(ids) ? ids.filter((id) => typeof id === \"string\") : []);\n"
     "    } catch (_) {\n      return new Set();\n    }\n",
     "    return new Set(JSON.parse(recall(FOLD_KEY)) || []);\n"),
    ("layout: a browser that refuses storage gets no Board", "worldwatch/board/static/board.js",
     "    try {\n      return localStorage.getItem(key);\n    } catch (_) {\n      return null;\n    }\n",
     "    return localStorage.getItem(key);\n"),
    ("strip: the sources are names again, spilling over the bar", "worldwatch/board/static/board.js",
     'const dot = el("button", null, "dot " + kind);',
     'const dot = el("button", sourceLine(s), "dot " + kind);\n'
     '      dot.style.width = dot.style.height = "auto";\n      dot.style.whiteSpace = "nowrap";'),
    ("strip: a source's error written as HTML", "worldwatch/board/static/board.js",
     'box.textContent = s ? sourceLine(s) + " · " + sourceDetail(s) : "";',
     'box.innerHTML = s ? sourceLine(s) + " · " + sourceDetail(s) : "";'),
    ("board: the CSP lets inline styles in", "worldwatch/board/server.py",
     "style-src 'self'; img-src", "style-src 'self' 'unsafe-inline'; img-src"),
    # Task 4 — hazards and Mexico (D-22): the time, the id, the box, the caps, one alert per quake.
    ("ssn: Mexico time read as UTC", "worldwatch/collectors/ssn.py",
     'MEXICO_TIME = timezone(timedelta(hours=-6), "CDMX")', "MEXICO_TIME = timezone.utc"),
    ("ssn: an XML bomb's DTD is parsed", "worldwatch/collectors/__init__.py",  # the guard SSN shares
     'if "<!DOCTYPE" in upper or "<!ENTITY" in upper:', "if False:"),
    ("ssn: another encoding hides the bomb from the check", "worldwatch/collectors/__init__.py",
     'raise ParseError(f"{source}: only UTF-8 XML is read")', "pass"),
    ("ssn: the feed's raw spaces kill the link", "worldwatch/collectors/ssn.py",
     'url=quote(link, safe=":/?&=%#") if link else None', "url=link or None"),
    ("ssn: a revised magnitude is a new quake", "worldwatch/collectors/ssn.py",
     'native_id=happened.astimezone(timezone.utc).strftime("%Y-%m-%dT%H:%M:%SZ"),', "native_id=title,"),
    ("firms: the whole region kept, not the Mexico box", "worldwatch/collectors/firms.py",
     'parse_records = partial(_records, keep=usgs.near_mexico, build=_build)',
     'parse_records = partial(_records, keep=lambda lat, lon: True, build=_build)'),
    ("firms: one oversized field crashes the batch", "worldwatch/collectors/firms.py",
     "except csv.Error as err:", "except ValueError as err:"),
    ("smn: a gzip bomb unpacks without a cap", "worldwatch/collectors/smn.py",
     "if len(text) > MAX_UNPACKED:", "if False:"),
    ("near-cdmx: one quake from two sources is two alerts", "worldwatch/collectors/near_cdmx.py",
     "limit_s, limit_km = (SAME_SECONDS, SAME_KM) if a.source == b.source else (QUAKE_SECONDS, QUAKE_KM)",
     "limit_s, limit_km = (SAME_SECONDS, SAME_KM) if a.source == b.source else (-1, QUAKE_KM)"),
    ("near-cdmx: a re-timed report from one source is a second quake", "worldwatch/collectors/near_cdmx.py",
     "limit_s, limit_km = (SAME_SECONDS, SAME_KM) if a.source == b.source else (QUAKE_SECONDS, QUAKE_KM)",
     "limit_s, limit_km = (-1, SAME_KM) if a.source == b.source else (QUAKE_SECONDS, QUAKE_KM)"),
    ("near-cdmx: the alert's id follows the source order, not the first stored", "worldwatch/collectors/near_cdmx.py",
     'order = sorted(reports, key=lambda r: (r.row["fetched_at"], QUAKE_SOURCES.index(r.source), r.row["id"]))',
     'order = sorted(reports, key=lambda r: (QUAKE_SOURCES.index(r.source), r.row["id"]))'),
    ("near-cdmx: grouped after the rule, so a revised magnitude moves the alert", "worldwatch/collectors/near_cdmx.py",
     'if cdmx.km_from_cdmx(row["lat"], row["lon"]) <= REACH_KM:',
     'if cdmx.near_cdmx(usgs.magnitude(row), row["lat"], row["lon"]):'),
    ("near-cdmx: an alert revised below the rule stays", "worldwatch/collectors/near_cdmx.py",
     "store.forget_items(SOURCE, [", "(lambda *a: None)(SOURCE, ["),
    ("near-cdmx: in a burst a report joins the first quake, not the closest", "worldwatch/collectors/near_cdmx.py",
     "if gaps and (best_gap is None or min(gaps) < best_gap):", "if gaps and best_gap is None:"),
    ("near-cdmx: a big far quake never alerts", "worldwatch/collectors/cdmx.py",
     "NEAR_RULES = ((150.0, 2.5), (400.0, 5.0), (700.0, 6.0), (1200.0, 7.0))", "NEAR_RULES = ((150.0, 2.5),)"),
    # The flat map (Trevor, 2026-11-09): the right pins in the right place, fires readable, safe text, the globe on demand.
    ("map: quakes from M4 get a pin", "worldwatch/board/static/pins.js",
     "const PIN_MAG = 5;", "const PIN_MAG = 4;"),
    ("map: a Green GDACS alert gets a pin", "worldwatch/board/static/pins.js",
     'pin: lvl === "orange" || lvl === "red"', "pin: lvl !== null"),
    ("map: fires never merge", "worldwatch/board/static/pins.js",
     'return layerId === "fires" || layerId === "heat-mideast";', "return false;"),
    ("map: two or three fires merge too", "worldwatch/board/static/pins.js",
     "const CLUSTER_MIN = 4;", "const CLUSTER_MIN = 2;"),
    ("map: the CDMX rings are not true distances", "worldwatch/board/static/pins.js",
     "const d = km / R;", "const d = km / 6000;"),
    ("map: fires stay merged at close range", "worldwatch/board/static/map.js",
     "const merge = v.s < minScale() * SPLIT_ZOOM;", "const merge = true;"),
    ("map: latitude drawn upside down", "worldwatch/board/static/map.js",
     "const toY = (lat) => v.oy + (90 - lat) * v.s;", "const toY = (lat) => v.oy + (lat + 90) * v.s;"),
    ("map: impossible positions drawn", "worldwatch/board/static/map.js",
     "return Number.isFinite(p.lat) && Number.isFinite(p.lon) && Math.abs(p.lat) <= 90 && Math.abs(p.lon) <= 180;",
     "return true;"),
    ("map: zooming out goes past the whole world", "worldwatch/board/static/map.js",
     "v.s = Math.min(Math.max(v.s, minScale()), minScale() * MAX_ZOOM);", "v.s = Math.min(v.s, minScale() * MAX_ZOOM);"),
    ("map: zoom ignores where the pointer is", "worldwatch/board/static/map.js",
     "      v.ox = x - (lon + 180) * v.s;\n      v.oy = y - (90 - lat) * v.s;\n", ""),
    ("map: a drag counts as a click", "worldwatch/board/static/map.js",
     'const wasClick = !drag.moved && e.type === "pointerup";', 'const wasClick = e.type === "pointerup";'),
    ("map: the hover tip written as HTML", "worldwatch/board/static/map.js",
     "tip.textContent = tipText(m);", "tip.innerHTML = tipText(m);"),
    ("map: CDMX never shows its alert", "worldwatch/board/static/board.js",
     "if (state.map) state.map.setAlerts(alertAt >= 0 ? panelBodies[alertAt].entries : []);",
     "if (state.map) state.map.setAlerts([]);"),
    ("map: a layer switched off stays on the map", "worldwatch/board/static/board.js",
     "const shown = state.layers.filter((layer) => state.shown[layer.id] !== false)",
     "const shown = state.layers.filter((layer) => layer)"),
    ("map: the globe's 1.9 MB loads with every page", "worldwatch/board/static/board.html",
     '<script src="/static/map.js" defer></script>',
     '<script src="/static/globe.gl.min.js" defer></script>\n<script src="/static/map.js" defer></script>'),
    ("map: failed first loads stack retry timers", "worldwatch/board/static/board.js",
     "if (!state.loaded && !state.retry) {", "if (!state.loaded) {"),
    ("map: a failed first load waits ten minutes", "worldwatch/board/static/board.js",
     "const FIRST_RETRY_MS = 3 * 1000;", "const FIRST_RETRY_MS = 600 * 1000;"),
    ("map: a scaling change keeps the old canvas size", "worldwatch/board/static/map.js",
     "if ((window.devicePixelRatio || 1) !== v.dpr) {", "if (false) {"),
    # The Middle East watch (Trevor, 2026-11-09): one narrow frame exception (D-24), nothing plays before a click,
    # only listed YouTube streams become frames, heat is never a strike.
    ("mideast: the player pages may frame any https site", "worldwatch/board/server.py",
     'CSP.replace("connect-src \'self\'; ", f"connect-src \'self\'; frame-src {PLAYER_ORIGIN}; ")',
     'CSP.replace("connect-src \'self\'; ", "connect-src \'self\'; frame-src https:; ")'),
    ("mideast: every file served may frame YouTube", "worldwatch/board/server.py",
     "return 200, file.read_bytes(), kind, CSP", "return 200, file.read_bytes(), kind, PLAYER_CSP"),
    ("mideast: the player may navigate the Board", "worldwatch/board/static/player.js",
     'const SANDBOX = "allow-scripts allow-same-origin allow-presentation allow-popups allow-popups-to-escape-sandbox";',
     'const SANDBOX = "allow-scripts allow-same-origin allow-presentation allow-popups allow-popups-to-escape-sandbox allow-top-navigation";'),
    ("mideast: YouTube is sent the full page address", "worldwatch/board/static/player.js",
     'f.referrerPolicy = "strict-origin";', 'f.referrerPolicy = "unsafe-url";'),
    ("mideast: the player is not privacy-enhanced", "worldwatch/board/static/player.js",
     'const ORIGIN = "https://www.youtube-nocookie.com";', 'const ORIGIN = "https://www.youtube.com";'),
    ("mideast: a link with extra text becomes a frame", "worldwatch/board/static/player.js",
     r"const VIDEO = /^https:\/\/www\.youtube\.com\/watch\?v=([A-Za-z0-9_-]{11})$/;",
     r"const VIDEO = /^https:\/\/www\.youtube\.com\/watch\?v=([A-Za-z0-9_-]{11})/;"),
    ("mideast: the viewer plays before a click", "worldwatch/board/static/viewer.js",
     "const v = { entries: [], current: recall(), playing: false, shownId: null };",
     "const v = { entries: [], current: recall(), playing: true, shownId: null };"),
    ("mideast: a refresh reloads the playing stream", "worldwatch/board/static/viewer.js",
     "if (v.shownId === e.id) return;", "if (false) return;"),
    ("mideast: every console tile autoplays", "worldwatch/board/static/live.js",
     "play(t, id, n === 0);", "play(t, id, true);"),
    ("mideast: the streams shown again as lists", "worldwatch/board/static/board.js",
     "const lists = paired.filter(([p]) => !LIVE_PANELS.includes(p.id));", "const lists = paired;"),
    ("mideast: an oEmbed answer for another video accepted", "worldwatch/collectors/live_streams.py",
     "stream = next((s for s in cams if found and s.video == found.group(1)), None)",
     "stream = next((s for s in cams), None)"),
    ("mideast: one cam gone fails every cam", "worldwatch/collectors/live_streams.py",
     "    follow_optional=True,  # one cam gone", "    follow_optional=False,  # one cam gone"),
    ("mideast: a listed news channel called checked", "worldwatch/collectors/live_streams.py",
     'note=NOT_CHECKED, basis="inferred")', 'note=NOT_CHECKED, basis="reported")'),
    ("mideast: Sudan's fires counted as Middle East heat", "worldwatch/collectors/firms.py",
     "        return 42.5 <= lon <= 60.0", "        return 25.0 <= lon <= 60.0"),
    ("mideast: heat titled a strike", "worldwatch/collectors/firms.py",
     'build=partial(_build, source=MIDEAST_SOURCE, word="Heat", note=HEAT_NOTE))',
     'build=partial(_build, source=MIDEAST_SOURCE, word="Strike", note=HEAT_NOTE))'),
]


def run_one(name: str, rel: str, old: str, new: str) -> bool:
    with tempfile.TemporaryDirectory(prefix="ww-mutant-") as tmp:
        work = Path(tmp)
        shutil.copytree(ROOT / "worldwatch", work / "worldwatch")
        shutil.copytree(ROOT / "tests", work / "tests")
        shutil.copy2(ROOT / "watchlist.example.txt", work / "watchlist.example.txt")  # a test reads it
        if not rel:  # the baseline: the untouched copy must pass, or "caught" means nothing
            return _suite_fails(work)
        target = work / rel
        text = target.read_text(encoding="utf-8")
        if text.count(old) != 1:
            print(f"  BROKEN MUTANT  {name}: pattern found {text.count(old)} times")
            return False
        target.write_text(text.replace(old, new), encoding="utf-8")
        caught = _suite_fails(work)
        print(f"  {'caught ' if caught else 'MISSED '}  {name}")
        return caught


def _suite_fails(work: Path) -> bool:
    try:
        result = subprocess.run([sys.executable, "-m", "unittest", "discover", "-s", "tests", "-t", "."],
                                cwd=work, capture_output=True, text=True, timeout=600)
    except subprocess.TimeoutExpired:
        return True  # a hung suite is a failing one
    return result.returncode != 0


def main() -> int:
    if run_one("baseline", "", "", ""):
        print("  the untouched copy fails its own tests: fix that before trusting any mutant")
        return 1
    only = sys.argv[1:]
    results = [run_one(*m) for m in MUTANTS if not only or any(word in m[0] for word in only)]
    print(f"{sum(results)}/{len(results)} mutants caught")
    return 0 if all(results) else 1


if __name__ == "__main__":
    sys.exit(main())
