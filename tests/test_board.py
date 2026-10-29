"""The Board (D-17): a local, read-only page on 127.0.0.1. Each safety rule has a test here.

A real server runs on a free port for each test class; requests go through http.client so the
Host header (and the method) can be anything a hostile page could send.
"""

import hashlib
import http.client
import json
import re
import socket
import sqlite3
import threading
import unittest
from datetime import timedelta
from pathlib import Path

from tests.helpers import NOW, fixture, sample_item, temp_dir
from worldwatch.board import server as board
from worldwatch.collectors import Collector, cisa_kev, usgs
from worldwatch.item import iso_utc
from worldwatch.store import Store
from worldwatch.views import Layer, Panel

STATIC = Path(board.__file__).parent / "static"
REAL_STORE = Path(__file__).resolve().parent.parent / "data" / "worldwatch.sqlite3"
HOSTILE = '<img src=x onerror="alert(1)"><script>alert(2)</script>'


def start(db_path: Path, collectors, recon_dir: Path | None = None, now=NOW):
    srv = board.make_server(db_path, collectors, recon_dir or db_path.parent / "recon", port=0, now=lambda: now)
    thread = threading.Thread(target=srv.serve_forever, daemon=True)
    thread.start()
    return srv


def request(srv, path, *, method="GET", host=None, body=None):
    conn = http.client.HTTPConnection("127.0.0.1", srv.server_port, timeout=10)
    conn.putrequest(method, path, skip_host=True, skip_accept_encoding=True)
    conn.putheader("Host", host if host is not None else f"127.0.0.1:{srv.server_port}")
    if body is not None:
        conn.putheader("Content-Length", str(len(body)))
    conn.endheaders(body)
    resp = conn.getresponse()
    data = resp.read()
    conn.close()
    return resp, data


def get_json(srv, path):
    resp, data = request(srv, path)
    assert resp.status == 200, (path, resp.status, data[:200])
    return json.loads(data)


def raw_insert(db_path: Path, **over):
    """Write a row straight into SQLite, past make_item's checks: what a bug or an old row could leave."""
    row = dict(id="raw-1", channel="security", source="cisa-kev", happened_at=iso_utc(NOW), fetched_at=iso_utc(NOW),
               title="raw", url=None, summary="", lat=None, lon=None, country=None, severity=None,
               licence="t", basis="reported", lang="en", raw="{}", updated_at=iso_utc(NOW))
    row.update(over)
    db = sqlite3.connect(db_path)
    with db:
        db.execute(f"INSERT INTO items ({', '.join(row)}) VALUES ({', '.join('?' for _ in row)})", list(row.values()))
    db.close()


def real_feed_store() -> Path:
    """A store filled by the real collectors from saved real responses (USGS week feed, KEV catalogue)."""
    path = temp_dir() / "worldwatch.sqlite3"
    store = Store(path)
    store.save_items(usgs.COLLECTOR.parse(fixture("usgs_2.5_week.geojson"), NOW))
    store.save_items(cisa_kev.COLLECTOR.parse(fixture("cisa_kev.json"), NOW))
    store.record_run("usgs-quakes", NOW, NOW, ok=True, n_items=1, error=None, next_due=iso_utc(NOW), fail_count=0)
    store.close()
    return path


COLLECTORS = [usgs.COLLECTOR, cisa_kev.COLLECTOR]


class BoardCase(unittest.TestCase):
    collectors = COLLECTORS

    @classmethod
    def setUpClass(cls):
        cls.db_path = real_feed_store()
        cls.srv = start(cls.db_path, cls.collectors)

    @classmethod
    def tearDownClass(cls):
        cls.srv.shutdown()
        cls.srv.server_close()


