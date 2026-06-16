"""SDL2 gamepad support for the `retrokix play` loop.

SDL's `SDL_GameController` API maps any pad it recognizes (XInput,
DualShock/DualSense, 8BitDo, Steam Controller, generic clones) to a
common A/B/X/Y/L1/R1/dpad/sticks/triggers layout via the community
mapping DB shipped with the SDL2 binary. We hook those normalized
buttons to the GBA's 10-button input layer.

What ships:
- Default mapping (see DEFAULT_PADMAP) covers A/B/L/R/Start/Select/dpad.
- Left analog stick → digital D-pad with a 25% deadzone.
- Left trigger (LT/L2) → fast-forward, mirroring keyboard's L-Shift.
- All connected pads share one input bus (set-union into `held`),
  matching how retrokix already merges keyboard + agent HTTP inputs.
- Hot-plug: pads added/removed mid-session register/unregister live.
- Plugin `on_key` handlers fire on synthetic slot names — `PAD_A`,
  `PAD_B`, `PAD_L1`, `PAD_R1`, `PAD_START`, `PAD_SELECT`,
  `PAD_DPAD_UP`, etc. — so the existing decorator extends naturally.

What's intentionally unbound for v1: X/Y face buttons, right stick,
right trigger, guide button. Reserved for hotkeys later.
"""

from __future__ import annotations

from dataclasses import dataclass, field
from typing import TYPE_CHECKING, Callable

import sdl2

from retrokix.input import Button

if TYPE_CHECKING:
    pass


# ----- tunables ----------------------------------------------------

#: Magnitude on a stick axis (range -32768..32767) below which we treat
#: the stick as centered. SDL's docs recommend ~25% of full range.
STICK_DEADZONE = 8000

#: Threshold on trigger axis (range 0..32767) above which the trigger
#: counts as "pressed". Light feathering should trigger fast-forward,
#: so set this below the half-press point.
TRIGGER_THRESHOLD = 12000


def default_padmap() -> dict[int, Button]:
    """SDL GameController button ID → GBA Button.

    Layout decisions (recorded in the research note):
    - A → A, B → B (face buttons; X/Y left unbound to avoid a
      "two-buttons-do-A" mental model).
    - L1 → L, R1 → R.
    - LT fast-forward is handled separately on the trigger axis.
    """
    return {
        sdl2.SDL_CONTROLLER_BUTTON_A:             Button.A,
        sdl2.SDL_CONTROLLER_BUTTON_B:             Button.B,
        sdl2.SDL_CONTROLLER_BUTTON_LEFTSHOULDER:  Button.L,
        sdl2.SDL_CONTROLLER_BUTTON_RIGHTSHOULDER: Button.R,
        sdl2.SDL_CONTROLLER_BUTTON_START:         Button.START,
        sdl2.SDL_CONTROLLER_BUTTON_BACK:          Button.SELECT,
        sdl2.SDL_CONTROLLER_BUTTON_DPAD_UP:       Button.UP,
        sdl2.SDL_CONTROLLER_BUTTON_DPAD_DOWN:     Button.DOWN,
        sdl2.SDL_CONTROLLER_BUTTON_DPAD_LEFT:     Button.LEFT,
        sdl2.SDL_CONTROLLER_BUTTON_DPAD_RIGHT:    Button.RIGHT,
    }


def pad_button_slot(sdl_button: int) -> str | None:
    """Slot name fed to plugin `on_key` handlers for pad buttons.

    Returns None for buttons we don't surface (e.g. guide).
    """
    return _SLOT_BY_BUTTON.get(sdl_button)


_SLOT_BY_BUTTON: dict[int, str] = {
    sdl2.SDL_CONTROLLER_BUTTON_A:             "PAD_A",
    sdl2.SDL_CONTROLLER_BUTTON_B:             "PAD_B",
    sdl2.SDL_CONTROLLER_BUTTON_X:             "PAD_X",
    sdl2.SDL_CONTROLLER_BUTTON_Y:             "PAD_Y",
    sdl2.SDL_CONTROLLER_BUTTON_LEFTSHOULDER:  "PAD_L1",
    sdl2.SDL_CONTROLLER_BUTTON_RIGHTSHOULDER: "PAD_R1",
    sdl2.SDL_CONTROLLER_BUTTON_START:         "PAD_START",
    sdl2.SDL_CONTROLLER_BUTTON_BACK:          "PAD_SELECT",
    sdl2.SDL_CONTROLLER_BUTTON_DPAD_UP:       "PAD_DPAD_UP",
    sdl2.SDL_CONTROLLER_BUTTON_DPAD_DOWN:     "PAD_DPAD_DOWN",
    sdl2.SDL_CONTROLLER_BUTTON_DPAD_LEFT:     "PAD_DPAD_LEFT",
    sdl2.SDL_CONTROLLER_BUTTON_DPAD_RIGHT:    "PAD_DPAD_RIGHT",
}


@dataclass
class _PadState:
    """Per-pad analog-stick state so we can synthesize D-pad
    press/release events when the stick crosses the deadzone."""

    # Direction the LEFT analog stick is currently producing.
    # ('x', 'y') axis members: -1, 0, or +1.
    stick_x: int = 0
    stick_y: int = 0
    # Whether the LT trigger is currently above TRIGGER_THRESHOLD.
    lt_pressed: bool = False


