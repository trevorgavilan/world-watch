import logging
import os
import unittest
from pathlib import Path
from unittest import mock

from tests.helpers import temp_dir
from worldwatch import cli, console


class Lock(unittest.TestCase):
    def test_second_holder_is_refused_until_the_first_lets_go(self):
        path = temp_dir() / "worldwatch.lock"
        first = cli.SingleInstance(path)
        self.assertTrue(first.acquire())
        self.assertFalse(cli.SingleInstance(path).acquire())
        first.release()
        again = cli.SingleInstance(path)
        self.assertTrue(again.acquire())
        again.release()


class Commands(unittest.TestCase):
    def setUp(self):
        self.home = temp_dir()
        patcher = mock.patch.dict(os.environ, {"WORLDWATCH_HOME": str(self.home)})
        patcher.start()
        self.addCleanup(patcher.stop)
        self.addCleanup(logging.getLogger().handlers.clear)
        logging.getLogger().handlers.clear()

    def test_once_and_loop_refuse_while_another_copy_runs(self):
        held = cli.SingleInstance(self.home / "worldwatch.lock")
        self.assertTrue(held.acquire())
        try:
            with mock.patch.object(cli.runner, "run_once") as run_once, \
                 mock.patch.object(cli.runner, "run_loop") as run_loop:
                self.assertEqual(cli.main(["once"]), 2)
                self.assertEqual(cli.main(["loop"]), 2)
            run_once.assert_not_called()
            run_loop.assert_not_called()
        finally:
            held.release()

    def test_an_unexpected_crash_is_logged_and_returns_1(self):
        with mock.patch.object(cli, "all_collectors", side_effect=RuntimeError("boom")):
            self.assertEqual(cli.main(["recon"]), 1)
        log_text = (self.home / "logs" / "worldwatch.log").read_text(encoding="utf-8")
        self.assertIn("boom", log_text)
        self.assertIn("Traceback", log_text)

    def assert_lock_free(self):
        lock = cli.SingleInstance(self.home / "worldwatch.lock")
        self.assertTrue(lock.acquire(), "start left the lock held")
        lock.release()

    def test_start_survives_a_failing_first_fetch(self):
        with mock.patch.object(cli, "wait_for_network", return_value=True), \
             mock.patch.object(cli.runner, "run_once", side_effect=OSError("disk hiccup")), \
             mock.patch.object(cli, "_open") as opened, \
             mock.patch.object(cli.runner, "run_loop") as run_loop:
            self.assertEqual(cli.main(["start"]), 0)
        opened.assert_called_once()
        run_loop.assert_called_once()
        self.assertEqual(run_loop.call_args.kwargs["heartbeat_s"], cli.HEARTBEAT_S)
        self.assert_lock_free()

    def test_start_logs_when_it_starts_and_stops(self):
        with mock.patch.object(cli, "wait_for_network", return_value=True), \
             mock.patch.object(cli.runner, "run_once", return_value=[]), \
             mock.patch.object(cli, "_open"), \
             mock.patch.object(cli.runner, "run_loop", side_effect=KeyboardInterrupt):
            self.assertEqual(cli.main(["start"]), 130)
        log_text = (self.home / "logs" / "worldwatch.log").read_text(encoding="utf-8")
        self.assertIn("World Watch started", log_text)
        self.assertIn("World Watch stopped", log_text)
        self.assert_lock_free()

    def test_a_second_start_shows_the_last_recon_and_does_not_collect(self):
        latest = self.home / "recon" / "recon-latest.html"
        latest.parent.mkdir(parents=True)
        latest.write_text("<html></html>", encoding="utf-8")
        held = cli.SingleInstance(self.home / "worldwatch.lock")
        self.assertTrue(held.acquire())
        try:
            with mock.patch.object(cli, "_open") as opened, \
                 mock.patch.object(cli.runner, "run_once") as run_once, \
                 mock.patch.object(cli.runner, "run_loop") as run_loop:
                self.assertEqual(cli.main(["start"]), 2)
            opened.assert_called_once_with(latest)
            run_once.assert_not_called()
            run_loop.assert_not_called()
        finally:
            held.release()


class Console(unittest.TestCase):
    def test_quick_edit_is_cleared_and_extended_flags_set(self):
        mode = console.quick_edit_off(0x0040 | 0x0001)
        self.assertFalse(mode & console.ENABLE_QUICK_EDIT_MODE)
        self.assertTrue(mode & console.ENABLE_EXTENDED_FLAGS)
        self.assertTrue(mode & 0x0001)  # other modes kept

    def test_closing_the_window_is_logged_and_windows_carries_on(self):
        with self.assertLogs("worldwatch.console", level="INFO") as logs:
            self.assertFalse(console.on_console_event(2))
        self.assertIn("window closed", logs.output[0])

    def test_ctrl_c_is_left_to_python(self):
        with self.assertNoLogs("worldwatch.console", level="INFO"):
            self.assertFalse(console.on_console_event(0))


class WaitForNetwork(unittest.TestCase):
    def test_waits_until_the_name_resolves(self):
        answers = iter([OSError("no route"), OSError("no route"), None])
        slept = []

        def resolve(host, port):
            answer = next(answers)
            if answer:
                raise answer

        self.assertTrue(cli.wait_for_network(resolve=resolve, sleep=slept.append, attempts=5, pause_s=10))
        self.assertEqual(slept, [10, 10])

    def test_gives_up_after_the_attempts(self):
        def resolve(host, port):
            raise OSError("offline")

        slept = []
        self.assertFalse(cli.wait_for_network(resolve=resolve, sleep=slept.append, attempts=3, pause_s=10))
        self.assertEqual(len(slept), 2)


if __name__ == "__main__":
    unittest.main()
