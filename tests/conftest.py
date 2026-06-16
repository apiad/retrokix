"""Pytest fixtures shared across the retrokix test suite."""

from __future__ import annotations

import signal
from pathlib import Path

import pytest


FIXTURES = Path(__file__).parent / "fixtures"
CORES = Path(__file__).parent / "cores"


class FakeProcess:
    """Stand-in for subprocess.Popen — used by hub tests."""

    _next_pid = 9000

    def __init__(self) -> None:
        FakeProcess._next_pid += 1
        self.pid = FakeProcess._next_pid
        self._alive = True
        self.terminate_calls = 0
        self.kill_calls = 0

    def poll(self):
        return None if self._alive else 0

    def terminate(self) -> None:
        self.terminate_calls += 1
        self._alive = False

    def kill(self) -> None:
        self.kill_calls += 1
        self._alive = False

    def wait(self, timeout: float | None = None) -> int:
        return 0

    def send_signal(self, sig: int) -> None:
        if sig in (signal.SIGTERM, signal.SIGKILL):
            self._alive = False


@pytest.fixture
def fake_process_cls():
    """Hand tests the FakeProcess class without forcing them to import
    from conftest (which pytest doesn't expose as a regular module)."""
    return FakeProcess


@pytest.fixture
def test_rom() -> Path:
    return FIXTURES / "test.gba"


@pytest.fixture
def mgba_core() -> Path:
    """Path to the bundled mgba_libretro.so used for tests.

    Build instructions in `know-how/building-libretro-core.md`.
    """
    path = CORES / "mgba_libretro.so"
    if not path.exists():
        pytest.skip(f"libretro core not built (expected at {path}); "
                    "see know-how/building-libretro-core.md")
    return path
