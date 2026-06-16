"""GBA buttons + name <-> libretro id helpers.

The libretro joypad device uses a fixed set of IDs (see BUTTON_IDS in
retrokix.libretro). retrokix exposes them as a clean Enum for the runtime and the
API surface.
"""

from __future__ import annotations

from enum import IntEnum

from retrokix.libretro import BUTTON_IDS


class Button(IntEnum):
    A      = BUTTON_IDS["A"]
    B      = BUTTON_IDS["B"]
    SELECT = BUTTON_IDS["SELECT"]
    START  = BUTTON_IDS["START"]
    RIGHT  = BUTTON_IDS["RIGHT"]
    LEFT   = BUTTON_IDS["LEFT"]
    UP     = BUTTON_IDS["UP"]
    DOWN   = BUTTON_IDS["DOWN"]
    R      = BUTTON_IDS["R"]
    L      = BUTTON_IDS["L"]


def button_from_str(name: str) -> Button:
    try:
        return Button[name.upper()]
    except KeyError as exc:
        raise ValueError(f"unknown button: {name!r}") from exc
