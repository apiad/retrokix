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


# --- Mode + speed ---


def test_default_mode_is_step(runtime):
    from gbax.runtime import Mode
    assert runtime.mode == Mode.STEP


def test_mode_setter(runtime):
    from gbax.runtime import Mode
    runtime.mode = Mode.FREE
    assert runtime.mode == Mode.FREE
    runtime.mode = "step"  # string also accepted
    assert runtime.mode == Mode.STEP


def test_speed_multiplier_default_and_setter(runtime):
    assert runtime.speed_multiplier == 1.0
    runtime.speed_multiplier = 4.0
    assert runtime.speed_multiplier == 4.0
    with pytest.raises(ValueError):
        runtime.speed_multiplier = 0.0
    with pytest.raises(ValueError):
        runtime.speed_multiplier = -1.0


# --- Save state slots ---


def test_savestate_roundtrip(runtime):
    runtime.step(frames=30)
    runtime.save_state_to_slot(1)
    runtime.step(frames=30)
    assert runtime.frame_count == 60
    runtime.load_state_from_slot(1)
    assert runtime.frame_count == 30


def test_savestate_multiple_slots(runtime):
    runtime.step(frames=10)
    runtime.save_state_to_slot(1)
    runtime.step(frames=10)
    runtime.save_state_to_slot(2)
    runtime.step(frames=10)
    assert runtime.frame_count == 30
    runtime.load_state_from_slot(1)
    assert runtime.frame_count == 10
    runtime.load_state_from_slot(2)
    assert runtime.frame_count == 20


def test_savestate_invalid_slot_raises(runtime):
    with pytest.raises(ValueError):
        runtime.save_state_to_slot(0)
    with pytest.raises(ValueError):
        runtime.save_state_to_slot(10)
    with pytest.raises(KeyError):
        runtime.load_state_from_slot(5)


def test_persist_and_reload_state(test_rom, mgba_core, tmp_path):
    with EmulatorRuntime(test_rom, core_path=mgba_core, save_dir=tmp_path) as rt:
        rt.step(frames=42)
        rt.save_state_to_slot(1)
        path = rt.persist_slot_to_disk(1)
        assert path.exists()
        assert path.parent.parent == tmp_path
        assert path.parent.name == rt.rom_sha1

    # Open a fresh runtime, load the persistent slot
    with EmulatorRuntime(test_rom, core_path=mgba_core, save_dir=tmp_path) as rt2:
        rt2.load_persistent_slot(1)
        assert rt2.frame_count == 42
