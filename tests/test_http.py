"""The fetcher against a real HTTP server on 127.0.0.1."""

import http.server
import threading
import time
import unittest
from unittest import mock

from worldwatch import http as ww_http
from worldwatch.http import FetchError, Fetcher, RateLimited


class Handler(http.server.BaseHTTPRequestHandler):
    seen_agents: list = []

    def do_GET(self):
        Handler.seen_agents.append(self.headers.get("User-Agent"))
        if self.path == "/429":
            self.send_response(429)
            self.send_header("Retry-After", "120")
            self.end_headers()
            self.wfile.write(b"Please limit requests to one every 5 seconds")
        elif self.path == "/500":
            self.send_response(500)
            self.end_headers()
        elif self.path == "/short":
            self.send_response(200)
            self.send_header("Content-Length", "100")
            self.end_headers()
            self.wfile.write(b"only ten b")
            self.close_connection = True
        elif self.path == "/drip":
            self.send_response(200)
            self.end_headers()
            for _ in range(20):
                self.wfile.write(b"." * 70_000)
                self.wfile.flush()
                time.sleep(0.05)
        elif self.path == "/big":
            self.send_response(200)
            self.end_headers()
            self.wfile.write(b"x" * 2048)
        else:
            self.send_response(200)
            self.end_headers()
            self.wfile.write(b'{"ok": true}')

    def log_message(self, *args):
        pass


class FetcherTests(unittest.TestCase):
    @classmethod
    def setUpClass(cls):
        cls.server = http.server.ThreadingHTTPServer(("127.0.0.1", 0), Handler)
        cls.base = f"http://127.0.0.1:{cls.server.server_address[1]}"
        threading.Thread(target=cls.server.serve_forever, daemon=True).start()

    @classmethod
    def tearDownClass(cls):
        cls.server.shutdown()
        cls.server.server_close()

    def test_ok_and_identifies_itself(self):
        self.assertEqual(Fetcher().get(self.base + "/ok"), b'{"ok": true}')
        self.assertEqual(Handler.seen_agents[-1], ww_http.USER_AGENT)

    def test_429_is_rate_limited_with_retry_after(self):
        with self.assertRaises(RateLimited) as caught:
            Fetcher().get(self.base + "/429")
        self.assertEqual(caught.exception.retry_after_s, 120.0)

    def test_server_error_is_a_fetch_error(self):
        with self.assertRaises(FetchError) as caught:
            Fetcher().get(self.base + "/500")
        self.assertNotIsInstance(caught.exception, RateLimited)

    def test_refused_connection_is_a_fetch_error(self):
        with self.assertRaises(FetchError):
            Fetcher().get("http://127.0.0.1:9/")

    def test_oversized_body_is_refused(self):
        with mock.patch.object(ww_http, "MAX_BYTES", 1024):
            with self.assertRaises(FetchError):
                Fetcher().get(self.base + "/big")

    def test_truncated_body_is_a_fetch_error(self):
        with self.assertRaises(FetchError):
            Fetcher().get(self.base + "/short")

    def test_a_dripping_server_hits_the_total_deadline(self):
        with mock.patch.object(ww_http, "TOTAL_DEADLINE_S", 0.2):
            with self.assertRaises(FetchError) as caught:
                Fetcher().get(self.base + "/drip")
        self.assertIn("deadline", str(caught.exception))

    def test_per_host_gap_is_kept(self):
        clock = [100.0]
        slept = []

        def sleep(seconds):
            slept.append(seconds)
            clock[0] += seconds

        fetcher = Fetcher(sleep=sleep, clock=lambda: clock[0])
        with mock.patch.dict(ww_http.HOST_MIN_GAP_S, {"127.0.0.1": 6.0}):
            fetcher.get(self.base + "/ok")
            clock[0] += 1.0
            fetcher.get(self.base + "/ok")
        self.assertEqual(slept, [5.0])

    def test_retry_after_parsing(self):
        self.assertEqual(ww_http._retry_after("30"), 30.0)
        self.assertIsNone(ww_http._retry_after("Wed, 21 Oct 2026 07:28:00 GMT"))
        self.assertIsNone(ww_http._retry_after(None))


if __name__ == "__main__":
    unittest.main()
