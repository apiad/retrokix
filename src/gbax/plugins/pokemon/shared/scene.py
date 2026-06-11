"""Scene / battle-phase detection.

Interim implementation reads the empirically-discovered battle phase byte
at 0x02024332 (gBattleCommunication[MULTIUSE_STATE]). Slice 2 will add a
gMain.callback2 reader for unambiguous screen identity (see the post-mortem
in the suite spec).
"""
from __future__ import annotations

import struct

from gbax.plugins.pokemon.shared.addresses import (
    BATTLE_PHASE_ADDR, GBATTLE_TYPE_FLAGS,
)


# Mapping of byte values at 0x02024332 — empirical, ambiguous in places.
#   0 = wild encounter intro / send-out animation
#   1 = trainer "is about to use X" announce OR party menu / SHIFT submenu
#   2 = action menu (FIGHT/BAG/PKMN/RUN)
#   3 = secondary menu (move menu OR party menu)
#   5 = generic: text scroll, animation, Yes/No, out-of-battle, outro
#   6 = transition (closing menu / UI rebuild)
PHASE_WILD_INTRO = 0
PHASE_TRAINER_ANNOUNCE = 1
PHASE_ACTION_MENU = 2
PHASE_SECONDARY_MENU = 3
PHASE_GENERIC = 5
PHASE_TRANSITION = 6

PHASE_NAMES = {
    PHASE_WILD_INTRO: "wild_intro",
    PHASE_TRAINER_ANNOUNCE: "trainer_announce",
    PHASE_ACTION_MENU: "action_menu",
    PHASE_SECONDARY_MENU: "secondary_menu",
    PHASE_GENERIC: "generic",
    PHASE_TRANSITION: "transition",
}

INTERACTIVE_PHASES = {PHASE_ACTION_MENU, PHASE_SECONDARY_MENU}
ADVANCEABLE_PHASES = {PHASE_WILD_INTRO, PHASE_TRAINER_ANNOUNCE, PHASE_GENERIC}
WAIT_PHASES = {PHASE_TRANSITION}


def in_battle(runtime) -> bool:
    """gBattleTypeFlags non-zero ⇒ currently in a battle."""
    flags = struct.unpack("<I", runtime.read_memory(GBATTLE_TYPE_FLAGS, 4))[0]
    return 0 < flags < 0x01000000


def battle_phase(runtime) -> tuple[int, str]:
    raw = runtime.read_memory(BATTLE_PHASE_ADDR, 1)[0]
    name = PHASE_NAMES.get(raw, f"unknown:{raw}")
    return raw, name


def phase_raw(runtime) -> int:
    return runtime.read_memory(BATTLE_PHASE_ADDR, 1)[0]
