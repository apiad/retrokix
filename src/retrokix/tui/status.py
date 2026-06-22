"""Status snapshot — the thin, lock-guarded struct shared between the
emulator worker thread (publisher) and the Textual UI thread (reader).

The emulator thread calls ``publish(**fields)`` (cheaply, per frame or on
change); the TUI polls ``read()`` on a timer. This is the *only* mutable
state shared across the two threads in slice 1.
"""

from __future__ import annotations

import threading
from dataclasses import dataclass, replace


@dataclass(frozen=True)
class Status:
    """Generic, every-game status rendered by the core TUI tab."""

    title: str = ""
    console: str = ""
    sha1: str = ""
    fps: float = 0.0
    speed: float = 1.0
    frame_count: int = 0
    session_seconds: float = 0.0
    total_seconds: float = 0.0
    api_endpoint: str | None = None
    client_count: int = 0


class StatusSnapshot:
    """Thread-safe holder for the latest :class:`Status`."""

    def __init__(self) -> None:
        self._lock = threading.Lock()
        self._status = Status()

    def publish(self, **fields: object) -> None:
        with self._lock:
            self._status = replace(self._status, **fields)  # type: ignore[arg-type]

    def read(self) -> Status:
        with self._lock:
            return self._status
