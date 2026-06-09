"""Smoke tests for the libretro shim against the bundled mGBA core."""

from __future__ import annotations

import numpy as np
import pytest

from gbax.libretro import (
    BUTTON_IDS,
    GBA_HEIGHT,
    GBA_WIDTH,
    LibretroCore,
)


@pytest.fixture
def core(mgba_core, test_rom):
    c = LibretroCore(mgba_core)
    c.init()
    c.load_rom(test_rom)
    c.reset()
    yield c
    c.deinit()


def test_run_advances_without_error(core):
    for _ in range(60):
        core.run()


def test_framebuffer_shape_and_dtype(core):
    core.run()
    fb = core.framebuffer
    assert fb.shape == (GBA_HEIGHT, GBA_WIDTH, 3)
    assert fb.dtype == np.uint8


def test_framebuffer_has_content_after_frames(core):
    for _ in range(60):
        core.run()
    fb = core.framebuffer
    # A real ROM produces something other than all-zero pixels by frame 60
    assert fb.max() > 0


def test_memory_map_descriptors_present(core):
    # mGBA should set memory maps during init/load
    assert len(core._mem_descriptors) >= 5, "expected at least IWRAM/EWRAM/ROM/VRAM/I-O"


def test_read_ewram_initial_zero(core):
    data = core.read_bus(0x02000000, 16)
    assert len(data) == 16
    # EWRAM is zero on cold boot
    assert data == b"\x00" * 16


def test_write_then_read_ewram(core):
    core.write_bus(0x02000100, b"\xDE\xAD\xBE\xEF")
    assert core.read_bus(0x02000100, 4) == b"\xDE\xAD\xBE\xEF"


def test_read_iwram(core):
    core.run()
    data = core.read_bus(0x03000000, 16)
    assert len(data) == 16


def test_rom_region_is_const(core):
    # ROM at 0x08000000 should reject writes
    with pytest.raises(PermissionError):
        core.write_bus(0x08000000, b"\x00\x00\x00\x00")


def test_resolve_unmapped_address_raises(core):
    with pytest.raises(ValueError):
        core.read_bus(0xFFFF0000, 4)


def test_serialize_unserialize_roundtrip(core):
    core.write_bus(0x02000200, b"\x42\x42\x42\x42")
    state = core.serialize()
    assert len(state) > 0

    # Mutate the value, then restore
    core.write_bus(0x02000200, b"\x00\x00\x00\x00")
    assert core.read_bus(0x02000200, 4) == b"\x00\x00\x00\x00"

    core.unserialize(state)
    assert core.read_bus(0x02000200, 4) == b"\x42\x42\x42\x42"


def test_button_input_does_not_crash(core):
    core.set_buttons({BUTTON_IDS["A"]})
    for _ in range(2):
        core.run()
    core.set_buttons(set())
    for _ in range(2):
        core.run()
