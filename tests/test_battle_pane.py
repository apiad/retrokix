"""Tests for the Battle panel formatters + pane (single + double)."""
from __future__ import annotations

from pathlib import Path

import pytest
from textual.app import App, ComposeResult

from retrokix.tui.battle_widget import BattlePane, best_counter, format_battle, format_weaknesses

# Magnemite = Electric(13)/Steel(8) → weak to Fire(10), Fighting(1), Ground(4) ×2.
_MAGNEMITE = {"species_name": "Magnemite", "level": 17, "hp": 20, "max_hp": 37, "types": [13, 8]}
_VOLBEAT = {"species_name": "Volbeat", "level": 17, "hp": 0, "max_hp": 51, "types": [6, 6]}


def test_weaknesses_for_dual_type():
    s = format_weaknesses([13, 8])  # Magnemite
    assert "Fire" in s and "Ground" in s and "Fighting" in s


def test_weaknesses_dedupes_mono_type():
    # Volbeat is mono-Bug stored as [6, 6]; weaknesses must not be squared.
    s = format_weaknesses([6, 6])
    assert "×4" not in s  # mono-type can't have a ×4 weakness


def test_best_counter_picks_super_effective_move():
    # A party mon with a Flying move (Peck) vs a Fighting opponent (type 1).
    party = [{"species_name": "Combusken", "moves": [
        {"name": "Scratch", "type": "NORMAL", "power": 40},
        {"name": "Peck", "type": "FLYING", "power": 35},
    ]}]
    bc = best_counter(party, [1])  # Fighting
    assert bc is not None
    assert bc["pokemon"] == "Combusken"
    assert bc["move"] == "Peck"
    assert bc["mul"] == 2.0


def test_best_counter_none_when_no_advantage():
    party = [{"species_name": "X", "moves": [{"name": "Tackle", "type": "NORMAL", "power": 40}]}]
    assert best_counter(party, [1]) is None  # Normal not SE vs Fighting


def test_format_battle_lists_active_and_team():
    out = format_battle([_VOLBEAT, _MAGNEMITE], [_VOLBEAT, _MAGNEMITE], is_double_flag=True)
    assert "Magnemite" in out
    assert "Volbeat" in out
    assert "Weak" in out
    assert "Opponent team" in out


class _Host(App):
    def __init__(self, pane):
        super().__init__()
        self._pane = pane

    def compose(self) -> ComposeResult:
        yield self._pane


async def test_battle_pane_empty_without_runtime():
    app = _Host(BattlePane(ctx=None))
    async with app.run_test():
        assert app.query_one("#battle-empty").display is True


# ---- live empirical ----

ROM = Path.home() / ".retrokix/roms/Pokemon - Emerald Version (USA, Europe).gba"
_SAVES = Path.home() / ".retrokix/saves/f3ae088181bf583e55daf962a92bb46f4f1d07b7"
DOUBLE = _SAVES / "running/running-2026-06-22T01-50-49.083Z.state"
TOWN = _SAVES / "slot-1.state"


@pytest.mark.skipif(
    not (ROM.exists() and DOUBLE.exists()), reason="Emerald ROM + battle save not present"
)
def test_live_double_battle_two_opponents_and_team():
    from retrokix.plugins.pokemon.shared import battle as B
    from retrokix.runtime import EmulatorRuntime

    rt = EmulatorRuntime(ROM)
    try:
        rt.load_state_from_file(DOUBLE)
        rt.step(1)
        assert B.is_in_battle(rt) is True
        assert B.is_double(rt) is True
        opp = B.active_opponents(rt)
        assert len(opp) == 2  # both on-field opponents
        team = B.enemy_party(rt)
        assert len(team) >= 2  # full opponent party
        rt.load_state_from_file(TOWN)
        rt.step(1)
        assert B.is_in_battle(rt) is False
    finally:
        rt.close()