@dataclass
class PadManager:
    """Owns all open SDL GameController handles + the input state they
    drive. The play loop calls into the `handle_*` methods from its
    SDL_PollEvent dispatch.

    All connected pads share one held-button set with the keyboard and
    the HTTP API. That set-union is what gives retrokix its 'human + agent
    co-play' character; pads slot into the same model.
    """

    padmap: dict[int, Button] = field(default_factory=default_padmap)
    #: Caller-provided callback fired when LT crosses the trigger
    #: threshold (down: bool). Plumbed to fast-forward state.
    on_fast_forward: Callable[[bool], None] | None = None
    #: Caller-provided callback for plugin `on_key` dispatch on pad
    #: buttons. Signature: (slot_name, is_down).
    on_plugin_slot: Callable[[str, bool], None] | None = None

    # instance_id → (pad handle, _PadState)
    _open: dict[int, tuple[object, _PadState]] = field(default_factory=dict)

    # ----- lifecycle ------------------------------------------------

    def open_attached(self) -> list[str]:
        """Open every gamecontroller-compatible pad SDL currently sees.
        Returns the list of pad names opened, for the play-loop banner.
        """
        names: list[str] = []
        n = sdl2.SDL_NumJoysticks()
        for i in range(n):
            if not sdl2.SDL_IsGameController(i):
                continue
            name = self._open_device(i)
            if name is not None:
                names.append(name)
        return names

    def close_all(self) -> None:
        for pad, _state in self._open.values():
            sdl2.SDL_GameControllerClose(pad)
        self._open.clear()

    def _open_device(self, device_index: int) -> str | None:
        pad = sdl2.SDL_GameControllerOpen(device_index)
        if not pad:
            return None
        joystick = sdl2.SDL_GameControllerGetJoystick(pad)
        instance_id = sdl2.SDL_JoystickInstanceID(joystick)
        if instance_id < 0:
            sdl2.SDL_GameControllerClose(pad)
            return None
        self._open[instance_id] = (pad, _PadState())
        raw = sdl2.SDL_GameControllerName(pad)
        return raw.decode() if raw else f"pad #{device_index}"

    # ----- event hooks ----------------------------------------------

    def handle_device_added(
        self, device_index: int
    ) -> str | None:
        """SDL_CONTROLLERDEVICEADDED — `device_index` is the joystick
        device index (not instance ID). Returns the pad name on success."""
        if not sdl2.SDL_IsGameController(device_index):
            return None
        return self._open_device(device_index)

    def handle_device_removed(
        self, instance_id: int, held: set[Button]
    ) -> str | None:
        """SDL_CONTROLLERDEVICEREMOVED — `instance_id` is the joystick
        instance ID (NOT device index). Returns the pad name we closed,
        or None if we didn't have it.

        Any buttons this pad was holding are released so the GBA doesn't
        get stuck in mid-press."""
        entry = self._open.pop(instance_id, None)
        if entry is None:
            return None
        pad, state = entry
        name_raw = sdl2.SDL_GameControllerName(pad)
        name = name_raw.decode() if name_raw else f"pad #{instance_id}"
        # Drop any pad-driven directions from the digital D-pad map.
        if state.stick_x != 0:
            held.discard(Button.LEFT if state.stick_x < 0 else Button.RIGHT)
        if state.stick_y != 0:
            held.discard(Button.UP if state.stick_y < 0 else Button.DOWN)
        if state.lt_pressed and self.on_fast_forward is not None:
            self.on_fast_forward(False)
        sdl2.SDL_GameControllerClose(pad)
        return name

    def handle_button(
        self, instance_id: int, button: int, down: bool, held: set[Button]
    ) -> None:
        """SDL_CONTROLLERBUTTONDOWN/UP."""
        # Mutate held first so plugin handlers see the post-event state.
        gba = self.padmap.get(button)
        if gba is not None:
            if down:
                held.add(gba)
            else:
                held.discard(gba)
        slot = pad_button_slot(button)
        if slot is not None and self.on_plugin_slot is not None:
            self.on_plugin_slot(slot, down)

    def handle_axis(
        self, instance_id: int, axis: int, value: int, held: set[Button]
    ) -> None:
        """SDL_CONTROLLERAXISMOTION — value is signed -32768..32767
        for sticks, 0..32767 for triggers."""
        entry = self._open.get(instance_id)
        if entry is None:
            return
        _pad, state = entry

        if axis == sdl2.SDL_CONTROLLER_AXIS_LEFTX:
            new_x = self._axis_sign(value)
            if new_x != state.stick_x:
                # Release the old direction first, then press the new
                # one. Releasing nothing (state.stick_x == 0) is a no-op.
                if state.stick_x != 0:
                    held.discard(Button.LEFT if state.stick_x < 0 else Button.RIGHT)
                if new_x != 0:
                    held.add(Button.LEFT if new_x < 0 else Button.RIGHT)
                state.stick_x = new_x

        elif axis == sdl2.SDL_CONTROLLER_AXIS_LEFTY:
            new_y = self._axis_sign(value)
            if new_y != state.stick_y:
                if state.stick_y != 0:
                    held.discard(Button.UP if state.stick_y < 0 else Button.DOWN)
                if new_y != 0:
                    held.add(Button.UP if new_y < 0 else Button.DOWN)
                state.stick_y = new_y

        elif axis == sdl2.SDL_CONTROLLER_AXIS_TRIGGERLEFT:
            pressed = value > TRIGGER_THRESHOLD
            if pressed != state.lt_pressed:
                state.lt_pressed = pressed
                if self.on_fast_forward is not None:
                    self.on_fast_forward(pressed)

        # SDL_CONTROLLER_AXIS_RIGHTX / RIGHTY / TRIGGERRIGHT —
        # intentionally unhandled (left as future hotkey targets).

    @staticmethod
    def _axis_sign(value: int) -> int:
        if value <= -STICK_DEADZONE:
            return -1
        if value >= STICK_DEADZONE:
            return +1
        return 0
