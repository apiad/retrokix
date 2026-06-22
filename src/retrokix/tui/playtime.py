"""Per-ROM play-time tracking — session timer + persisted cumulative total.

A small JSON sidecar at ``~/.retrokix/playtime/<rom_sha1>.json`` records the
total seconds ever spent in a ROM. ``PlayTime`` wraps a live session timer on
top of that total so the core TUI tab can render both. Atomic writes via
tmp-file + rename, mirroring ``retrokix.settings``.
"""

from __future__ import annotations

import json
import os
import tempfile
import time
from pathlib import Path
from typing import Callable

DEFAULT_PLAYTIME_DIR = Path.home() / ".retrokix" / "playtime"


def _path_for(rom_sha1: str, root: Path | None = None) -> Path:
    base = Path(root) if root else DEFAULT_PLAYTIME_DIR
    return base / f"{rom_sha1}.json"


def load_total(rom_sha1: str, root: Path | None = None) -> float:
    """Persisted cumulative seconds for this ROM, or 0.0 if absent/unreadable."""
    p = _path_for(rom_sha1, root)
    if not p.exists():
        return 0.0
    try:
        data = json.loads(p.read_text())
        return float(data.get("total_seconds", 0.0))
    except (json.JSONDecodeError, OSError, TypeError, ValueError):
        return 0.0


def add_session(rom_sha1: str, seconds: float, root: Path | None = None) -> float:
    """Add ``seconds`` to the persisted total and return the new total."""
    new_total = load_total(rom_sha1, root) + float(seconds)
    p = _path_for(rom_sha1, root)
    p.parent.mkdir(parents=True, exist_ok=True)
    fd, tmp = tempfile.mkstemp(dir=p.parent, suffix=".tmp")
    try:
        with os.fdopen(fd, "w") as fh:
            json.dump({"total_seconds": new_total}, fh)
        os.replace(tmp, p)
    finally:
        if os.path.exists(tmp):
            os.unlink(tmp)
    return new_total


class PlayTime:
    """Live session timer layered over the persisted per-ROM total."""

    def __init__(
        self,
        rom_sha1: str,
        root: Path | None = None,
        clock: Callable[[], float] = time.monotonic,
    ) -> None:
        self._sha1 = rom_sha1
        self._root = root
        self._clock = clock
        self._start: float | None = None
        self._persisted = load_total(rom_sha1, root)

    def start(self) -> None:
        self._start = self._clock()

    @property
    def session_seconds(self) -> float:
        if self._start is None:
            return 0.0
        return self._clock() - self._start

    @property
    def total_seconds(self) -> float:
        return self._persisted + self.session_seconds

    def flush(self) -> None:
        """Persist the current session into the total and reset the timer."""
        if self._start is None:
            return
        elapsed = self._clock() - self._start
        self._persisted = add_session(self._sha1, elapsed, self._root)
        self._start = self._clock()
