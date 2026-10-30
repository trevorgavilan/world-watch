"""A headless Edge (or Chrome) driven over the DevTools protocol, standard library only.

The Board's layout lives in the browser, so its tests run the real page in a real browser. The
browser is told to stay offline apart from the page it is given (no sync, updates or extensions),
and only ever opens 127.0.0.1. Without Edge or Chrome on the machine the tests that need it skip.
"""

from __future__ import annotations

import base64
import json
import os
import shutil
import socket
import struct
import subprocess
import time
import urllib.request
from pathlib import Path

from tests.helpers import temp_dir

CANDIDATES = [
    Path(os.environ.get("ProgramFiles(x86)", r"C:\Program Files (x86)")) / "Microsoft/Edge/Application/msedge.exe",
    Path(os.environ.get("ProgramFiles", r"C:\Program Files")) / "Microsoft/Edge/Application/msedge.exe",
    Path(os.environ.get("ProgramFiles", r"C:\Program Files")) / "Google/Chrome/Application/chrome.exe",
]
FLAGS = ["--headless=new", "--remote-debugging-port=0", "--no-first-run", "--no-default-browser-check",
         "--disable-background-networking", "--disable-component-update", "--disable-sync",
         "--disable-extensions", "--disable-default-apps", "--metrics-recording-only", "--mute-audio",
         "--no-pings", "--disable-domain-reliability", "--disable-crash-reporter", "--disable-breakpad",
         # the browser's own traffic too: every name but 127.0.0.1 fails to resolve, and any proxy use goes nowhere
         "--host-resolver-rules=MAP * ~NOTFOUND , EXCLUDE 127.0.0.1", "--proxy-server=127.0.0.1:9",
         "--use-angle=swiftshader", "--enable-unsafe-swiftshader"]
LOCAL = urllib.request.build_opener(urllib.request.ProxyHandler({}))  # never a system proxy for 127.0.0.1


def find_browser() -> Path | None:
    return next((p for p in CANDIDATES if p.exists()), None)


class Browser:
    """One headless browser with one tab. `run(js)` evaluates an expression and returns its value."""

    def __init__(self, exe: Path):
        self.profile = temp_dir()
        self.proc = subprocess.Popen([str(exe), *FLAGS, f"--user-data-dir={self.profile}", "about:blank"],
                                     stdout=subprocess.DEVNULL, stderr=subprocess.DEVNULL)
        self.ws = None
        self.next_id = 0
        try:
            self.ws = _WebSocket(self._page_socket(self._devtools_port()))
            self.call("Page.enable")
            self.call("Runtime.enable")
        except BaseException:
            self.close()  # never leave a browser running with its debugging port open
            raise

    def _page_socket(self, port: int) -> str:
        deadline = time.monotonic() + 30
        while time.monotonic() < deadline:
            targets = json.loads(LOCAL.open(f"http://127.0.0.1:{port}/json/list", timeout=10).read())
            if page := next((t for t in targets if t["type"] == "page"), None):
                return page["webSocketDebuggerUrl"]
            time.sleep(0.1)
        raise RuntimeError("the browser opened no page")

    def _devtools_port(self) -> int:
        marker = self.profile / "DevToolsActivePort"
        deadline = time.monotonic() + 30
        while time.monotonic() < deadline:
            if marker.exists() and (text := marker.read_text().split()):
                return int(text[0])
            time.sleep(0.1)
        raise RuntimeError("the browser never opened its DevTools port")

    def call(self, method: str, **params):
        self.next_id += 1
        self.ws.send(json.dumps({"id": self.next_id, "method": method, "params": params}))
        deadline = time.monotonic() + 30  # events keep the socket busy: a lost reply must still end
        while time.monotonic() < deadline:
            msg = json.loads(self.ws.recv())
            if msg.get("id") == self.next_id:
                if "error" in msg:
                    raise RuntimeError(f"{method}: {msg['error']}")
                return msg.get("result", {})
        raise TimeoutError(f"{method}: no reply in 30 s")

    def run(self, expression: str):
        result = self.call("Runtime.evaluate", expression=expression, returnByValue=True, awaitPromise=True)
        if "exceptionDetails" in result:
            raise RuntimeError(f"{expression[:60]}: {result['exceptionDetails'].get('text')}")
        return result["result"].get("value")

    def wait_for(self, expression: str, timeout: float = 20.0):
        deadline = time.monotonic() + timeout
        last_error = None
        while time.monotonic() < deadline:
            try:
                if value := self.run(expression):
                    return value
            except RuntimeError as err:  # mid-navigation the old page's context can vanish under us
                last_error = err
            time.sleep(0.05)
        raise AssertionError(f"never true: {expression} (last error: {last_error})")

    def size(self, width: int, height: int):
        self.call("Emulation.setDeviceMetricsOverride", width=width, height=height, deviceScaleFactor=1, mobile=False)

    def open(self, url: str, ready: str):
        """Load (or reload) a page and wait until `ready` is true in the new document, not the old one."""
        self.run("window.__wwOld = true")
        self.call("Page.navigate", url=url)
        self.wait_for(f"!window.__wwOld && location.href === {json.dumps(url)} && "
                      f"document.readyState === 'complete' && ({ready})")

    def before_each_page(self, source: str) -> str:
        return self.call("Page.addScriptToEvaluateOnNewDocument", source=source)["identifier"]

    def forget_script(self, identifier: str):
        self.call("Page.removeScriptToEvaluateOnNewDocument", identifier=identifier)

    def mouse(self, kind: str, x: float, y: float, buttons: int = 1):
        self.call("Input.dispatchMouseEvent", type=kind, x=x, y=y, button="left",
                  buttons=buttons, clickCount=1 if kind != "mouseMoved" else 0)

    def drag(self, x: float, y: float, to_x: float):
        self.mouse("mousePressed", x, y)
        for step in range(1, 6):
            self.mouse("mouseMoved", x + (to_x - x) * step / 5, y)
        self.mouse("mouseReleased", to_x, y, buttons=0)

    def key(self, key: str, code: str, key_code: int):
        for kind in ("rawKeyDown", "keyUp"):
            self.call("Input.dispatchKeyEvent", type=kind, key=key, code=code, windowsVirtualKeyCode=key_code)

    def close(self):
        if self.ws:
            try:
                self.call("Browser.close")
            except Exception:  # noqa: BLE001 — it may already be gone
                pass
            self.ws.close()
        try:
            self.proc.wait(timeout=10)
        except subprocess.TimeoutExpired:
            self.proc.kill()
        shutil.rmtree(self.profile, ignore_errors=True)


