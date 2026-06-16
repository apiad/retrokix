"""Tests for the cheat hotkey pin system."""

from __future__ import annotations

import pytest

from retrokix import pins as pins_module
from retrokix.cheats import Cheat
from retrokix.runtime import EmulatorRuntime


def test_load_returns_empty_when_no_file(tmp_path):
    assert pins_module.load("deadbeef", pins_dir=tmp_path) == {}


def test_save_and_load_roundtrip(tmp_path):
    pins_module.save("aaa", {"F1": "max-money", "F3": "walk"}, pins_dir=tmp_path)
    loaded = pins_module.load("aaa", pins_dir=tmp_path)
    assert loaded == {"F1": "max-money", "F3": "walk"}


def test_save_filters_invalid_keys(tmp_path):
    pins_module.save("aaa", {"F1": "ok", "F99": "bad", "garbage": "no"}, pins_dir=tmp_path)
    assert pins_module.load("aaa", pins_dir=tmp_path) == {"F1": "ok"}


def test_set_pin_persists(tmp_path):
    pins_module.set_pin("aaa", "F2", "infinite-hp", pins_dir=tmp_path)
    pins_module.set_pin("aaa", "F7", "walk-through-walls", pins_dir=tmp_path)
    assert pins_module.load("aaa", pins_dir=tmp_path) == {
        "F2": "infinite-hp",
        "F7": "walk-through-walls",
    }


def test_unset_pin(tmp_path):
    pins_module.set_pin("aaa", "F1", "a", pins_dir=tmp_path)
    pins_module.set_pin("aaa", "F2", "b", pins_dir=tmp_path)
    pins_module.unset_pin("aaa", "F1", pins_dir=tmp_path)
    assert pins_module.load("aaa", pins_dir=tmp_path) == {"F2": "b"}


def test_invalid_key_rejected(tmp_path):
    with pytest.raises(ValueError):
        pins_module.set_pin("aaa", "F12", "anything", pins_dir=tmp_path)
    with pytest.raises(ValueError):
        pins_module.set_pin("aaa", "ctrl+x", "anything", pins_dir=tmp_path)


def test_runtime_loads_pins_for_rom(test_rom, mgba_core, tmp_path, monkeypatch):
    """EmulatorRuntime hydrates _pins from disk on construction."""
    import hashlib
    rom_sha1 = hashlib.sha1(test_rom.read_bytes()).hexdigest()
    monkeypatch.setattr(pins_module, "DEFAULT_PINS_DIR", tmp_path)
    pins_module.set_pin(rom_sha1, "F4", "some-cheat")

    rt = EmulatorRuntime(test_rom, core_path=mgba_core)
    try:
        assert rt.cheat_pins() == {"F4": "some-cheat"}
    finally:
        rt.close()


def test_runtime_set_and_unset_pin(test_rom, mgba_core, tmp_path, monkeypatch):
    """set/unset go through to disk and to the in-memory map."""
    import hashlib

    monkeypatch.setattr(pins_module, "DEFAULT_PINS_DIR", tmp_path)
    rom_sha1 = hashlib.sha1(test_rom.read_bytes()).hexdigest()

    rt = EmulatorRuntime(test_rom, core_path=mgba_core)
    try:
        rt._cheat_catalog = [Cheat(name="Max Money", code="000")]
        rt.set_cheat_pin("F1", "max-money")

        # In-memory state updated
        assert rt.cheat_pins()["F1"] == "max-money"
        # Disk state updated (skip the libretro-global-state hazard of opening a second core)
        assert pins_module.load(rom_sha1, pins_dir=tmp_path) == {"F1": "max-money"}

        rt.unset_cheat_pin("F1")
        assert "F1" not in rt.cheat_pins()
        assert pins_module.load(rom_sha1, pins_dir=tmp_path) == {}
    finally:
        rt.close()
