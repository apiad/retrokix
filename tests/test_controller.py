"""Tests for the public Controller API."""

from __future__ import annotations

from pathlib import Path

import numpy as np
import pytest

from gbax.controller import Controller


@pytest.fixture
def controller(test_rom, mgba_core):
    with Controller(test_rom, core_path=mgba_core) as c:
        yield c


def test_construction_loads_rom(controller, test_rom):
    assert controller.rom_path == Path(test_rom)
    assert controller.frame_count == 0


def test_framebuffer_initially_present(controller):
    fb = controller.framebuffer
    assert fb.shape == (160, 240, 3)
    assert fb.dtype == np.uint8
