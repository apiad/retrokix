"""Smoke tests for the TUI shell — uses Textual's async run_test harness."""
from __future__ import annotations

from retrokix.plugin import Plugin
from retrokix.tui.app import RetrokixTUI, TabContext
from retrokix.tui.core_tab import CoreTab
from retrokix.tui.pokedex_widget import PokedexPane
from retrokix.tui.status import StatusSnapshot
from textual.widgets import TabPane


def _pokedex_plugin() -> Plugin:
    p = Plugin()

    @p.tab("Pokédex")
    def make(ctx):
        return PokedexPane(ctx)

    return p


async def test_app_mounts_core_and_plugin_tabs():
    app = RetrokixTUI(StatusSnapshot(), _pokedex_plugin().tabs, TabContext())
    async with app.run_test():
        assert app.query_one("#tab-core", TabPane) is not None
        assert app.query_one(PokedexPane) is not None


async def test_app_polls_status_into_core_tab():
    snap = StatusSnapshot()
    snap.publish(title="Zelda Minish Cap")
    app = RetrokixTUI(snap, [], TabContext())
    async with app.run_test() as pilot:
        await pilot.pause()
        rendered = str(app.query_one("#core-status").render())
        assert "Zelda Minish Cap" in rendered


async def test_broken_plugin_tab_is_skipped_not_fatal():
    p = Plugin()

    @p.tab("Boom")
    def make(ctx):
        raise RuntimeError("kaboom")

    app = RetrokixTUI(StatusSnapshot(), p.tabs, TabContext())
    async with app.run_test():
        # Core tab still present; the broken tab was skipped.
        assert app.query_one(CoreTab) is not None
        assert not app.query("#tab-plugin-0")


async def test_pokedex_tab_filters_species():
    app = RetrokixTUI(StatusSnapshot(), _pokedex_plugin().tabs, TabContext())
    async with app.run_test():
        pane = app.query_one(PokedexPane)
        assert pane.apply_query("") == 386
        assert pane.apply_query("char") == 3
