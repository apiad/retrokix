"""Pokémon Emerald party slot decoding.

Reads gPlayerParty[] from EWRAM, decrypts the 48-byte substructure block
via personality ^ otId XOR + 24-permutation, and exposes structured per-slot
records. Pure-function — no rendering, no buttons.

Source: pokeemerald include/pokemon.h (struct Pokemon, BoxPokemon, the four
PokemonSubstruct types) + src/pokemon.c (CalculateMonStats, status flags).
"""
from __future__ import annotations

import json
import struct
from importlib.resources import files

from gbax.plugins.pokemon.shared.addresses import (
    OFF_CURRENT_HP, OFF_ENC_BLOCK, OFF_LEVEL, OFF_MAX_HP, OFF_OTID,
    OFF_PERSONALITY, OFF_STATUS, OFF_STAT_ATK, OFF_STAT_DEF, OFF_STAT_SPA,
    OFF_STAT_SPD, OFF_STAT_SPE, PARTY_BASE, SLOT_COUNT, SLOT_SIZE,
    SUBSTRUCT_ORDERS,
)


def _load_json_table(name: str) -> dict[int, object]:
    try:
        raw = files("gbax.data").joinpath(name).read_text()
        return {int(k): v for k, v in json.loads(raw).items()}
    except Exception:
        return {}


SPECIES_NAMES = _load_json_table("emerald_species.json")
GROWTH_RATES = _load_json_table("emerald_growth_rates.json")

GROWTH_MEDIUM_FAST = 0
GROWTH_ERRATIC = 1
GROWTH_FLUCTUATING = 2
GROWTH_MEDIUM_SLOW = 3
GROWTH_FAST = 4
GROWTH_SLOW = 5


