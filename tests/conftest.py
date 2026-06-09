"""Pytest fixtures shared across the gbax test suite."""

from __future__ import annotations

from pathlib import Path

import pytest


FIXTURES = Path(__file__).parent / "fixtures"
CORES = Path(__file__).parent / "cores"


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
