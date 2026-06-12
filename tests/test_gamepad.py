"""Unit tests for the gamepad input decoder.

Exercise PadManager.handle_button / handle_axis on a synthetic held
set without spinning up an SDL window or a real controller.
"""

from __future__ import annotations

import sdl2

from gbax.input import Button
from gbax.render.gamepad import (
    STICK_DEADZONE,
    TRIGGER_THRESHOLD,
    PadManager,
    _PadState,
    default_padmap,
    pad_button_slot,
)


# ----- default mapping --------------------------------------------

def test_default_padmap_covers_all_gba_buttons():
    """Every GBA button has a pad source. (The keyboard equivalent
    must be reachable from the pad too — no orphans.)"""
    mapped = set(default_padmap().values())
    assert mapped == {
        Button.A, Button.B, Button.L, Button.R,
        Button.START, Button.SELECT,
        Button.UP, Button.DOWN, Button.LEFT, Button.RIGHT,
    }


def test_pad_button_slot_uses_PAD_prefix():
    assert pad_button_slot(sdl2.SDL_CONTROLLER_BUTTON_A) == "PAD_A"
    assert pad_button_slot(sdl2.SDL_CONTROLLER_BUTTON_LEFTSHOULDER) == "PAD_L1"
    assert pad_button_slot(sdl2.SDL_CONTROLLER_BUTTON_DPAD_UP) == "PAD_DPAD_UP"
    # Guide button intentionally unbound
    assert pad_button_slot(sdl2.SDL_CONTROLLER_BUTTON_GUIDE) is None


# ----- button events ----------------------------------------------

def test_handle_button_press_adds_to_held():
    pm = PadManager()
    held: set[Button] = set()
    pm.handle_button(0, sdl2.SDL_CONTROLLER_BUTTON_A, True, held)
    assert held == {Button.A}


def test_handle_button_release_discards_from_held():
    pm = PadManager()
    held: set[Button] = {Button.A}
    pm.handle_button(0, sdl2.SDL_CONTROLLER_BUTTON_A, False, held)
    assert held == set()


def test_handle_button_unmapped_does_not_touch_held():
    pm = PadManager()
    held: set[Button] = set()
    # X is intentionally unbound for v1
    pm.handle_button(0, sdl2.SDL_CONTROLLER_BUTTON_X, True, held)
    assert held == set()


def test_handle_button_fires_plugin_slot():
    fired: list[tuple[str, bool]] = []
    pm = PadManager(on_plugin_slot=lambda slot, down: fired.append((slot, down)))
    held: set[Button] = set()
    pm.handle_button(0, sdl2.SDL_CONTROLLER_BUTTON_A, True, held)
    pm.handle_button(0, sdl2.SDL_CONTROLLER_BUTTON_A, False, held)
    assert fired == [("PAD_A", True), ("PAD_A", False)]


# ----- analog stick → dpad ----------------------------------------

def test_left_stick_crossing_deadzone_presses_dpad():
    pm = PadManager()
    held: set[Button] = set()
    pm._open[7] = (object(), _PadState())  # type: ignore[arg-type]
    pm.handle_axis(7, sdl2.SDL_CONTROLLER_AXIS_LEFTX, STICK_DEADZONE + 100, held)
    assert held == {Button.RIGHT}


def test_left_stick_inside_deadzone_no_press():
    pm = PadManager()
    held: set[Button] = set()
    pm._open[7] = (object(), _PadState())  # type: ignore[arg-type]
    pm.handle_axis(7, sdl2.SDL_CONTROLLER_AXIS_LEFTX, STICK_DEADZONE - 1, held)
    assert held == set()


def test_left_stick_reversing_swaps_dpad_press():
    pm = PadManager()
    held: set[Button] = set()
    pm._open[7] = (object(), _PadState())  # type: ignore[arg-type]
    pm.handle_axis(7, sdl2.SDL_CONTROLLER_AXIS_LEFTX, +20000, held)
    assert held == {Button.RIGHT}
    pm.handle_axis(7, sdl2.SDL_CONTROLLER_AXIS_LEFTX, -20000, held)
    assert held == {Button.LEFT}, "old direction should be released first"


def test_left_stick_returning_to_center_releases_dpad():
    pm = PadManager()
    held: set[Button] = set()
    pm._open[7] = (object(), _PadState())  # type: ignore[arg-type]
    pm.handle_axis(7, sdl2.SDL_CONTROLLER_AXIS_LEFTX, +20000, held)
    pm.handle_axis(7, sdl2.SDL_CONTROLLER_AXIS_LEFTX, 0, held)
    assert held == set()


def test_y_axis_up_press_uses_negative_sign():
    """SDL convention: Y axis is negative when stick is up."""
    pm = PadManager()
    held: set[Button] = set()
    pm._open[7] = (object(), _PadState())  # type: ignore[arg-type]
    pm.handle_axis(7, sdl2.SDL_CONTROLLER_AXIS_LEFTY, -20000, held)
    assert held == {Button.UP}


# ----- triggers ---------------------------------------------------

def test_left_trigger_above_threshold_fires_fast_forward_on():
    calls: list[bool] = []
    pm = PadManager(on_fast_forward=calls.append)
    held: set[Button] = set()
    pm._open[7] = (object(), _PadState())  # type: ignore[arg-type]
    pm.handle_axis(7, sdl2.SDL_CONTROLLER_AXIS_TRIGGERLEFT, TRIGGER_THRESHOLD + 1, held)
    assert calls == [True]


def test_left_trigger_release_fires_fast_forward_off():
    calls: list[bool] = []
    pm = PadManager(on_fast_forward=calls.append)
    held: set[Button] = set()
    pm._open[7] = (object(), _PadState())  # type: ignore[arg-type]
    pm.handle_axis(7, sdl2.SDL_CONTROLLER_AXIS_TRIGGERLEFT, TRIGGER_THRESHOLD + 1, held)
    pm.handle_axis(7, sdl2.SDL_CONTROLLER_AXIS_TRIGGERLEFT, 0, held)
    assert calls == [True, False]


def test_left_trigger_no_callback_no_crash():
    """Decoding works even without a fast-forward sink registered."""
    pm = PadManager(on_fast_forward=None)
    held: set[Button] = set()
    pm._open[7] = (object(), _PadState())  # type: ignore[arg-type]
    pm.handle_axis(7, sdl2.SDL_CONTROLLER_AXIS_TRIGGERLEFT, TRIGGER_THRESHOLD + 1, held)


# ----- right stick / right trigger unbound ------------------------

def test_right_stick_axis_does_not_touch_held():
    pm = PadManager()
    held: set[Button] = set()
    pm._open[7] = (object(), _PadState())  # type: ignore[arg-type]
    pm.handle_axis(7, sdl2.SDL_CONTROLLER_AXIS_RIGHTX, 30000, held)
    pm.handle_axis(7, sdl2.SDL_CONTROLLER_AXIS_RIGHTY, -30000, held)
    assert held == set()


def test_right_trigger_does_not_fire_fast_forward():
    calls: list[bool] = []
    pm = PadManager(on_fast_forward=calls.append)
    held: set[Button] = set()
    pm._open[7] = (object(), _PadState())  # type: ignore[arg-type]
    pm.handle_axis(7, sdl2.SDL_CONTROLLER_AXIS_TRIGGERRIGHT, 30000, held)
    assert calls == []
