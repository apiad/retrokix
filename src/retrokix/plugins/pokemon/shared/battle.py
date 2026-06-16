"""In-battle gBattleMons[] readers.

Reads the decoded BattlePokemon structs that the game maintains during
combat — these are fully decrypted by the game itself, no XOR/permutation
needed. Source: include/pokemon.h::BattlePokemon, src/battle_main.c:164.
"""
from __future__ import annotations

import struct

from retrokix.plugins.pokemon.shared.addresses import (
    BATTLE_MON_SIZE, BMON_OFF_HP, BMON_OFF_LEVEL, BMON_OFF_MAX_HP,
    BMON_OFF_MOVES, BMON_OFF_PP, BMON_OFF_SPECIES, BMON_OFF_TYPES,
    BMON_PLAYER_SLOT, GBATTLE_MONS_BASE, OPP_SINGLES_SLOT,
)
from retrokix.plugins.pokemon.shared.party import SPECIES_NAMES
from retrokix.plugins.pokemon.shared.scene import in_battle


def read_battle_mon(runtime, slot: int) -> dict | None:
    """Read gBattleMons[slot]. Returns None if sanity-filter fails."""
    base = GBATTLE_MONS_BASE + slot * BATTLE_MON_SIZE
    species = struct.unpack("<H", runtime.read_memory(base + BMON_OFF_SPECIES, 2))[0]
    if species == 0 or species > 412:
        return None
    level = runtime.read_memory(base + BMON_OFF_LEVEL, 1)[0]
    if level == 0 or level > 100:
        return None
    max_hp = struct.unpack("<H", runtime.read_memory(base + BMON_OFF_MAX_HP, 2))[0]
    if max_hp == 0 or max_hp > 999:
        return None
    hp = struct.unpack("<H", runtime.read_memory(base + BMON_OFF_HP, 2))[0]
    if hp > max_hp:
        return None
    type1 = runtime.read_memory(base + BMON_OFF_TYPES, 1)[0]
    type2 = runtime.read_memory(base + BMON_OFF_TYPES + 1, 1)[0]
    move_ids = struct.unpack("<HHHH", runtime.read_memory(base + BMON_OFF_MOVES, 8))
    pp_values = list(runtime.read_memory(base + BMON_OFF_PP, 4))
    return {
        "species": species,
        "species_name": SPECIES_NAMES.get(species, f"#{species}"),
        "level": level,
        "hp": hp,
        "max_hp": max_hp,
        "types": [type1, type2],
        "move_ids": list(move_ids),
        "pp": pp_values,
    }


def read_battle_opponent(runtime) -> dict | None:
    """Read gBattleMons[1] (singles opponent). Returns None if not in battle."""
    if not in_battle(runtime):
        return None
    base = GBATTLE_MONS_BASE + OPP_SINGLES_SLOT * BATTLE_MON_SIZE
    species = struct.unpack("<H", runtime.read_memory(base + BMON_OFF_SPECIES, 2))[0]
    if species == 0 or species > 412:
        return None
    level = runtime.read_memory(base + BMON_OFF_LEVEL, 1)[0]
    if level == 0 or level > 100:
        return None
    max_hp = struct.unpack("<H", runtime.read_memory(base + BMON_OFF_MAX_HP, 2))[0]
    if max_hp == 0 or max_hp > 999:
        return None
    hp = struct.unpack("<H", runtime.read_memory(base + BMON_OFF_HP, 2))[0]
    if hp > max_hp:
        return None
    return {
        "species": species,
        "species_name": SPECIES_NAMES.get(species, f"#{species}"),
        "level": level,
        "hp": hp,
        "max_hp": max_hp,
        "auto": True,
    }


def battle_state_dict(runtime) -> dict:
    """Combined snapshot for an agent: active + opponent + ranked moves."""
    from retrokix.plugins.pokemon.shared.data import load_moves, load_types
    from retrokix.plugins.pokemon.shared.formulas import type_effectiveness
    if not in_battle(runtime):
        return {"in_battle": False}
    active = read_battle_mon(runtime, BMON_PLAYER_SLOT)
    opp = read_battle_mon(runtime, OPP_SINGLES_SLOT)
    if not active or not opp:
        return {"in_battle": True, "active": active, "opponent": opp,
                "warning": "could not read both battlers cleanly"}
    types_lookup = load_types()
    moves_table = load_moves()

    def _enrich_mon(m):
        return {**m, "type_names": [types_lookup.get(str(t), f"#{t}") for t in m["types"]]}

    active_enriched = _enrich_mon(active)
    opp_enriched = _enrich_mon(opp)

    ranked = []
    for slot_idx, mid in enumerate(active["move_ids"]):
        if mid == 0:
            continue
        rec = moves_table.get(str(mid)) or {}
        type_name = rec.get("type", "NORMAL")
        type_id = _type_id_for_name(type_name)
        power = rec.get("power", 0)
        mul = type_effectiveness(type_id, opp["types"]) if type_id is not None else 1.0
        ranked.append({
            "menu_slot": slot_idx, "move_id": mid,
            "name": rec.get("name", f"#{mid}"),
            "type": type_name, "power": power,
            "accuracy": rec.get("accuracy", 100),
            "pp": active["pp"][slot_idx],
            "effective_mul": mul,
            "score": (power or 0) * mul,
        })
    ranked.sort(key=lambda r: r["score"], reverse=True)
    best = ranked[0] if ranked and ranked[0]["score"] > 0 else None
    return {
        "in_battle": True,
        "active": active_enriched,
        "opponent": opp_enriched,
        "ranked_moves": ranked,
        "best_move": best,
    }


def _type_id_for_name(name: str) -> int | None:
    from retrokix.plugins.pokemon.shared.data import load_types
    for tid, disp in load_types().items():
        if disp.upper() == name.upper():
            return int(tid)
    return None
