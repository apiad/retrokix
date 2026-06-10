"""Tests for the gbax.macros persistence layer."""
from __future__ import annotations

from datetime import datetime, timezone

import pytest

from gbax.input import Button
from gbax.macros import Macro, delete, list_for_rom, load, macros_dir_for_rom, save


SHA1 = "f3ae088181bf583e55daf962a92bb46f4f1d07b7"


def _sample_macro(slot: str = "F3", name: str = "heal-pc") -> Macro:
    return Macro(
        slot=slot,
        name=name,
        rom_sha1=SHA1,
        rom_name="Pokemon - Emerald Version (USA, Europe).gba",
        recorded_at=datetime(2026, 6, 9, 23, 14, 0, tzinfo=timezone.utc),
        total_frames=124,
        events=[
            (0, frozenset()),
            (3, frozenset({Button.A})),
            (5, frozenset()),
            (27, frozenset({Button.DOWN})),
            (29, frozenset()),
        ],
    )


def test_round_trip_save_load(tmp_path):
    m = _sample_macro()
    save(m, macros_root=tmp_path)
    loaded = load(SHA1, "F3", macros_root=tmp_path)
    assert loaded is not None
    assert loaded.slot == "F3"
    assert loaded.name == "heal-pc"
    assert loaded.total_frames == 124
    assert loaded.events == m.events


def test_load_missing_returns_none(tmp_path):
    assert load(SHA1, "F3", macros_root=tmp_path) is None


def test_load_malformed_returns_none(tmp_path):
    d = macros_dir_for_rom(SHA1, macros_root=tmp_path)
    d.mkdir(parents=True)
    (d / "F3.json").write_text("not valid json {{{")
    assert load(SHA1, "F3", macros_root=tmp_path) is None


def test_list_returns_sorted_by_slot(tmp_path):
    save(_sample_macro("F5", "second"), macros_root=tmp_path)
    save(_sample_macro("F3", "first"), macros_root=tmp_path)
    listed = list_for_rom(SHA1, macros_root=tmp_path)
    assert [m.slot for m in listed] == ["F3", "F5"]
    assert [m.name for m in listed] == ["first", "second"]


def test_delete_removes_file(tmp_path):
    save(_sample_macro(), macros_root=tmp_path)
    assert load(SHA1, "F3", macros_root=tmp_path) is not None
    deleted = delete(SHA1, "F3", macros_root=tmp_path)
    assert deleted is True
    assert load(SHA1, "F3", macros_root=tmp_path) is None


def test_delete_missing_returns_false(tmp_path):
    assert delete(SHA1, "F3", macros_root=tmp_path) is False


def test_invalid_slot_raises(tmp_path):
    m = _sample_macro(slot="F12")
    with pytest.raises(ValueError):
        save(m, macros_root=tmp_path)
