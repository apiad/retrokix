"""Tests for the Button enum + name mapping."""

from __future__ import annotations

import pytest

from retrokix.input import Button, button_from_str
from retrokix.runtime import EmulatorRuntime


def test_button_enum_covers_ten_gba_buttons():
    names = {b.name for b in Button}
    assert names == {
        "A", "B", "SELECT", "START",
        "RIGHT", "LEFT", "UP", "DOWN",
        "R", "L",
    }


def test_button_from_str_is_case_insensitive():
    assert button_from_str("a") == Button.A
    assert button_from_str("A") == Button.A
    assert button_from_str("StArT") == Button.START
    assert button_from_str("right") == Button.RIGHT


def test_button_from_str_rejects_unknown():
    with pytest.raises(ValueError):
        button_from_str("turbo")
    with pytest.raises(ValueError):
        button_from_str("")


def test_set_and_get_buttons(test_rom, mgba_core):
    with EmulatorRuntime(test_rom, core_path=mgba_core) as rt:
        assert rt.buttons_held() == set()
        rt.set_buttons({Button.A, Button.RIGHT})
        assert rt.buttons_held() == {Button.A, Button.RIGHT}
        rt.set_buttons(set())
        assert rt.buttons_held() == set()


def test_buttons_persist_across_steps(test_rom, mgba_core):
    with EmulatorRuntime(test_rom, core_path=mgba_core) as rt:
        rt.set_buttons({Button.START})
        rt.step(frames=2)
        assert rt.buttons_held() == {Button.START}
