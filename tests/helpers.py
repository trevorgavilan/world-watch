from __future__ import annotations

import atexit
import os
import shutil
import tempfile
from datetime import datetime, timezone
from pathlib import Path

from worldwatch.item import make_item

FIXTURES = Path(__file__).parent / "fixtures"
LIVE = os.environ.get("WW_LIVE") == "1"  # live tests hit the real feeds; off by default

NOW = datetime(2026, 10, 23, 23, 50, tzinfo=timezone.utc)


def fixture(name: str) -> bytes:
    return (FIXTURES / name).read_bytes()


def temp_dir() -> Path:
    path = Path(tempfile.mkdtemp(prefix="ww-test-"))
    atexit.register(shutil.rmtree, path, ignore_errors=True)  # else every run leaks into %TEMP%
    return path


def sample_item(n: int = 1, *, source: str = "test-src", channel: str = "news", **over):
    fields = dict(
        channel=channel,
        source=source,
        native_id=f"native-{n}",
        happened_at=NOW,
        fetched_at=NOW,
        title=f"Title {n}",
        url=f"https://example.org/{n}",
        summary=f"Summary {n}",
        licence="test licence",
        raw={"n": n},
        lang="en",
    )
    fields.update(over)
    return make_item(**fields)