class Binding(BoardCase):
    def test_listens_on_loopback_only(self):
        self.assertEqual(self.srv.server_address[0], "127.0.0.1")

    def test_refuses_any_other_address(self):
        for host in ("0.0.0.0", "", "192.168.1.10", "::", "localhost"):
            with self.assertRaises(ValueError, msg=host):
                board.make_server(self.db_path, COLLECTORS, self.db_path.parent, host=host, port=0)

    def test_default_port_is_the_reserved_one(self):
        self.assertEqual(board.BOARD_PORT, 8420)

    def test_a_taken_port_is_never_shared(self):
        other = socket.socket()
        other.setsockopt(socket.SOL_SOCKET, socket.SO_REUSEADDR, 1)  # what most dev servers set
        other.bind(("127.0.0.1", 0))
        other.listen()
        try:
            with self.assertRaises(OSError):
                board.make_server(self.db_path, COLLECTORS, self.db_path.parent, port=other.getsockname()[1])
        finally:
            other.close()

    def test_nothing_can_bind_on_top_of_the_board(self):
        intruder = socket.socket()
        intruder.setsockopt(socket.SOL_SOCKET, socket.SO_REUSEADDR, 1)
        try:
            with self.assertRaises(OSError):
                intruder.bind(("127.0.0.1", self.srv.server_port))
        finally:
            intruder.close()

    def test_idle_connections_time_out(self):
        self.assertTrue(board.Handler.timeout and board.Handler.timeout <= 30)

    def test_the_sources_in_the_run_register_cleanly(self):
        from worldwatch.board.data import Registry
        from worldwatch.collectors import all_collectors
        registry = Registry(all_collectors())
        self.assertEqual(set(registry.layers), {"quakes"})
        self.assertEqual(set(registry.panels), {"kev", "nvd", "osv", "epss", "my-stack", "github-status", "cloudflare-status",
                                                "claude-status", "google-workspace-status"})


class HostHeader(BoardCase):
    """DNS rebinding: a hostile site's name pointed at 127.0.0.1 still sends its own name as Host."""

    def test_foreign_host_refused_on_every_route(self):
        port = self.srv.server_port
        for host in ("evil.example", f"evil.example:{port}", f"127.0.0.1.evil.example:{port}",
                     f"localhost.evil.example:{port}", f"127.0.0.1:{port + 1}", "127.0.0.1", ""):
            for path in ("/", "/api/board", "/api/layers/quakes", "/static/board.js"):
                resp, data = request(self.srv, path, host=host)
                self.assertEqual(resp.status, 421, (host, path))
                self.assertNotIn(b"M ", data)

    def test_missing_host_refused(self):
        with socket.create_connection(("127.0.0.1", self.srv.server_port), timeout=10) as sock:
            sock.sendall(b"GET /api/board HTTP/1.0\r\n\r\n")
            reply = sock.recv(200)
        self.assertTrue(reply.startswith(b"HTTP/1.0 421"), reply)

    def test_own_names_accepted(self):
        port = self.srv.server_port
        for host in (f"127.0.0.1:{port}", f"localhost:{port}", f"LOCALHOST:{port}"):
            resp, _ = request(self.srv, "/api/board", host=host)
            self.assertEqual(resp.status, 200, host)


