"""Tests for the Trainer panel formatters + pane."""
from __future__ import annotations

from pathlib import Path

import pytest
from textual.app import App, ComposeResult

from retrokix.tui.trainer_widget import TrainerPane, format_bag, format_trainer_header

_WORLD = {
    "trainer": {"name": "ALEX", "id": 31742, "gender": "M"},
    "money": 8920,
    "badges": {"count": 1, "list": [True] + [False] * 7},
    "play_time": {"h": 16, "m": 40, "s": 10},
}
_BAG = {
    "Balls": [{"id": 4, "name": "Poke-Ball", "qty": 3}, {"id": 3, "name": "Great-Ball", "qty": 2}],
    "Items": [{"id": 13, "name": "Potion", "qty": 2}],
    "Key": [],
    "TMs": [],
    "Berries": [],
}


def test_header_has_all_fields():
    s = format_trainer_header(_WORLD)
    assert "ALEX" in s
    assert "31742" in s
    assert "8,920" in s
    assert "1/8" in s
    assert "16h40m" in s


def test_bag_groups_nonempty_pockets():
    s = format_bag(_BAG)
    assert "Balls" in s
    assert "Poke-Ball ×3" in s
    assert "Great-Ball ×2" in s
    assert "Potion ×2" in s


def test_bag_empty():
    assert "empty" in format_bag({"Balls": [], "Items": []}).lower()


class _Host(App):
    def __init__(self, pane):
        super().__init__()
        self._pane = pane

    def compose(self) -> ComposeResult:
        yield self._pane


async def test_trainer_pane_empty_without_runtime():
    app = _Host(TrainerPane(ctx=None))
    async with app.run_test():
        assert app.query_one("#trainer-empty").display is True


# ---- live empirical ----

ROM = Path.home() / ".retrokix/roms/Pokemon - Emerald Version (USA, Europe).gba"
STATE = (
    Path.home()
    / ".retrokix/saves/f3ae088181bf583e55daf962a92bb46f4f1d07b7/slot-1.state"
)


@pytest.mark.skipif(
    not (ROM.exists() and STATE.exists()), reason="Emerald ROM + save not present"
)
def test_world_bag_live():
    from retrokix.plugins.pokemon.shared import bag, world
    from retrokix.runtime import EmulatorRuntime

    rt = EmulatorRuntime(ROM)
    try:
        rt.load_state_from_file(STATE)
        rt.step(2)
        w = world.read_world(rt)
        b = bag.read_bag(rt)
        assert w is not None and b is not None
        assert 0 < w["money"] <= 999999
        assert w["trainer"]["name"].isalpha()
        assert w["badges"]["count"] >= 1
        ball_names = {i["name"] for i in b["Balls"]}
        assert "Poke-Ball" in ball_names
    finally:
        rt.close()
