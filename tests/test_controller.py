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


from gbax.input import Button


def test_press_advances_frames(controller):
    controller.press(["a"], frames=3)
    assert controller.frame_count == 3


def test_press_releases_at_end(controller):
    controller.press(["a", "right"], frames=2)
    assert controller._runtime.buttons_held() == set()


def test_hold_does_not_release(controller):
    controller.hold(["a"])
    assert controller._runtime.buttons_held() == {Button.A}


def test_release_clears(controller):
    controller.hold(["a", "b"])
    controller.release()
    assert controller._runtime.buttons_held() == set()


def test_wait_advances_with_current_held(controller):
    controller.hold(["start"])
    controller.wait(5)
    assert controller.frame_count == 5
    assert controller._runtime.buttons_held() == {Button.START}


def test_press_unknown_button_raises(controller):
    with pytest.raises(ValueError):
        controller.press(["turbo"], frames=1)
