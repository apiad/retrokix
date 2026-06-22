"""HubState — registry of spawned child play processes.

Each child is `retrokix play <rom> --headless --no-open-browser
--listen-port N` running in its own process. The hub keeps a small
record per child (id, port, rom path, console, pid) so it can build
play URLs and reap on shutdown. Subprocess isolation means a libretro
core crash kills one tab, not the hub.
"""

from __future__ import annotations

import socket
import subprocess
import sys
import threading
import time
from dataclasses import dataclass, field
from pathlib import Path
from typing import Callable, Protocol


class _ProcessLike(Protocol):
    pid: int

    def poll(self) -> int | None: ...
    def terminate(self) -> None: ...
    def kill(self) -> None: ...
    def wait(self, timeout: float | None = None) -> int: ...


Spawner = Callable[[list[str]], _ProcessLike]


def _default_spawner(cmd: list[str]) -> subprocess.Popen:
    return subprocess.Popen(cmd)


@dataclass
class GameProcess:
    game_id: str
    rom_path: Path
    console: str | None
    port: int
    pid: int
    process: _ProcessLike
    started_at: float = field(default_factory=time.time)


class HubState:
    """Thread-safe registry of child play processes."""

    def __init__(
        self,
        *,
        host: str = "127.0.0.1",
        spawner: Spawner | None = None,
        cli_entry: list[str] | None = None,
    ) -> None:
        self.host = host
        self._spawner: Spawner = spawner or _default_spawner
        # Default: re-invoke ourselves through the retrokix module entry.
        # Tests inject a fake spawner so cli_entry stays unused.
        self._cli_entry: list[str] = cli_entry or [sys.executable, "-m", "retrokix"]
        self._processes: dict[str, GameProcess] = {}
        self._counter = 0
        self._lock = threading.Lock()

    def _allocate_port(self) -> int:
        """Ask the kernel for any free port. Race-free in practice — the
        child binds before any sibling spawn could collide."""
        with socket.socket(socket.AF_INET, socket.SOCK_STREAM) as s:
            s.bind((self.host, 0))
            return s.getsockname()[1]

    def _next_game_id(self) -> str:
        # _counter mutation is held under the same lock as _processes
        # to keep ids monotonic under concurrent spawn.
        self._counter += 1
        return f"g{self._counter:04d}"

    def spawn(self, rom_path: Path, console: str | None = None) -> GameProcess:
        with self._lock:
            port = self._allocate_port()
            game_id = self._next_game_id()
        cmd = [
            *self._cli_entry,
            "play",
            str(rom_path),
            "--headless",
            "--no-open-browser",
            "--listen-host", self.host,
            "--listen-port", str(port),
        ]
        proc = self._spawner(cmd)
        gp = GameProcess(
            game_id=game_id,
            rom_path=rom_path,
            console=console,
            port=port,
            pid=proc.pid,
            process=proc,
        )
        with self._lock:
            self._processes[game_id] = gp
        return gp

    def get(self, game_id: str) -> GameProcess | None:
        with self._lock:
            return self._processes.get(game_id)

    def list(self) -> list[GameProcess]:
        with self._lock:
            return list(self._processes.values())

    def play_url(self, game_id: str) -> str | None:
        gp = self.get(game_id)
        if gp is None:
            return None
        return f"http://{self.host}:{gp.port}/stream?mode=controller"

    def reap(self, game_id: str) -> bool:
        with self._lock:
            gp = self._processes.pop(game_id, None)
        if gp is None:
            return False
        try:
            gp.process.terminate()
            try:
                gp.process.wait(timeout=5)
            except Exception:
                gp.process.kill()
        except Exception:
            # Already dead, or process surface differs from Popen.
            pass
        return True

    def shutdown_all(self) -> None:
        for game_id in [gp.game_id for gp in self.list()]:
            self.reap(game_id)
