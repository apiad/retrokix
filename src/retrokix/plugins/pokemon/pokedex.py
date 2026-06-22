"""retrokix Pokédex plugin — a searchable, stat-browsing Pokédex tab.

Pure reference data: renders all 386 Emerald species with base stats, types,
abilities, type matchups, evolutions, and level-up movesets, with live search.
Reads only bundled data — no ROM, save, or network. The "caught/seen" overlay
(live ``dexCaught`` read) is a later slice; this plugin stays static.

Load it for an Emerald session::

    retrokix play emerald.gba --plugin retrokix.plugins.pokemon.pokedex
"""

from __future__ import annotations

import retrokix
from retrokix.tui.pokedex_widget import PokedexPane

p = retrokix.plugin()


@p.tab("Pokédex")
def pokedex_tab(ctx):
    return PokedexPane(ctx)
