"""API keys: read only from Windows user environment variables Trevor creates, never from a file,
the code or a note. A key is checked at the boundary (letters, digits, '-' and '_', a sane length)
and every key we read is masked out of log lines and stored error messages.

`setx` writes the user environment for new processes only, so a window that was already open would
not see a fresh key: on Windows the registry's user environment is read too (HKCU\\Environment).
"""

from __future__ import annotations

import logging
import os
import re
import sys

KEY = re.compile(r"[A-Za-z0-9_-]{8,128}")
MASK = "•••"

_seen: set[str] = set()  # every key value read so far: masked wherever text leaves the process


def _from_registry(name: str) -> str | None:
    if sys.platform != "win32":
        return None
    try:
        import winreg

        with winreg.OpenKey(winreg.HKEY_CURRENT_USER, "Environment") as env:
            value, _kind = winreg.QueryValueEx(env, name)
    except OSError:
        return None
    return value if isinstance(value, str) else None


def get_key(name: str) -> str | None:
    """The key named `name`, or None when it is missing or malformed (a malformed key is never sent)."""
    value = os.environ.get(name) or _from_registry(name)
    if not value:
        return None
    value = value.strip()
    if not KEY.fullmatch(value):
        return None
    _seen.add(value)
    return value


def require_key(name: str) -> str:
    """The key, or MissingKey saying whether it is missing or set but malformed (so Trevor knows which)."""
    key = get_key(name)
    if key is not None:
        return key
    if os.environ.get(name) or _from_registry(name):
        raise MissingKey(f"{name} is set but malformed (letters, digits, '-' and '_' only, 8 to 128 of them)")
    raise MissingKey(f"needs {name} (a Windows user environment variable Trevor creates)")


def redact(text: str) -> str:
    for value in _seen:
        text = text.replace(value, MASK)
    return text


class RedactKeys(logging.Filter):
    """On a handler: every record's final text has the keys masked, whatever logged it."""

    def filter(self, record: logging.LogRecord) -> bool:
        if _seen:
            message = record.getMessage()
            masked = redact(message)
            if masked != message:
                record.msg, record.args = masked, None
            if record.exc_info and record.exc_info[1] is not None:
                record.exc_text = redact(logging.Formatter().formatException(record.exc_info))
                record.exc_info = None
        return True


class MissingKey(Exception):
    """The source needs a key that is not set: not a failure of the source, a wait for Trevor."""
