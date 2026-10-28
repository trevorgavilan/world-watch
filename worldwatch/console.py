"""The console window World Watch.bat opens (Windows only; elsewhere these do nothing).

- QuickEdit off: in the classic console a stray click starts a selection, and every write then
  blocks until a key is pressed — the log line would freeze the whole loop.
- Closing the window kills the process without running `finally`; a console handler logs it first.
"""

from __future__ import annotations

import logging
import os

log = logging.getLogger(__name__)

STD_INPUT_HANDLE = -10
ENABLE_QUICK_EDIT_MODE = 0x0040
ENABLE_EXTENDED_FLAGS = 0x0080
CLOSE_EVENTS = {2: "window closed", 5: "logging off", 6: "shutting down"}  # CTRL_CLOSE/LOGOFF/SHUTDOWN

_handler = None  # kept referenced: Windows calls it after setup returns


def quick_edit_off(mode: int) -> int:
    return (mode & ~ENABLE_QUICK_EDIT_MODE) | ENABLE_EXTENDED_FLAGS


def on_console_event(event: int) -> bool:
    """Log a close/logoff/shutdown, then let Windows go on ending the process (False)."""
    reason = CLOSE_EVENTS.get(event)
    if reason:
        log.info("World Watch stopped (%s)", reason)
        for handler in logging.getLogger().handlers:
            handler.flush()
    return False


def setup() -> None:
    global _handler
    if os.name != "nt":
        return
    try:
        import ctypes
        from ctypes import wintypes

        kernel32 = ctypes.windll.kernel32
        stdin = kernel32.GetStdHandle(STD_INPUT_HANDLE)
        mode = wintypes.DWORD()
        if kernel32.GetConsoleMode(stdin, ctypes.byref(mode)):  # false when there is no console
            kernel32.SetConsoleMode(stdin, quick_edit_off(mode.value))
        routine = ctypes.WINFUNCTYPE(wintypes.BOOL, wintypes.DWORD)
        _handler = routine(on_console_event)
        kernel32.SetConsoleCtrlHandler(_handler, True)
    except Exception:  # noqa: BLE001 — a convenience; collection goes on without it
        log.warning("console setup failed", exc_info=True)