class Csp(BoardCase):
    def csp(self, path):
        resp, _ = request(self.srv, path)
        return resp.getheader("Content-Security-Policy") or ""

    def test_every_response_carries_the_strict_policy(self):
        for path in ("/", "/api/board", "/static/board.js", "/nope", "/api/layers/nope"):
            policy = self.csp(path)
            directives = dict((d.split()[0], d.split()[1:]) for d in policy.split(";") if d.strip())
            self.assertEqual(directives.get("default-src"), ["'none'"], path)
            self.assertEqual(directives.get("script-src"), ["'self'"], path)
            self.assertNotIn("unsafe-inline", policy)
            self.assertNotIn("unsafe-eval", policy)
            self.assertNotRegex(policy, r"nonce-|sha\d+-|https?:|\*|data:")
            self.assertEqual(directives.get("frame-ancestors"), ["'none'"], path)

    def test_page_has_no_inline_script_or_handlers(self):
        html = (STATIC / "board.html").read_text(encoding="utf-8")
        scripts = re.findall(r"<script\b([^>]*)>(.*?)</script>", html, re.S | re.I)
        self.assertTrue(scripts)
        for attrs, body in scripts:
            self.assertRegex(attrs, r'src="/static/[\w.-]+"')
            self.assertEqual(body.strip(), "")
        self.assertNotRegex(html, r"(?i)\son\w+\s*=|\sstyle\s*=|javascript:")

    def test_http_servers_own_errors_carry_the_policy_too(self):
        for raw in (b"BREW / HTTP/1.0\r\n\r\n", b"GET /" + b"a" * 70000 + b" HTTP/1.0\r\n\r\n"):
            with socket.create_connection(("127.0.0.1", self.srv.server_port), timeout=10) as sock:
                sock.sendall(raw)
                reply = b""
                while chunk := sock.recv(4096):
                    reply += chunk
            head = reply.split(b"\r\n\r\n", 1)[0].decode("latin-1")
            self.assertRegex(head, r"^HTTP/1\.[01] (400|414|501)", raw[:20])
            self.assertIn(f"Content-Security-Policy: {board.CSP}", head)
            self.assertIn("X-Content-Type-Options: nosniff", head)
            self.assertIn("Content-Type: text/plain", head)

    def test_only_pinned_files_are_cached(self):
        for path in ("/static/globe.gl.min.js", "/static/earth.jpg"):
            self.assertIn("immutable", request(self.srv, path)[0].getheader("Cache-Control"), path)
        for path in ("/", "/static/board.js", "/api/board", "/nope"):
            self.assertEqual(request(self.srv, path)[0].getheader("Cache-Control"), "no-store", path)

    def test_other_safety_headers(self):
        resp, _ = request(self.srv, "/")
        self.assertEqual(resp.getheader("X-Content-Type-Options"), "nosniff")
        self.assertEqual(resp.getheader("Referrer-Policy"), "no-referrer")
        self.assertEqual(resp.getheader("Cross-Origin-Resource-Policy"), "same-origin")


class NoOutsideRequests(BoardCase):
    def test_page_files_name_no_other_host(self):
        for name in ("board.html", "board.js", "board.css"):
            text = (STATIC / name).read_text(encoding="utf-8")
            self.assertIsNone(re.search(r"(?i)\b(https?:)?//[a-z0-9]", text), name)
            if name != "board.js":  # in CSS, url() and @import may name only this server's own files
                self.assertIsNone(re.search(r"(?i)@import|url\(\s*['\"]?(?!/static/)", text), name)

    def test_policy_lets_the_page_reach_only_itself(self):
        resp, _ = request(self.srv, "/")
        policy = resp.getheader("Content-Security-Policy")
        for directive in ("connect-src", "img-src", "style-src", "font-src"):
            match = re.search(rf"{directive} ([^;]+)", policy)
            if match:
                self.assertEqual(match.group(1).strip(), "'self'", directive)

    def test_vendored_files_match_their_pinned_checksums(self):
        manifest = json.loads((STATIC / "vendor" / "MANIFEST.json").read_text(encoding="utf-8"))
        files = {p.name for p in (STATIC / "vendor").iterdir() if p.name not in ("MANIFEST.json", "README.md")}
        self.assertEqual(files, set(manifest), "every vendored file is pinned, nothing unpinned")
        for name, entry in manifest.items():
            digest = hashlib.sha256((STATIC / "vendor" / name).read_bytes()).hexdigest()
            self.assertEqual(digest, entry["sha256"], name)
            self.assertTrue(entry["version"] and entry["source"] and entry["licence"], name)