def exp_at_level(growth: int, n: int) -> int:
    """Cumulative experience required to reach level n. Mirrors pokeemerald
    src/data/pokemon/experience_tables.h macros. n in [0, 100]."""
    if n <= 0:
        return 0
    if n == 1:
        return 1
    if growth == GROWTH_MEDIUM_FAST:
        return n ** 3
    if growth == GROWTH_FAST:
        return (4 * n ** 3) // 5
    if growth == GROWTH_SLOW:
        return (5 * n ** 3) // 4
    if growth == GROWTH_MEDIUM_SLOW:
        return (6 * n ** 3) // 5 - 15 * n ** 2 + 100 * n - 140
    if growth == GROWTH_ERRATIC:
        if n <= 50:
            return (100 - n) * n ** 3 // 50
        if n <= 68:
            return (150 - n) * n ** 3 // 100
        if n <= 98:
            return ((1911 - 10 * n) // 3) * n ** 3 // 500
        return (160 - n) * n ** 3 // 100
    if growth == GROWTH_FLUCTUATING:
        if n <= 15:
            return ((n + 1) // 3 + 24) * n ** 3 // 50
        if n <= 36:
            return (n + 14) * n ** 3 // 50
        return ((n // 2) + 32) * n ** 3 // 50
    return n ** 3


def _u8(runtime, addr):
    return runtime.read_memory(addr, 1)[0]


def _u16(runtime, addr):
    return struct.unpack("<H", runtime.read_memory(addr, 2))[0]


def _u32(runtime, addr):
    return struct.unpack("<I", runtime.read_memory(addr, 4))[0]


def _decrypt_block(enc_block: bytes, key: int) -> bytes:
    dec = bytearray()
    for i in range(0, 48, 4):
        w = struct.unpack("<I", enc_block[i:i + 4])[0] ^ key
        dec.extend(struct.pack("<I", w))
    return bytes(dec)


def _split_substructures(plain: bytes, personality: int) -> dict:
    order = SUBSTRUCT_ORDERS[personality % 24]
    return {letter: plain[i * 12:(i + 1) * 12] for i, letter in enumerate(order)}


def _parse_growth(sub: bytes) -> dict:
    species, held, exp = struct.unpack("<HHI", sub[:8])
    return {
        "species": species, "held_item": held, "experience": exp,
        "pp_bonuses": sub[8], "friendship": sub[9],
    }


def _parse_attacks(sub: bytes) -> dict:
    moves = list(struct.unpack("<HHHH", sub[:8]))
    pp = list(sub[8:12])
    return {"moves": moves, "pp": pp}


def _parse_evs(sub: bytes) -> dict:
    hp_ev, atk_ev, def_ev, spe_ev, spa_ev, spd_ev = sub[:6]
    return {
        "hp": hp_ev, "atk": atk_ev, "def": def_ev,
        "spe": spe_ev, "spa": spa_ev, "spd": spd_ev,
        "contest": list(sub[6:12]),
    }


def _parse_misc(sub: bytes) -> dict:
    pokerus = sub[0]
    met_location = sub[1]
    origin_info = struct.unpack("<H", sub[2:4])[0]
    iv_word = struct.unpack("<I", sub[4:8])[0]
    ribbons = struct.unpack("<I", sub[8:12])[0]
    return {
        "pokerus": pokerus,
        "met_location": met_location,
        "met_level": origin_info & 0x7F,
        "origin_game": (origin_info >> 7) & 0x0F,
        "poke_ball": (origin_info >> 11) & 0x0F,
        "ot_gender": (origin_info >> 15) & 0x01,
        "ivs": {
            "hp": iv_word & 0x1F,
            "atk": (iv_word >> 5) & 0x1F,
            "def": (iv_word >> 10) & 0x1F,
            "spe": (iv_word >> 15) & 0x1F,
            "spa": (iv_word >> 20) & 0x1F,
            "spd": (iv_word >> 25) & 0x1F,
        },
        "is_egg": (iv_word >> 30) & 1,
        "ability_num": (iv_word >> 31) & 1,
        "ribbons": ribbons,
    }


def _decode_status(status_word: int) -> str | None:
    sleep_turns = status_word & 0x07
    if sleep_turns:
        return f"sleep ({sleep_turns}T)"
    if status_word & 0x08:
        return "poison"
    if status_word & 0x10:
        return "burn"
    if status_word & 0x20:
        return "freeze"
    if status_word & 0x40:
        return "paralysis"
    if status_word & 0x80:
        return "toxic"
    return None


NATURE_NAMES_LOCAL = [
    "Hardy", "Lonely", "Brave", "Adamant", "Naughty",
    "Bold", "Docile", "Relaxed", "Impish", "Lax",
    "Timid", "Hasty", "Serious", "Jolly", "Naive",
    "Modest", "Mild", "Quiet", "Bashful", "Rash",
    "Calm", "Gentle", "Sassy", "Careful", "Quirky",
]


def next_move_for(species: int, level: int) -> dict | None:
    from gbax.plugins.pokemon.shared.data import load_levelup
    learnset = load_levelup().get(str(species), [])
    for entry in learnset:
        if entry["level"] > level:
            return {
                "level": entry["level"],
                "move_name": entry["move_name"],
                "move_id": entry["move_id"],
                "in": entry["level"] - level,
            }
    return None


def next_evolution_for(species: int, level: int) -> dict | None:
    from gbax.plugins.pokemon.shared.data import load_evolutions
    evos = load_evolutions().get(str(species), [])
    if not evos:
        return None
    for evo in evos:
        if evo["trigger"] == "LEVEL":
            return {
                "target_name": evo["target_name"],
                "trigger": "LEVEL",
                "at_level": evo["param"],
                "in": max(0, evo["param"] - level),
            }
    evo = evos[0]
    return {"target_name": evo["target_name"], "trigger": evo["trigger"], "param": evo["param"]}


def read_slot(runtime, slot_idx: int):
    """Return a dict for the slot, or None if the slot is empty. Decodes
    all 4 substructures + the Pokémon trailer (status + computed stats)."""
    base = PARTY_BASE + slot_idx * SLOT_SIZE
    personality = _u32(runtime, base + OFF_PERSONALITY)
    if personality == 0:
        return None
    otid = _u32(runtime, base + OFF_OTID)
    key = personality ^ otid

    level = _u8(runtime, base + OFF_LEVEL)
    hp = _u16(runtime, base + OFF_CURRENT_HP)
    max_hp = _u16(runtime, base + OFF_MAX_HP)
    status_word = _u32(runtime, base + OFF_STATUS)
    stats = {
        "atk": _u16(runtime, base + OFF_STAT_ATK),
        "def": _u16(runtime, base + OFF_STAT_DEF),
        "spe": _u16(runtime, base + OFF_STAT_SPE),
        "spa": _u16(runtime, base + OFF_STAT_SPA),
        "spd": _u16(runtime, base + OFF_STAT_SPD),
    }

    enc = runtime.read_memory(base + OFF_ENC_BLOCK, 48)
    plain = _decrypt_block(enc, key)
    subs = _split_substructures(plain, personality)
    growth_info = _parse_growth(subs["G"])
    attacks_info = _parse_attacks(subs["A"])
    evs_info = _parse_evs(subs["E"])
    misc_info = _parse_misc(subs["M"])

    species = growth_info["species"]
    exp = growth_info["experience"]
    growth_rate = GROWTH_RATES.get(species, GROWTH_MEDIUM_FAST)
    exp_cur_lv = exp_at_level(growth_rate, level)
    exp_next_lv = exp_at_level(growth_rate, level + 1) if level < 100 else exp_cur_lv
    span = max(1, exp_next_lv - exp_cur_lv)
    into = max(0, exp - exp_cur_lv)
    to_next = max(0, exp_next_lv - exp)

    nature_id = personality % 25
    nature_name = NATURE_NAMES_LOCAL[nature_id]

    from gbax.plugins.pokemon.shared.data import load_moves
    moves_table = load_moves()
    move_records = []
    for i, mid in enumerate(attacks_info["moves"]):
        if mid == 0:
            continue
        info = moves_table.get(str(mid)) or {}
        move_records.append({
            "id": mid,
            "name": info.get("name", f"#{mid}"),
            "type": info.get("type"),
            "power": info.get("power"),
            "accuracy": info.get("accuracy"),
            "pp_current": attacks_info["pp"][i],
        })

    return {
        "slot": slot_idx,
        "species": species,
        "species_name": SPECIES_NAMES.get(species, f"#{species}"),
        "level": level,
        "hp": hp,
        "max_hp": max_hp,
        "exp": exp,
        "exp_into_level": into,
        "exp_to_next_level": to_next,
        "exp_level_span": span,
        "held": growth_info["held_item"],
        "friendship": growth_info["friendship"],
        "pp_bonus": growth_info["pp_bonuses"],
        "next_move": next_move_for(species, level),
        "next_evolution": next_evolution_for(species, level),
        "nature": nature_name,
        "nature_id": nature_id,
        "ability_num": misc_info["ability_num"],
        "ivs": misc_info["ivs"],
        "evs": {k: v for k, v in evs_info.items() if k != "contest"},
        "stats": stats,
        "status": _decode_status(status_word),
        "moves": move_records,
        "met_level": misc_info["met_level"],
        "poke_ball": misc_info["poke_ball"],
        "personality": personality,
    }


def party_slots_full(runtime) -> list[dict | None]:
    """Return all 6 party slot dicts (or None for empty slots)."""
    return [read_slot(runtime, i) for i in range(SLOT_COUNT)]