class _WebSocket:
    """Just enough of RFC 6455 for DevTools on loopback: text frames, client-masked, no extensions."""

    def __init__(self, url: str):
        assert url.startswith("ws://127.0.0.1:"), url
        host_port, path = url[len("ws://"):].split("/", 1)
        host, port = host_port.split(":")
        self.sock = socket.create_connection((host, int(port)), timeout=30)
        key = base64.b64encode(os.urandom(16)).decode()
        self.sock.sendall((f"GET /{path} HTTP/1.1\r\nHost: {host_port}\r\nUpgrade: websocket\r\n"
                           f"Connection: Upgrade\r\nSec-WebSocket-Key: {key}\r\nSec-WebSocket-Version: 13\r\n\r\n")
                          .encode())
        head = b""
        while b"\r\n\r\n" not in head:
            head += self.sock.recv(1)
        if b" 101 " not in head.split(b"\r\n", 1)[0]:
            raise RuntimeError(head.decode("latin-1"))

    def send(self, text: str):
        data = text.encode()
        mask = os.urandom(4)
        n = len(data)
        head = bytes([0x81]) + (bytes([0x80 | n]) if n < 126 else
                                bytes([0x80 | 126]) + struct.pack(">H", n) if n < 65536 else
                                bytes([0x80 | 127]) + struct.pack(">Q", n))
        self.sock.sendall(head + mask + bytes(b ^ mask[i % 4] for i, b in enumerate(data)))

    def recv(self) -> str:
        parts = []
        while True:
            b0, b1 = self._exact(2)
            n = b1 & 0x7F
            if n == 126:
                n = struct.unpack(">H", self._exact(2))[0]
            elif n == 127:
                n = struct.unpack(">Q", self._exact(8))[0]
            payload = self._exact(n)
            if b0 & 0x0F in (0x1, 0x0):
                parts.append(payload)
                if b0 & 0x80:
                    return b"".join(parts).decode()
            elif b0 & 0x0F == 0x8:
                raise ConnectionError("the browser closed DevTools")

    def _exact(self, n: int) -> bytes:
        buf = b""
        while len(buf) < n:
            chunk = self.sock.recv(n - len(buf))
            if not chunk:
                raise ConnectionError("the browser closed DevTools")
            buf += chunk
        return buf

    def close(self):
        self.sock.close()