class TextNotHtml(unittest.TestCase):
    """Source text is data: JSON with nosniff, and the page only ever sets textContent."""

    @classmethod
    def setUpClass(cls):
        cls.db_path = temp_dir() / "worldwatch.sqlite3"
        Store(cls.db_path).close()
        # Straight into SQLite: make_item would strip the tags, and the Board must not rely on that.
        raw_insert(cls.db_path, id="h-1", source="usgs-quakes", channel="hazards", title=HOSTILE, summary=HOSTILE,
                   severity="M5.0", lat=19.4, lon=-99.1, url="https://example.org/q")
        raw_insert(cls.db_path, id="h-2", title=HOSTILE, summary=HOSTILE, url="https://example.org/k")
        raw_insert(cls.db_path, id="js-1", url="javascript:alert(1)", happened_at=iso_utc(NOW - timedelta(hours=1)))
        raw_insert(cls.db_path, id="js-2", url=" JaVaScRiPt:alert(1)", happened_at=iso_utc(NOW - timedelta(hours=2)))
        raw_insert(cls.db_path, id="js-3", url="data:text/html,<script>alert(1)</script>",
                   happened_at=iso_utc(NOW - timedelta(hours=3)))
        raw_insert(cls.db_path, id="js-4", source="usgs-quakes", channel="hazards", url="javascript:alert(1)",
                   lat=1.0, lon=2.0, severity="M4.9")
        raw_insert(cls.db_path, id="bad-lat", source="usgs-quakes", channel="hazards", lat=95.0, lon=2.0)
        raw_insert(cls.db_path, id="bad-lon", source="usgs-quakes", channel="hazards", lat=1.0, lon=-181.0)
        cls.srv = start(cls.db_path, COLLECTORS)

    @classmethod
    def tearDownClass(cls):
        cls.srv.shutdown()
        cls.srv.server_close()

    def test_hostile_title_is_sent_as_json_text(self):
        resp, data = request(self.srv, "/api/panels/kev")
        self.assertEqual(resp.getheader("Content-Type"), "application/json; charset=utf-8")
        self.assertEqual(resp.getheader("X-Content-Type-Options"), "nosniff")
        self.assertNotIn(b"<script>", data)  # escaped inside the JSON string as <
        for raw in (b"<", b">", b"&"):  # none of them, anywhere in the response
            self.assertNotIn(raw, data)
        titles = [e["title"] for e in json.loads(data)["entries"]]
        self.assertIn(HOSTILE, titles)

    def test_page_script_never_writes_html(self):
        js = (STATIC / "board.js").read_text(encoding="utf-8")
        self.assertNotRegex(js, r"innerHTML|outerHTML|insertAdjacentHTML|document\.write|\beval\(|new Function|"
                                r"setAttribute\(\s*['\"](on|style|href)")
        self.assertIn(".pointLabel(null)", js, "globe.gl renders a point label as HTML: it must stay off")
        self.assertEqual(js.count("Label("), 1, "no other label accessor")
        self.assertIsNone(re.search(r"htmlElement|labelsData|Label\s*:", js), "no globe.gl HTML layers")

    def test_javascript_and_data_links_never_reach_the_page(self):
        for path in ("/api/panels/kev", "/api/layers/quakes"):
            body = get_json(self.srv, path)
            rows = body.get("entries") or body.get("points")
            self.assertTrue(rows)
            for row in rows:
                self.assertTrue(row["url"] is None or re.match(r"https?://", row["url"]), row["url"])
        self.assertNotRegex(json.dumps(get_json(self.srv, "/api/panels/kev")), r"(?i)javascript:|data:text")

    def test_impossible_positions_stay_off_the_globe(self):
        ids = {p["id"] for p in get_json(self.srv, "/api/layers/quakes")["points"]}
        self.assertIn("js-4", ids)
        self.assertNotIn("bad-lat", ids)
        self.assertNotIn("bad-lon", ids)

    def test_page_rechecks_links_before_using_them(self):
        js = (STATIC / "board.js").read_text(encoding="utf-8")
        self.assertEqual(len(re.findall(r"\.href\s*=", js)), 1, "one place sets a link")
        self.assertIsNotNone(re.search(r"\.href\s*=\s*safe", js))


