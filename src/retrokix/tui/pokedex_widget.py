"""PokedexPane — the Textual widget for the Pokédex tab.

Thin presentation over ``pokedex_model`` (pure, tested) for the static data,
plus a live seen/caught overlay read from the running Emerald save via
``shared.pokedex.read_dex`` when a runtime is available. Species are shown in
national-dex order; rows are marked ``✓`` caught / ``·`` seen.
"""
from __future__ import annotations

from textual.app import ComposeResult
from textual.containers import Horizontal, VerticalScroll
from textual.widgets import Input, Label, ListItem, ListView, Static

from retrokix.plugins.pokemon.shared import pokedex as _dexmod
from retrokix.plugins.pokemon.shared import pokedex_model as M


class PokedexPane(Static):
    """Two-pane master/detail Pokédex browser with a live caught/seen overlay."""

    DEFAULT_CSS = """
    PokedexPane { height: 1fr; }
    PokedexPane #pokedex-status { dock: top; color: $accent; }
    PokedexPane #pokedex-search { dock: top; }
    PokedexPane #pokedex-list { width: 30; }
    PokedexPane #pokedex-detail { padding: 0 1; }
    """

    def __init__(self, ctx: object | None = None) -> None:
        super().__init__()
        self._ctx = ctx
        self._ids: list[int] = []
        self._query = ""
        self._dex: dict[str, set[int]] | None = None

    def compose(self) -> ComposeResult:
        yield Static(id="pokedex-status")
        yield Input(placeholder="search: name · #natdex · type:fire", id="pokedex-search")
        with Horizontal():
            yield ListView(id="pokedex-list")
            with VerticalScroll(id="pokedex-detail-scroll"):
                yield Static(id="pokedex-detail")

    def on_mount(self) -> None:
        self._load_dex()
        self.apply_query("")
        self.set_interval(3.0, self._poll_dex)

    # ---- live dex overlay ----

    def _load_dex(self) -> None:
        runtime = getattr(self._ctx, "runtime", None)
        self._dex = _dexmod.read_dex(runtime) if runtime is not None else None
        self._refresh_status()

    def _poll_dex(self) -> None:
        before = self._dex
        self._load_dex()
        if self._dex != before:
            self.apply_query(self._query, keep_highlight=True)

    def _refresh_status(self) -> None:
        if self._dex is not None:
            caught, seen, total = _dexmod.counts(self._dex)
            text = f"Caught [b]{caught}[/b]/{total}    Seen {seen}"
        else:
            text = ""
        try:
            self.query_one("#pokedex-status", Static).update(text)
        except Exception:
            pass  # not mounted yet

    def _marker(self, species_id: int) -> str:
        if self._dex is None:
            return " "
        nat = M.national_of(species_id)
        if nat in self._dex["caught"]:
            return "✓"
        if nat in self._dex["seen"]:
            return "·"
        return " "

    # ---- list / detail ----

    def apply_query(self, query: str, keep_highlight: bool = False) -> int:
        """Rebuild the species list for ``query``; return the match count."""
        self._query = query
        prev: int | None = None
        if keep_highlight and self._ids:
            cur = self.query_one("#pokedex-list", ListView).index
            if cur is not None and 0 <= cur < len(self._ids):
                prev = self._ids[cur]
        self._ids = M.search(query)
        listv = self.query_one("#pokedex-list", ListView)
        listv.clear()
        for sid in self._ids:
            nat = M.national_of(sid)
            listv.append(ListItem(Label(f"{self._marker(sid)} #{nat:03d} {M.species_name(sid)}")))
        if self._ids:
            idx = self._ids.index(prev) if prev in self._ids else 0
            listv.index = idx
            self.show_species(self._ids[idx])
        else:
            self.query_one("#pokedex-detail", Static).update("[dim]No matches.[/dim]")
        return len(self._ids)

    def show_species(self, species_id: int) -> None:
        detail = M.assemble_detail(species_id)
        text = M.format_detail(detail)
        if self._dex is not None and detail:
            nat = detail["national"]
            if nat in self._dex["caught"]:
                status = "[green]✓ Caught[/green]"
            elif nat in self._dex["seen"]:
                status = "[yellow]· Seen[/yellow]"
            else:
                status = "[dim]Not seen[/dim]"
            text = text.replace("\n", f"   {status}\n", 1)
        self.query_one("#pokedex-detail", Static).update(text)

    def on_input_changed(self, event: Input.Changed) -> None:
        if event.input.id == "pokedex-search":
            self.apply_query(event.value)

    def on_list_view_highlighted(self, event: ListView.Highlighted) -> None:
        index = event.list_view.index
        if index is not None and 0 <= index < len(self._ids):
            self.show_species(self._ids[index])
