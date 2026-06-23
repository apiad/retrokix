"""Live empirical regression for the Pokédex decode — keeps the SaveBlock2
addresses honest. Skipped when the Emerald ROM + savestate aren't present
(CI, other machines); runs against the real save where available.
"""
from __future__ import annotations

from pathlib import Path

import pytest

ROM = Path.home() / ".retrokix/roms/Pokemon - Emerald Version (USA, Europe).gba"
STATE = (
    Path.home()
    / ".retrokix/saves/f3ae088181bf583e55daf962a92bb46f4f1d07b7/slot-1.state"
)

pytestmark = pytest.mark.skipif(
    not (ROM.exists() and STATE.exists()),
    reason="Emerald ROM + slot-1 savestate not present",
)


def test_live_dex_contains_party_and_caught_subset_of_seen():
    from retrokix.plugins.pokemon.shared import party, pokedex
    from retrokix.plugins.pokemon.shared.pokedex_model import national_of
    from retrokix.runtime import EmulatorRuntime

    rt = EmulatorRuntime(ROM)
    try:
        rt.load_state_from_file(STATE)
        rt.step(2)
        dex = pokedex.read_dex(rt)
        assert dex is not None, "read_dex returned None on a known-good Emerald save"

        party_nats = set()
        for i in range(6):
            slot = party.read_slot(rt, i)
            if slot and slot.get("species"):
                party_nats.add(national_of(slot["species"]))

        assert party_nats, "no party species read"
        assert party_nats <= dex["caught"], "every party species must be caught"
        assert dex["caught"] <= dex["seen"], "caught must be a subset of seen"
    finally:
        rt.close()