class ReadOnly(BoardCase):
    def snapshot(self):
        db = sqlite3.connect(self.db_path)
        rows = db.execute("SELECT * FROM items ORDER BY id").fetchall() + db.execute("SELECT * FROM runs").fetchall()
        db.close()
        return rows

    def test_no_route_accepts_a_write(self):
        before = self.snapshot()
        for method in ("POST", "PUT", "DELETE", "PATCH"):
            for path in ("/", "/api/board", "/api/layers/quakes", "/api/panels/kev", "/static/board.js", "/recon"):
                resp, _ = request(self.srv, path, method=method, body=b'{"title": "x"}')
                self.assertEqual(resp.status, 405, (method, path))
                self.assertEqual(resp.getheader("Allow"), "GET, HEAD")
        self.assertEqual(self.snapshot(), before)

    def test_the_board_connection_cannot_write(self):
        store = Store.open_readonly(self.db_path)
        try:
            with self.assertRaises(sqlite3.OperationalError):
                store.db.execute("DELETE FROM items")
        finally:
            store.close()

    def test_head_answers_without_a_body(self):
        resp, data = request(self.srv, "/api/board", method="HEAD")
        self.assertEqual(resp.status, 200)
        self.assertEqual(data, b"")


class StaticFiles(BoardCase):
    def test_only_listed_files_are_served(self):
        for path in ("/static/../store.py", "/static/%2e%2e/store.py", "/static/..%5cstore.py", "/static/",
                     "/static/vendor/MANIFEST.json", "/worldwatch.sqlite3", "/static/nope.js", "//evil.example/"):
            resp, _ = request(self.srv, path)
            self.assertEqual(resp.status, 404, path)

    def test_page_and_its_files_are_served_with_their_types(self):
        for path, kind in (("/", "text/html"), ("/static/board.js", "text/javascript"),
                           ("/static/board.css", "text/css"), ("/static/globe.gl.min.js", "text/javascript"),
                           ("/static/earth.jpg", "image/jpeg")):
            resp, data = request(self.srv, path)
            self.assertEqual(resp.status, 200, path)
            self.assertTrue(resp.getheader("Content-Type").startswith(kind), path)
            self.assertTrue(data)


class FromTheStore(BoardCase):
    def test_board_lists_what_the_sources_registered(self):
        body = get_json(self.srv, "/api/board")
        self.assertEqual([(lay["id"], lay["source"]) for lay in body["layers"]], [("quakes", "usgs-quakes")])
        self.assertEqual([(p["id"], p["source"]) for p in body["panels"]], [("kev", "cisa-kev")])
        self.assertEqual(body["panels"][0]["date_only"], True)

    def test_quake_layer_is_the_stored_week_with_positions(self):
        start_iso = iso_utc(NOW - timedelta(days=7))
        db = sqlite3.connect(self.db_path)
        expected = db.execute("SELECT id FROM items WHERE source='usgs-quakes' AND lat IS NOT NULL AND lon IS NOT NULL "
                              "AND happened_at >= ? ORDER BY happened_at DESC, id", (start_iso,)).fetchall()
        db.close()
        points = get_json(self.srv, "/api/layers/quakes")["points"]
        self.assertGreater(len(points), 10)
        self.assertEqual([p["id"] for p in points], [r[0] for r in expected])
        for p in points:
            self.assertTrue(-90 <= p["lat"] <= 90 and -180 <= p["lon"] <= 180)
            self.assertTrue(0 <= p["weight"] <= 1)
            for key in ("source", "happened_at", "fetched_at", "title"):  # D-8: source and both times, always
                self.assertTrue(p[key], key)

    def test_bigger_quakes_weigh_more(self):
        points = get_json(self.srv, "/api/layers/quakes")["points"]
        by_mag = sorted(points, key=lambda p: usgs.magnitude(p) or 0)
        self.assertLessEqual(by_mag[0]["weight"], by_mag[-1]["weight"])
        self.assertLess(by_mag[0]["weight"], by_mag[-1]["weight"])

    def test_kev_panel_is_newest_first_within_its_window_and_limit(self):
        entries = get_json(self.srv, "/api/panels/kev")["entries"]
        self.assertTrue(0 < len(entries) <= cisa_kev.COLLECTOR.panel.limit)
        days = [e["happened_at"] for e in entries]
        self.assertEqual(days, sorted(days, reverse=True))
        self.assertGreaterEqual(min(days), iso_utc(NOW - cisa_kev.COLLECTOR.panel.window))
        for e in entries:
            self.assertEqual(e["source"], "cisa-kev")
            self.assertTrue(e["fetched_at"])

    def test_freshness_per_source(self):
        sources = {s["source"]: s for s in get_json(self.srv, "/api/board")["sources"]}
        self.assertEqual(set(sources), {"usgs-quakes", "cisa-kev"})
        self.assertEqual(sources["usgs-quakes"]["last_ok_at"], iso_utc(NOW))
        self.assertFalse(sources["usgs-quakes"]["stale"])
        self.assertIsNone(sources["cisa-kev"]["last_ok_at"])  # never recorded a run here
        self.assertTrue(sources["cisa-kev"]["stale"])
        self.assertTrue(sources["usgs-quakes"]["credit"])

    def test_unknown_layer_or_panel_is_404(self):
        for path in ("/api/layers/kev", "/api/panels/quakes", "/api/layers/", "/api/layers/quakes/x"):
            resp, _ = request(self.srv, path)
            self.assertEqual(resp.status, 404, path)


