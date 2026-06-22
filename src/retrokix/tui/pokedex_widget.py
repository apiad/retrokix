"""PokedexPane — the Textual widget for the Pokédex tab.

Thin presentation over ``pokedex_model``: a search box, a species list, and a
detail pane. All search/filter/detail logic lives in the model (pure, tested);
this widget only wires Textual events to it. The model functions never touch a
ROM, save, or the network, so the tab works with or without a running game.
"""

from __future__ import annotations

from textual.app import ComposeResult
from textual.containers import Horizontal, VerticalScroll
from textual.widgets import Input, Label, ListItem, ListView, Static

from retrokix.plugins.pokemon.shared import pokedex_model as M


class PokedexPane(Static):
    """Two-pane master/detail Pokédex browser."""

    DEFAULT_CSS = """
    PokedexPane { height: 1fr; }
    PokedexPane #pokedex-search { dock: top; }
    PokedexPane #pokedex-list { width: 28; }
    PokedexPane #pokedex-detail { padding: 0 1; }
    """

    def __init__(self, ctx: object | None = None) -> None:
        super().__init__()
        self._ctx = ctx
        self._ids: list[int] = []

    def compose(self) -> ComposeResult:
        yield Input(placeholder="search: name · #id · type:fire", id="pokedex-search")
        with Horizontal():
            yield ListView(id="pokedex-list")
            with VerticalScroll(id="pokedex-detail-scroll"):
                yield Static(id="pokedex-detail")

    def on_mount(self) -> None:
        self.apply_query("")

    def apply_query(self, query: str) -> int:
        """Rebuild the species list for ``query``; return the match count."""
        self._ids = M.search(query)
        listv = self.query_one("#pokedex-list", ListView)
        listv.clear()
        for sid in self._ids:
            listv.append(ListItem(Label(f"#{sid:03d} {M.species_name(sid)}")))
        if self._ids:
            listv.index = 0
            self.show_species(self._ids[0])
        else:
            self.query_one("#pokedex-detail", Static).update("[dim]No matches.[/dim]")
        return len(self._ids)

    def show_species(self, species_id: int) -> None:
        detail = M.assemble_detail(species_id)
        self.query_one("#pokedex-detail", Static).update(M.format_detail(detail))

    def on_input_changed(self, event: Input.Changed) -> None:
        if event.input.id == "pokedex-search":
            self.apply_query(event.value)

    def on_list_view_highlighted(self, event: ListView.Highlighted) -> None:
        index = event.list_view.index
        if index is not None and 0 <= index < len(self._ids):
            self.show_species(self._ids[index])
