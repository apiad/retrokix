"""Tests for the public Controller API."""

from __future__ import annotations

from pathlib import Path

import numpy as np
import pytest
from PIL import Image

from gbax.controller import Controller
from gbax.input import Button


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


def test_memory_roundtrip_u8(controller):
    controller.write_u8(0x02000100, 0x42)
    assert controller.read_u8(0x02000100) == 0x42


def test_memory_roundtrip_u32(controller):
    controller.write_u32(0x02000100, 0xCAFEBABE)
    assert controller.read_u32(0x02000100) == 0xCAFEBABE


def test_memory_bulk_roundtrip(controller):
    controller.write_bytes(0x02001000, b"\xDE\xAD\xBE\xEF")
    assert controller.read_bytes(0x02001000, 4) == b"\xDE\xAD\xBE\xEF"


def test_screenshot_writes_png(controller, tmp_path):
    out = tmp_path / "frame.png"
    controller.screenshot(out)
    assert out.exists()
    img = Image.open(out)
    assert img.size == (240, 160)
    assert img.mode == "RGB"


def test_save_state_roundtrip(controller):
    controller.press(["start"], frames=5)
    blob = controller.save_state()
    assert isinstance(blob, bytes) and len(blob) > 0
    controller.press(["a"], frames=5)
    fc_before = controller.frame_count
    controller.load_state(blob)
    assert controller.frame_count <= fc_before


def test_slot_save_and_load(controller, tmp_path):
    controller.press(["start"], frames=7)
    controller.save_slot(3)
    controller.press(["a"], frames=7)
    controller.load_slot(3)
    assert controller.frame_count == 7