class NewSourceTouchesNoBoardCode(unittest.TestCase):
    def test_a_registered_layer_and_panel_show_up(self):
        path = temp_dir() / "worldwatch.sqlite3"
        store = Store(path)
        store.save_items([sample_item(n, source="volcanoes", channel="hazards", lat=19.0, lon=-98.6)
                          for n in range(3)])
        store.close()
        volcanoes = Collector(source="volcanoes", channel="hazards", url="https://example.org/v", interval_s=3600,
                              licence="t", parse_records=lambda d, f: [],
                              layer=Layer("volcanoes", "Volcanoes", "Volcanes", timedelta(days=1), 10),
                              panel=Panel("volcano-list", "Volcanoes", "Volcanes", timedelta(days=1), 2))
        srv = start(path, [*COLLECTORS, volcanoes])
        try:
            body = get_json(srv, "/api/board")
            self.assertIn("volcanoes", [lay["id"] for lay in body["layers"]])
            self.assertEqual(len(get_json(srv, "/api/layers/volcanoes")["points"]), 3)
            self.assertEqual(len(get_json(srv, "/api/panels/volcano-list")["entries"]), 2)
        finally:
            srv.shutdown()
            srv.server_close()

    def test_a_layer_fills_its_limit_past_items_without_a_position(self):
        path = temp_dir() / "worldwatch.sqlite3"
        store = Store(path)
        store.save_items([sample_item(n, source="mixed", happened_at=NOW - timedelta(minutes=n)) for n in range(5)])
        store.save_items([sample_item(n, source="mixed", lat=1.0, lon=2.0, happened_at=NOW - timedelta(hours=n))
                          for n in range(10, 13)])
        store.close()
        mixed = Collector(source="mixed", channel="x", url="https://example.org/m", interval_s=60, licence="t",
                          parse_records=lambda d, f: [], layer=Layer("mixed", "a", "b", timedelta(days=1), 3))
        srv = start(path, [mixed])
        try:
            self.assertEqual(len(get_json(srv, "/api/layers/mixed")["points"]), 3)
        finally:
            srv.shutdown()
            srv.server_close()

    def test_duplicate_ids_are_refused_at_start(self):
        twin = Collector(source="twin", channel="x", url="https://example.org/t", interval_s=60, licence="t",
                         parse_records=lambda d, f: [], layer=Layer("quakes", "a", "b", timedelta(days=1), 1))
        with self.assertRaises(ValueError):
            board.make_server(temp_dir() / "x.sqlite3", [*COLLECTORS, twin], temp_dir(), port=0)

    def test_ids_must_be_url_safe(self):
        odd = Collector(source="odd", channel="x", url="https://example.org/o", interval_s=60, licence="t",
                        parse_records=lambda d, f: [], panel=Panel("../x", "a", "b", timedelta(days=1), 1))
        with self.assertRaises(ValueError):
            board.make_server(temp_dir() / "x.sqlite3", [odd], temp_dir(), port=0)


