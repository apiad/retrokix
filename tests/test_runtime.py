"""Tests for the EmulatorRuntime layer."""

from __future__ import annotations

import numpy as np
import pytest

from gbax.runtime import EmulatorRuntime


@pytest.fixture
def runtime(test_rom, mgba_core):
    with EmulatorRuntime(test_rom, core_path=mgba_core) as rt:
        yield rt


def test_load_rom_and_step(runtime):
    assert runtime.frame_count == 0
    runtime.step(frames=1)
    assert runtime.frame_count == 1
    runtime.step(frames=59)
    assert runtime.frame_count == 60


def test_reset_resets_frame_count(runtime):
    runtime.step(frames=10)
    runtime.reset()
    assert runtime.frame_count == 0


def test_step_rejects_zero_or_negative(runtime):
    with pytest.raises(ValueError):
        runtime.step(frames=0)
    with pytest.raises(ValueError):
        runtime.step(frames=-1)


def test_rom_sha1_is_hex_string(runtime):
    h = runtime.rom_sha1
    assert isinstance(h, str)
    assert len(h) == 40
    int(h, 16)  # parses as hex


def test_framebuffer_shape_and_dtype(runtime):
    runtime.step(frames=1)
    fb = runtime.framebuffer()
    assert fb.shape == (160, 240, 3)
    assert fb.dtype == np.uint8


def test_memory_read_write_typed(runtime):
    runtime.write_u32(0x02000010, 0xCAFEBABE)
    assert runtime.read_u32(0x02000010) == 0xCAFEBABE
    runtime.write_u16(0x02000010, 0x1234)
    assert runtime.read_u16(0x02000010) == 0x1234
    runtime.write_u8(0x02000010, 0x42)
    assert runtime.read_u8(0x02000010) == 0x42


def test_memory_bulk_read_write(runtime):
    runtime.write_memory(0x02001000, b"\xDE\xAD\xBE\xEF\xCA\xFE\xBA\xBE")
    assert runtime.read_memory(0x02001000, 8) == b"\xDE\xAD\xBE\xEF\xCA\xFE\xBA\xBE"


def test_unmapped_address_raises(runtime):
    with pytest.raises(ValueError):
        runtime.read_memory(0xFFFF0000, 4)


def test_missing_core_raises(test_rom, tmp_path):
    bogus = tmp_path / "nonexistent.so"
    with pytest.raises(FileNotFoundError):
        EmulatorRuntime(test_rom, core_path=bogus)
