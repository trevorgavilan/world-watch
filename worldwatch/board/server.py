"""The Board's server (D-17): 127.0.0.1 only, read-only GET/HEAD, strict headers on every answer.

Standard library only (Trevor, 2026-10-28: no FastAPI). It runs as a thread of the `World Watch.bat`
process (D-18), so closing that window stops it. Every request opens its own read-only SQLite
connection: SQLite itself refuses any write, whatever a route does.

Safety, each with a test in tests/test_board.py:
- binds 127.0.0.1, nothing else; a request whose Host is not this server's own name is refused
  (421), so a hostile site rebinding its name to 127.0.0.1 gets nothing (DNS rebinding);
- no route writes: anything but GET/HEAD is 405;
- a CSP that lets the page load only its own files, with no inline script at all;
- only the files listed in STATIC are served — no path from the request reaches the disk;
- source text goes out as JSON (with < > & escaped) and the page sets it as text, never HTML;
  links are re-checked as http(s) here and again in the page.
"""

from __future__ import annotations

import json
import logging
import socket
from datetime import datetime, timezone
from http.server import BaseHTTPRequestHandler, ThreadingHTTPServer
from pathlib import Path
from typing import Callable

from ..collectors import Collector
from ..recon_html import CSP as RECON_CSP
from ..store import Store
from . import data

log = logging.getLogger(__name__)

BOARD_HOST = "127.0.0.1"
BOARD_PORT = 8420  # NEMATIC SERVERS: 8000, 8010 and 8800 are taken

CSP = ("default-src 'none'; script-src 'self'; style-src 'self'; img-src 'self'; connect-src 'self'; "
       "base-uri 'none'; form-action 'none'; frame-ancestors 'none'")
SAFETY_HEADERS = {
    "X-Content-Type-Options": "nosniff",
    "Referrer-Policy": "no-referrer",
    "Cross-Origin-Resource-Policy": "same-origin",
    "Cross-Origin-Opener-Policy": "same-origin",
    "X-Frame-Options": "DENY",
    "Cache-Control": "no-store",
}

_HERE = Path(__file__).resolve().parent / "static"
STATIC: dict[str, tuple[Path, str]] = {  # served name -> (file, type); nothing else is ever read
    "board.js": (_HERE / "board.js", "text/javascript; charset=utf-8"),
    "board.css": (_HERE / "board.css", "text/css; charset=utf-8"),
    "globe.gl.min.js": (_HERE / "vendor" / "globe.gl-2.46.2.min.js", "text/javascript; charset=utf-8"),
    "earth.jpg": (_HERE / "vendor" / "earth-blue-marble-5400x2700.jpg", "image/jpeg"),
}
PINNED = {"/static/globe.gl.min.js", "/static/earth.jpg"}
PAGE = _HERE / "board.html"
MAX_DRAIN = 64 * 1024  # bytes of a refused request's body read and dropped; more and the connection just closes


class BoardServer(ThreadingHTTPServer):
    daemon_threads = True
    # The port is ours alone: no SO_REUSEADDR, and on Windows SO_EXCLUSIVEADDRUSE, so another local
    # process can neither share 8420 nor bind on top of the Board (and a taken port fails loudly).
    allow_reuse_address = False

    def __init__(self, db_path: Path, collectors: list[Collector], recon_dir: Path, *, host: str, port: int,
                 now: Callable[[], datetime]) -> None:
        self.db_path = db_path
        self.recon_dir = recon_dir
        self.registry = data.Registry(collectors)
        self.now = now
        super().__init__((host, port), Handler)
        self.allowed_hosts = {f"127.0.0.1:{self.server_port}", f"localhost:{self.server_port}"}

    def server_bind(self) -> None:
        if hasattr(socket, "SO_EXCLUSIVEADDRUSE"):
            self.socket.setsockopt(socket.SOL_SOCKET, socket.SO_EXCLUSIVEADDRUSE, 1)
        super().server_bind()


def make_server(db_path: Path, collectors: list[Collector], recon_dir: Path, *, host: str = BOARD_HOST,
                port: int = BOARD_PORT, now: Callable[[], datetime] | None = None) -> BoardServer:
    if host != BOARD_HOST:
        raise ValueError(f"the Board listens on {BOARD_HOST} only, not {host!r}")
    return BoardServer(db_path, collectors, recon_dir, host=host, port=port,
                       now=now or (lambda: datetime.now(timezone.utc)))


def to_json(body: object) -> bytes:
    """Escaped so a hostile string stays inert even if something ever read the bytes as HTML."""
    text = json.dumps(body, ensure_ascii=False, separators=(",", ":"))
    return text.replace("<", "\\u003c").replace(">", "\\u003e").replace("&", "\\u0026").encode("utf-8")