class MissingStoreAndRecon(unittest.TestCase):
    def test_page_loads_and_api_says_unavailable_before_the_first_fetch(self):
        base = temp_dir()
        srv = start(base / "worldwatch.sqlite3", COLLECTORS, base / "recon")
        try:
            self.assertEqual(request(srv, "/")[0].status, 200)
            self.assertEqual(request(srv, "/api/board")[0].status, 503)
            self.assertEqual(request(srv, "/recon")[0].status, 404)
        finally:
            srv.shutdown()
            srv.server_close()

    def test_recon_is_served_with_its_own_policy(self):
        base = temp_dir()
        (base / "recon").mkdir()
        (base / "recon" / "recon-latest.html").write_text("<p>recon</p>", encoding="utf-8")
        srv = start(base / "worldwatch.sqlite3", COLLECTORS, base / "recon")
        try:
            resp, data = request(srv, "/recon")
            self.assertEqual((resp.status, data), (200, b"<p>recon</p>"))
            from worldwatch.recon_html import CSP
            self.assertEqual(resp.getheader("Content-Security-Policy"), CSP)
        finally:
            srv.shutdown()
            srv.server_close()


@unittest.skipUnless(REAL_STORE.exists(), "no real store on this machine")
class RealStore(unittest.TestCase):
    """The Board against a copy of the real store (SQLite's backup: consistent while the collector writes)."""

    @classmethod
    def setUpClass(cls):
        cls.db_path = temp_dir() / "worldwatch.sqlite3"
        src = sqlite3.connect(f"{REAL_STORE.resolve().as_uri()}?mode=ro", uri=True)
        dst = sqlite3.connect(cls.db_path)
        src.backup(dst)
        src.close()
        dst.close()
        from datetime import datetime, timezone
        cls.now = datetime.now(timezone.utc)
        cls.srv = start(cls.db_path, COLLECTORS, now=cls.now)

    @classmethod
    def tearDownClass(cls):
        cls.srv.shutdown()
        cls.srv.server_close()

    def count(self, sql, *args):
        db = sqlite3.connect(self.db_path)
        n = db.execute(sql, args).fetchone()[0]
        db.close()
        return n

    def test_every_stored_quake_of_the_week_is_on_the_globe(self):
        start_iso = iso_utc(self.now - timedelta(days=7))
        expected = self.count("SELECT COUNT(*) FROM items WHERE source='usgs-quakes' AND lat IS NOT NULL "
                              "AND lon IS NOT NULL AND happened_at >= ?", start_iso)
        self.assertGreater(expected, 0)
        self.assertEqual(len(get_json(self.srv, "/api/layers/quakes")["points"]), min(expected, 2000))

    def test_kev_panel_and_freshness_come_from_the_store(self):
        entries = get_json(self.srv, "/api/panels/kev")["entries"]
        start_iso = iso_utc(self.now - timedelta(days=30))
        self.assertEqual(len(entries), min(50, self.count(
            "SELECT COUNT(*) FROM items WHERE source='cisa-kev' AND happened_at >= ?", start_iso)))
        sources = {s["source"]: s for s in get_json(self.srv, "/api/board")["sources"]}
        last_ok = self.count("SELECT last_ok_at FROM source_state WHERE source='usgs-quakes'")
        self.assertEqual(sources["usgs-quakes"]["last_ok_at"], last_ok)


if __name__ == "__main__":
    unittest.main()
