"""Smoke + live tests for PartyPane."""
from __future__ import annotations

from pathlib import Path

import pytest
from textual.app import App, ComposeResult
from textual.widgets import DataTable

from retrokix.tui.party_widget import PartyPane


class _Host(App):
    def __init__(self, pane: PartyPane) -> None:
        super().__init__()
        self._pane = pane

    def compose(self) -> ComposeResult:
        yield self._pane


def _slot(i: int, name: str) -> dict:
    return {
        "slot": i, "species": 1, "species_name": name, "level": 10,
        "hp": 30, "max_hp": 40, "exp_into_level": 1, "exp_level_span": 4,
        "exp_to_next_level": 100, "status": "OK", "next_move": None,
        "next_evolution": None,
    }


async def test_party_pane_renders_rows(monkeypatch):
    slots = [_slot(0, "Torchic"), _slot(1, "Mudkip")]
    monkeypatch.setattr(
        "retrokix.tui.party_widget.read_slot",
        lambda rt, i: slots[i] if i < len(slots) else None,
    )
    ctx = type("C", (), {"runtime": object()})()
    app = _Host(PartyPane(ctx))
    async with app.run_test():
        table = app.query_one("#party-table", DataTable)
        assert table.row_count == 2


async def test_party_pane_empty_without_runtime():
    app = _Host(PartyPane(ctx=None))
    async with app.run_test():
        assert app.query_one("#party-table", DataTable).row_count == 0
        assert app.query_one("#party-empty").display is True


# ---- live empirical ----

ROM = Path.home() / ".retrokix/roms/Pokemon - Emerald Version (USA, Europe).gba"
STATE = (
    Path.home()
    / ".retrokix/saves/f3ae088181bf583e55daf962a92bb46f4f1d07b7/slot-1.state"
)


@pytest.mark.skipif(
    not (ROM.exists() and STATE.exists()), reason="Emerald ROM + save not present"
)
async def test_party_pane_live_shows_known_party():
    from retrokix.runtime import EmulatorRuntime

    rt = EmulatorRuntime(ROM)
    try:
        rt.load_state_from_file(STATE)
        rt.step(2)
        ctx = type("C", (), {"runtime": rt})()
        app = _Host(PartyPane(ctx))
        async with app.run_test():
            table = app.query_one("#party-table", DataTable)
            assert table.row_count == 6
            names = {str(table.get_cell_at((r, 1))) for r in range(table.row_count)}
            assert {"Marill", "Combusken", "Abra"} <= names
    finally:
        rt.close()
