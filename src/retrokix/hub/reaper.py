"""IdleReaper — background thread that kills child processes whose
viewers have left.

Policy: every `poll_interval` seconds, ask each child its `ws_clients`
count via /healthz. Children younger than `grace_period` are skipped
(initial-load window). Children with `ws_clients == 0` get a timestamp
recorded; if that stays at 0 for at least `idle_threshold` seconds,
the child is reaped via HubState.reap.

A probe failure is treated as "unknown" — we don't reap on transient
network errors. Repeated probe failure across multiple ticks could
later trigger reap too, but v1 keeps it conservative.
"""

from __future__ import annotations

import json
import threading
import time
import urllib.error
import urllib.request
from typing import Callable

from retrokix.hub.state import HubState


Probe = Callable[[str, int], int | None]
"""Given (host, port), return the child's current ws_clients or None
on failure."""


def _default_probe(host: str, port: int) -> int | None:
    url = f"http://{host}:{port}/healthz"
    try:
        with urllib.request.urlopen(url, timeout=2) as resp:
            data = json.load(resp)
        return int(data.get("ws_clients", 0))
    except (urllib.error.URLError, json.JSONDecodeError, OSError, ValueError):
        return None


class IdleReaper:
    """Polls each child's /healthz and reaps idle ones."""

    def __init__(
        self,
        hub: HubState,
        *,
        poll_interval: float = 30.0,
        idle_threshold: float = 60.0,
        grace_period: float = 20.0,
        probe: Probe | None = None,
        clock: Callable[[], float] | None = None,
    ) -> None:
        self._hub = hub
        self._poll_interval = poll_interval
        self._idle_threshold = idle_threshold
        self._grace_period = grace_period
        self._probe = probe or _default_probe
        # Must match the clock GameProcess.started_at uses (time.time).
        # Tests inject a controllable clock.
        self._now = clock or time.time
        self._idle_since: dict[str, float] = {}
        self._stop = threading.Event()
        self._thread: threading.Thread | None = None

    def start(self) -> None:
        if self._thread is not None:
            return
        self._thread = threading.Thread(
            target=self._loop, name="retrokix-hub-reaper", daemon=True,
        )
        self._thread.start()

    def stop(self) -> None:
        self._stop.set()
        if self._thread is not None:
            self._thread.join(timeout=2.0)
            self._thread = None

    def _loop(self) -> None:
        while not self._stop.is_set():
            try:
                self.tick()
            except Exception:
                # Reaper errors must never take down the hub.
                pass
            self._stop.wait(self._poll_interval)

    def tick(self) -> list[str]:
        """One reaper pass. Returns the game_ids reaped this tick.

        Public for tests; the loop calls it on every poll.
        """
        reaped: list[str] = []
        now = self._now()
        # Snapshot list — reap mutates the hub state mid-iteration.
        for gp in self._hub.list():
            age = now - gp.started_at
            if age < self._grace_period:
                continue
            ws = self._probe(self._hub.host, gp.port)
            if ws is None:
                # Probe failed — leave alone, try next tick.
                continue
            if ws > 0:
                self._idle_since.pop(gp.game_id, None)
                continue
            since = self._idle_since.get(gp.game_id)
            if since is None:
                self._idle_since[gp.game_id] = now
                continue
            if now - since >= self._idle_threshold:
                if self._hub.reap(gp.game_id):
                    reaped.append(gp.game_id)
                self._idle_since.pop(gp.game_id, None)
        return reaped