class Handler(BaseHTTPRequestHandler):
    server: BoardServer
    server_version = "WorldWatchBoard"
    sys_version = ""
    timeout = 15  # an idle or trickling connection lets go of its thread
    error_content_type = "text/plain; charset=utf-8"
    error_message_format = "%(code)d %(message)s\n"

    def do_GET(self) -> None:  # noqa: N802 — http.server's naming
        self._answer(head=False)

    def do_HEAD(self) -> None:  # noqa: N802
        self._answer(head=True)

    def _refuse_write(self) -> None:
        try:  # drain a small body first: closing on unread bytes resets the connection before the 405 lands
            length = int(self.headers.get("Content-Length") or 0)
        except ValueError:
            length = 0
        if 0 < length <= MAX_DRAIN:
            self.rfile.read(length)
        self._send(405, b"read-only\n", "text/plain; charset=utf-8", head=False, extra={"Allow": "GET, HEAD"})

    do_POST = do_PUT = do_DELETE = do_PATCH = do_OPTIONS = _refuse_write  # noqa: N815

    def _answer(self, *, head: bool) -> None:
        if (self.headers.get("Host") or "").lower() not in self.server.allowed_hosts:
            self._send(421, b"wrong host\n", "text/plain; charset=utf-8", head=head)
            return
        try:
            status, body, kind, policy = self._route(self.path.split("?", 1)[0])
        except Exception:  # noqa: BLE001 — a bug answers 500; the window keeps collecting
            log.exception("Board: %s failed", self.path)
            status, body, kind, policy = 500, b"error\n", "text/plain; charset=utf-8", CSP
        pinned = status == 200 and self.path in PINNED  # checksummed files never change under a name
        self._send(status, body, kind, head=head, policy=policy,
                   extra={"Cache-Control": "max-age=86400, immutable"} if pinned else None)

    def _route(self, path: str) -> tuple[int, bytes, str, str]:
        if path == "/":
            return 200, PAGE.read_bytes(), "text/html; charset=utf-8", CSP
        if path.startswith("/static/") and path[len("/static/"):] in STATIC:
            file, kind = STATIC[path[len("/static/"):]]
            return 200, file.read_bytes(), kind, CSP
        if path == "/recon":
            latest = self.server.recon_dir / "recon-latest.html"
            if not latest.is_file():
                return 404, b"no Recon yet\n", "text/plain; charset=utf-8", CSP
            return 200, latest.read_bytes(), "text/html; charset=utf-8", RECON_CSP
        if path.startswith("/api/"):
            return self._api(path[len("/api/"):].split("/"))
        return 404, b"not found\n", "text/plain; charset=utf-8", CSP

    def _api(self, parts: list[str]) -> tuple[int, bytes, str, str]:
        registry = self.server.registry
        found = None
        if parts == ["board"]:
            found = "board"
        elif len(parts) == 2 and parts[0] == "layers":
            found = registry.layer(parts[1])
        elif len(parts) == 2 and parts[0] == "panels":
            found = registry.panel(parts[1])
        if found is None:
            return 404, b"not found\n", "text/plain; charset=utf-8", CSP
        try:
            store = Store.open_readonly(self.server.db_path)
        except (FileNotFoundError, OSError) as err:
            log.info("Board: store not readable yet (%s)", err)
            return 503, b"no data yet\n", "text/plain; charset=utf-8", CSP
        try:
            now = self.server.now()
            if found == "board":
                body = registry.board(store, now)
            elif parts[0] == "layers":
                body = data.layer_points(store, found, now)
            else:
                body = data.panel_entries(store, found, now)
        finally:
            store.close()
        return 200, to_json(body), "application/json; charset=utf-8", CSP

    def _send(self, status: int, body: bytes, kind: str, *, head: bool, policy: str = CSP,
              extra: dict[str, str] | None = None) -> None:
        self.send_response(status)
        self.send_header("Content-Type", kind)
        self.send_header("Content-Length", str(len(body)))
        self._policy = policy
        extra = dict(extra or {})
        self._cache = extra.pop("Cache-Control", None)
        for name, value in extra.items():
            self.send_header(name, value)
        self.end_headers()
        if not head:
            self.wfile.write(body)

    def end_headers(self) -> None:
        """Every answer carries the policy and the safety headers — http.server's own 400/414/501 too."""
        self.send_header("Content-Security-Policy", getattr(self, "_policy", CSP))
        for name, value in SAFETY_HEADERS.items():
            if name == "Cache-Control" and getattr(self, "_cache", None):
                value = self._cache
            self.send_header(name, value)
        super().end_headers()

    def log_message(self, format: str, *args) -> None:  # noqa: A002 — http.server's signature
        log.debug("Board: " + format, *args)
