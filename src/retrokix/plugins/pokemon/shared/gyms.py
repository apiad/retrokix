"""Hoenn gym progression + computed type-matchup planning.

The gym list grounds "which gym is next" by badge count; `gym_plan` uses the
real type engine (formulas) to compute which party members resist / are weak to
the gym's type and which attacking types beat it — so the LLM never has to
(mis)do type math.
"""
from __future__ import annotations

from retrokix.plugins.pokemon.shared import formulas as _F
from retrokix.plugins.pokemon.shared.data import load_types

# Hoenn gyms in order. `type_id` matches the type chart; ace_level is approximate
# (Emerald), used only as soft guidance.
GYMS = [
    {"leader": "Roxanne", "town": "Rustboro City", "type": "Rock", "type_id": 5, "ace_level": 15},
    {"leader": "Brawly", "town": "Dewford Town", "type": "Fighting", "type_id": 1, "ace_level": 19},
    {"leader": "Wattson", "town": "Mauville City", "type": "Electric", "type_id": 13, "ace_level": 24},
    {"leader": "Flannery", "town": "Lavaridge Town", "type": "Fire", "type_id": 10, "ace_level": 29},
    {"leader": "Norman", "town": "Petalburg City", "type": "Normal", "type_id": 0, "ace_level": 31},
    {"leader": "Winona", "town": "Fortree City", "type": "Flying", "type_id": 2, "ace_level": 33},
    {"leader": "Tate & Liza", "town": "Mossdeep City", "type": "Psychic", "type_id": 14, "ace_level": 42},
    {"leader": "Juan", "town": "Sootopolis City", "type": "Water", "type_id": 11, "ace_level": 46},
]


def next_gym(badge_count: int) -> dict | None:
    """The next unbeaten gym for this badge count, or None (Elite Four next)."""
    return GYMS[badge_count] if 0 <= badge_count < len(GYMS) else None


def _type_name(type_id: int) -> str:
    return load_types().get(str(type_id), f"#{type_id}")


def gym_plan(gym_type_id: int, party: list[dict]) -> dict:
    """Compute, from the real type chart, how the party fares vs a gym type.

    ``party`` items need a ``species`` (internal id) and ``name``. Returns
    resist / weak / neutral party-name lists (defensive vs the gym's STAB type)
    and ``se_types`` — attacking type names that are super-effective against it.
    """
    resist, weak, neutral = [], [], []
    for mon in party:
        sp = mon.get("species")
        if not sp:
            continue
        types = _F.species_types(int(sp))
        if not types:
            continue
        eff = _F.type_effectiveness(gym_type_id, types)
        label = f"{mon['name']} (×{eff:g})"
        if eff < 1:
            resist.append(label)
        elif eff > 1:
            weak.append(label)
        else:
            neutral.append(mon["name"])

    se_types = [
        _type_name(tid)
        for tid in range(0, 18)
        if _F.type_effectiveness(tid, [gym_type_id]) > 1
    ]
    return {"resist": resist, "weak": weak, "neutral": neutral, "se_types": se_types}
