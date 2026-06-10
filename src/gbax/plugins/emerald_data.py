"""Lazy loaders for the bundled emerald_*.json data tables.

Data derived from pokeemerald (https://github.com/pret/pokeemerald), the
community decompilation of Pokémon Emerald. Pokémon names and game data ©
Nintendo / Game Freak / Creatures. This module reads only from the bundled
package data; no network, no save, no ROM access.
"""
from __future__ import annotations

import json
from functools import cache
from importlib.resources import files


def _load(name: str) -> dict:
    try:
        raw = files("gbax.data").joinpath(name).read_text()
        payload = json.loads(raw)
        return payload.get("data", payload)
    except Exception:
        return {}


@cache
def load_species_info() -> dict:
    """Per-species base stats record. Keys are species-id strings."""
    return _load("emerald_species_info.json")


@cache
def load_evolutions() -> dict:
    return _load("emerald_evolutions.json")


@cache
def load_levelup() -> dict:
    """species_id_string → [{level, move_id, move_name}, ...] sorted by level."""
    return _load("emerald_levelup.json")


@cache
def load_moves() -> dict:
    """Per-move record: name, type, power, accuracy, pp, priority, effect, flags."""
    return _load("emerald_moves.json")


@cache
def load_type_chart() -> list[list[int]]:
    """List of [attack_type, defender_type, multiplier×10] triples (gen-3 ints)."""
    return _load("emerald_type_chart.json")


@cache
def load_types() -> dict[str, str]:
    """Type-ID-string → display name. Includes '???' (TYPE_MYSTERY=9)."""
    return _load("emerald_types.json")


@cache
def load_items() -> dict:
    return _load("emerald_items.json")


@cache
def load_abilities() -> dict:
    return _load("emerald_abilities.json")


@cache
def load_natures() -> dict:
    """Per-nature record: {name, mods: [atk_mod, def_mod, spe_mod, spa_mod, spd_mod]}."""
    return _load("emerald_natures.json")


@cache
def load_mapsec() -> dict:
    return _load("emerald_mapsec.json")
