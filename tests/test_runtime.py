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


def test_save_to_slot_auto_persists(test_rom, mgba_core, tmp_path):
    """Pressing 1-9 in `play` writes to disk immediately, without needing Ctrl+S."""
    with EmulatorRuntime(test_rom, core_path=mgba_core, save_dir=tmp_path) as rt:
        rt.step(frames=17)
        rt.save_state_to_slot(3)
        # File appeared on disk without persist_slot_to_disk being called
        slot_file = tmp_path / rt.rom_sha1 / "slot-3.state"
        assert slot_file.exists()


def test_running_save_writes_timestamped_file(test_rom, mgba_core, tmp_path):
    """Ctrl+S equivalent — every call writes a new running-*.state with
    a sidecar JSON and never overwrites."""
    with EmulatorRuntime(test_rom, core_path=mgba_core, save_dir=tmp_path) as rt:
        rt.step(frames=10)
        p1 = rt.save_state_running()
        rt.step(frames=10)
        p2 = rt.save_state_running()

    assert p1 != p2
    assert p1.exists() and p2.exists()
    assert p1.name.startswith("running-") and p1.suffix == ".state"
    assert p1.with_suffix(".json").exists()
    assert p2.with_suffix(".json").exists()


def test_latest_running_save_returns_newest_or_none(test_rom, mgba_core, tmp_path):
    """Empty stream → None; after a save it's the path; after a second,
    the newer one wins."""
    with EmulatorRuntime(test_rom, core_path=mgba_core, save_dir=tmp_path) as rt:
        assert rt.latest_running_save() is None
        rt.step(frames=5)
        a = rt.save_state_running()
        assert rt.latest_running_save() == a
        rt.step(frames=5)
        b = rt.save_state_running()
        assert rt.latest_running_save() == b


def test_load_state_from_file_restores_frame_count(test_rom, mgba_core, tmp_path):
    """Ctrl+L equivalent — load from any path; sidecar JSON restores
    frame_count so plugins/macros pick up where the save left off."""
    with EmulatorRuntime(test_rom, core_path=mgba_core, save_dir=tmp_path) as rt:
        rt.step(frames=42)
        path = rt.save_state_running()
        rt.step(frames=100)  # advance past the save
        assert rt.frame_count == 142
        rt.load_state_from_file(path)
        assert rt.frame_count == 42


def test_load_state_from_file_without_sidecar_defaults_frame_count_zero(test_rom, mgba_core, tmp_path):
    """A standalone .state (no .json sidecar) still loads cleanly;
    frame_count just resets to 0. Covers `gbax play --load <path>` for
    files copied from elsewhere."""
    with EmulatorRuntime(test_rom, core_path=mgba_core, save_dir=tmp_path) as rt:
        rt.step(frames=7)
        blob = rt.export_state()

    bare = tmp_path / "exported.state"
    bare.write_bytes(blob)
    with EmulatorRuntime(test_rom, core_path=mgba_core, save_dir=tmp_path) as rt2:
        rt2.load_state_from_file(bare)
        # No sidecar so frame_count defaults to 0.
        assert rt2.frame_count == 0


def test_slots_hydrate_on_construction(test_rom, mgba_core, tmp_path):
    """Slots saved in one session are in-memory on the next, so Shift+1-9 works."""
    with EmulatorRuntime(test_rom, core_path=mgba_core, save_dir=tmp_path) as rt:
        rt.step(frames=23)
        rt.save_state_to_slot(5)

    with EmulatorRuntime(test_rom, core_path=mgba_core, save_dir=tmp_path) as rt2:
        # Without explicitly calling load_persistent_slot, slot 5 is available
        rt2.load_state_from_slot(5)
        assert rt2.frame_count == 23


# --- Free-run ticker ---


def test_free_run_ticker_advances(runtime):
    import time
    runtime.start_free_run_ticker()
    try:
        time.sleep(0.5)
        fc = runtime.frame_count
        # 0.5s at 60fps → ~30 frames; allow wide margin for CI jitter
        assert 10 <= fc <= 60, f"expected ~30 frames in 0.5s, got {fc}"
    finally:
        runtime.stop_free_run_ticker()


def test_free_run_ticker_speed_multiplier(runtime):
    import time
    runtime.speed_multiplier = 4.0
    runtime.start_free_run_ticker()
    try:
        time.sleep(0.5)
        fc = runtime.frame_count
        # 0.5s at 240fps → ~120 frames; pad heavily for slow CI
        assert fc >= 50, f"expected many frames in 0.5s at 4x, got {fc}"
    finally:
        runtime.stop_free_run_ticker()


# ---------- multi-console (NES + GBA) ----------

def test_system_av_info_reports_gba_geometry(runtime):
    """mGBA reports 240x160 at native 16:10 aspect.

    libretro lets cores leave `aspect_ratio` zero ("compute from base");
    mGBA fills it in. Either way the base dimensions are exact."""
    av = runtime.system_av_info()
    assert av["base_width"] == 240
    assert av["base_height"] == 160
    assert av["aspect_ratio"] in (0.0, av["base_width"] / av["base_height"])


def test_runtime_console_property_is_gba_for_gba_rom(runtime, test_rom):
    """Runtime infers the console slug from the ROM extension."""
    # test_rom is a .gba fixture so should slot in as 'gba'.
    assert runtime.console == "gba"


def test_default_core_path_picks_console_specific_core(tmp_path):
    """A .nes ROM path resolves to fceumm_libretro.so (whether or not
    that core happens to exist on this dev machine — _default_core_path
    returns the *expected* location)."""
    from gbax.runtime import _default_core_path

    nes_rom = tmp_path / "fake.nes"
    nes_rom.write_bytes(b"NES\x1a")  # iNES magic — not booted, just file ext
    path = _default_core_path(nes_rom)
    assert path.name == "fceumm_libretro.so"

    gba_rom = tmp_path / "fake.gba"
    gba_rom.write_bytes(b"\x00" * 16)
    path = _default_core_path(gba_rom)
    assert path.name == "mgba_libretro.so"
