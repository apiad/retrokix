"""Tests for the Pokédex caught/seen overlay in PokedexPane."""
from __future__ import annotations

from retrokix.plugin import Plugin
from retrokix.tui.app import RetrokixTUI, TabContext
from retrokix.tui.pokedex_widget import PokedexPane
from retrokix.tui.status import StatusSnapshot


def test_marker_reflects_caught_seen_unknown():
    pane = PokedexPane()
    pane._dex = {"caught": {6}, "seen": {1, 6}}
    assert pane._marker(6) == "✓"  # Charizard (national 6) caught
    assert pane._marker(1) == "·"  # Bulbasaur (national 1) seen-only
    assert pane._marker(4) == " "  # Charmander (national 4) not seen


def test_marker_blank_without_dex():
    pane = PokedexPane()
    assert pane._dex is None
    assert pane._marker(6) == " "


def _pokedex_plugin() -> Plugin:
    p = Plugin()

    @p.tab("Pokédex")
    def make(ctx):
        return PokedexPane(ctx)

    return p


async def test_overlay_renders_completion_count():
    app = RetrokixTUI(StatusSnapshot(), _pokedex_plugin().tabs, TabContext())
    async with app.run_test():
        pane = app.query_one(PokedexPane)
        pane._dex = {"caught": {1, 2, 3}, "seen": {1, 2, 3, 4}}
        pane._refresh_status()
        pane.apply_query("")
        status = str(app.query_one("#pokedex-status").render())
        assert "Caught" in status
        assert "3/386" in status
