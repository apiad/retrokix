"""gbax plugin — live Pokémon Emerald party panel.

Reads all 6 party slots, decrypts the substructure block via personality +
OT_id XOR, and renders a Rich table with Lv / HP / Exp / species per slot.
Updates ~3 Hz to keep the SDL main thread responsive.
"""
from __future__ import annotations

import json
import struct
from importlib.resources import files

import gbax

p = gbax.plugin()


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


# --- canonical Emerald layout ---

PARTY_BASE = 0x020244EC     # slot 0 start
SLOT_SIZE = 100             # bytes per party slot
SLOT_COUNT = 6

# Offsets WITHIN a 100-byte party slot. Source: include/pokemon.h (struct
# BoxPokemon + Pokemon trailer). The first 32 bytes are clear-text BoxPokemon
# header; offsets 0x20..0x4F are the encrypted 48-byte substructure block;
# offsets 0x50..0x63 are the unencrypted Pokemon trailer with status + stats.
OFF_PERSONALITY = 0x00      # u32
OFF_OTID = 0x04             # u32
OFF_NICKNAME = 0x08         # 10 bytes
OFF_LANGUAGE = 0x12         # u8
OFF_CHECKSUM = 0x1C         # u16
OFF_ENC_BLOCK = 0x20        # 48 encrypted bytes (4 × 12-byte substructures)
OFF_STATUS = 0x50           # u32 — sleep counter / poison / burn / freeze / para
OFF_LEVEL = 0x54            # u8
OFF_CURRENT_HP = 0x56       # u16_le
OFF_MAX_HP = 0x58           # u16_le
OFF_STAT_ATK = 0x5A         # u16_le
OFF_STAT_DEF = 0x5C
OFF_STAT_SPE = 0x5E
OFF_STAT_SPA = 0x60
OFF_STAT_SPD = 0x62

# 24 permutations of (Growth, Attacks, EVs, Misc) within the encrypted block,
# indexed by personality % 24.
SUBSTRUCT_ORDERS = [
    "GAEM", "GAME", "GEAM", "GEMA", "GMAE", "GMEA",
    "AGEM", "AGME", "AEGM", "AEMG", "AMGE", "AMEG",
    "EGAM", "EGMA", "EAGM", "EAMG", "EMGA", "EMAG",
    "MGAE", "MGEA", "MAGE", "MAEG", "MEGA", "MEAG",
]


def _u8(runtime, addr):
    return runtime.read_memory(addr, 1)[0]


def _u16(runtime, addr):
    return struct.unpack("<H", runtime.read_memory(addr, 2))[0]


def _u32(runtime, addr):
    return struct.unpack("<I", runtime.read_memory(addr, 4))[0]


def _decrypt_block(enc_block: bytes, key: int) -> bytes:
    """XOR every u32 word in the 48-byte block with the (personality ^ otId)
    key. Returns plaintext bytes in the same permuted order as the cipher."""
    dec = bytearray()
    for i in range(0, 48, 4):
        w = struct.unpack("<I", enc_block[i:i + 4])[0] ^ key
        dec.extend(struct.pack("<I", w))
    return bytes(dec)


def _split_substructures(plain: bytes, personality: int) -> dict:
    """Return dict with keys 'G', 'A', 'E', 'M' → 12-byte substructure each,
    using the personality%24 permutation. Source: include/pokemon.h struct
    BoxPokemon (the 24 substruct orders are documented in pokeemerald)."""
    order = SUBSTRUCT_ORDERS[personality % 24]
    return {letter: plain[i * 12:(i + 1) * 12] for i, letter in enumerate(order)}


def _parse_growth(sub: bytes) -> dict:
    """Source: src/pokemon.c::struct PokemonSubstruct0."""
    species, held, exp = struct.unpack("<HHI", sub[:8])
    pp_bonuses = sub[8]
    friendship = sub[9]
    return {
        "species": species,
        "held_item": held,
        "experience": exp,
        "pp_bonuses": pp_bonuses,
        "friendship": friendship,
    }


def _parse_attacks(sub: bytes) -> dict:
    """Source: src/pokemon.c::struct PokemonSubstruct1. 4 moves + 4 PPs."""
    moves = list(struct.unpack("<HHHH", sub[:8]))
    pp = list(sub[8:12])
    return {"moves": moves, "pp": pp}


def _parse_evs(sub: bytes) -> dict:
    """Source: src/pokemon.c::struct PokemonSubstruct2. 6 EVs + 6 contest stats."""
    hp_ev, atk_ev, def_ev, spe_ev, spa_ev, spd_ev = sub[:6]
    return {
        "hp": hp_ev, "atk": atk_ev, "def": def_ev,
        "spe": spe_ev, "spa": spa_ev, "spd": spd_ev,
        "contest": list(sub[6:12]),  # cool/beauty/cute/smart/tough/sheen
    }


def _parse_misc(sub: bytes) -> dict:
    """Source: src/pokemon.c::struct PokemonSubstruct3.
    Layout: pokerus(u8), metLocation(u8), originInfo(u16),
            IVs+egg+abilityNum(u32), ribbons(u32)."""
    pokerus = sub[0]
    met_location = sub[1]
    origin_info = struct.unpack("<H", sub[2:4])[0]
    iv_word = struct.unpack("<I", sub[4:8])[0]
    ribbons = struct.unpack("<I", sub[8:12])[0]
    # originInfo: metLevel:7, originGame:4, pokeBall:4, otGender:1
    met_level = origin_info & 0x7F
    origin_game = (origin_info >> 7) & 0x0F
    poke_ball = (origin_info >> 11) & 0x0F
    ot_gender = (origin_info >> 15) & 0x01
    # IVs: hp:5, atk:5, def:5, spe:5, spa:5, spd:5, isEgg:1, abilityNum:1
    ivs = {
        "hp": iv_word & 0x1F,
        "atk": (iv_word >> 5) & 0x1F,
        "def": (iv_word >> 10) & 0x1F,
        "spe": (iv_word >> 15) & 0x1F,
        "spa": (iv_word >> 20) & 0x1F,
        "spd": (iv_word >> 25) & 0x1F,
    }
    is_egg = (iv_word >> 30) & 1
    ability_num = (iv_word >> 31) & 1
    return {
        "pokerus": pokerus,
        "met_location": met_location,
        "met_level": met_level,
        "origin_game": origin_game,
        "poke_ball": poke_ball,
        "ot_gender": ot_gender,
        "ivs": ivs,
        "is_egg": is_egg,
        "ability_num": ability_num,
        "ribbons": ribbons,
    }


# Status u32 layout (0x50): sleep counter in low 3 bits; poison, burn, freeze,
# paralysis, toxic each as a flag. Source: include/pokemon.h STATUS1_* defines.
STATUS_LABELS = [
    (0x07, "sleep", lambda v: f"sleep ({v} turns)"),
    (0x08, "poison", lambda v: "poison"),
    (0x10, "burn", lambda v: "burn"),
    (0x20, "freeze", lambda v: "freeze"),
    (0x40, "paralysis", lambda v: "paralysis"),
    (0x80, "toxic", lambda v: "toxic"),
]


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


def read_slot(runtime, slot_idx: int):
    """Return a dict for the slot, or None if the slot is empty. Decodes
    all 4 substructures (Growth, Attacks, EVs, Misc) and surfaces the
    Pokémon trailer (status + computed stats)."""
    base = PARTY_BASE + slot_idx * SLOT_SIZE
    personality = _u32(runtime, base + OFF_PERSONALITY)
    if personality == 0:
        return None
    otid = _u32(runtime, base + OFF_OTID)
    key = personality ^ otid

    # Unencrypted trailer
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

    # Encrypted block (48 bytes), decrypt and split.
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

    # Move names from the bundled moves table
    from gbax.plugins.emerald_data import load_moves
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
        # Slice 3 additions:
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


# --- Goal lookups (next move + next evolution per slot) ---

def next_move_for(species: int, level: int) -> dict | None:
    """Next level-up move this species learns after current level."""
    from gbax.plugins.emerald_data import load_levelup
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
    """Next evolution and when it'll trigger. Levels only for v0.12 —
    Item/Friendship/etc. triggers report the trigger but no time-to-fire."""
    from gbax.plugins.emerald_data import load_evolutions
    evos = load_evolutions().get(str(species), [])
    if not evos:
        return None
    # Pick the first reachable: prefer LEVEL trigger over branch ones for clarity
    for evo in evos:
        if evo["trigger"] == "LEVEL":
            return {
                "target_name": evo["target_name"],
                "trigger": "LEVEL",
                "at_level": evo["param"],
                "in": max(0, evo["param"] - level),
            }
    # Fall back: any other trigger (FRIENDSHIP, ITEM, TRADE…)
    evo = evos[0]
    return {
        "target_name": evo["target_name"],
        "trigger": evo["trigger"],
        "param": evo["param"],
    }


# --- Rich Live panel ---

_live = None
_render_fn = None


def _likely_moves(species: int, level: int):
    """Heuristic: the last 4 distinct damaging moves a species has learned via
    level-up at-or-below the current level. Pokémon let you keep at most 4 at
    a time; new ones displace old ones in learn order. Status moves (power=0)
    are still returned so the panel can flag 'no damaging answer'."""
    from gbax.plugins.emerald_data import load_levelup
    learnset = load_levelup().get(str(species), [])
    eligible = [m for m in learnset if m["level"] <= level]
    # Walk newest → oldest, dedupe by move_id, take 4
    seen = set()
    keep = []
    for m in reversed(eligible):
        if m["move_id"] in seen:
            continue
        seen.add(m["move_id"])
        keep.append(m)
        if len(keep) >= 4:
            break
    return keep


def _type_id_for_name(name: str) -> int | None:
    from gbax.plugins.emerald_data import load_types
    for tid, disp in load_types().items():
        if disp.upper() == name.upper():
            return int(tid)
    return None


def _best_move_against(slot_data: dict, defender_types: list[int]):
    """Return (move_name, mul, power) for this slot's best move vs the
    defender, or None if no damaging move. Uses the slot's REAL moves
    when available (post-Slice-3); falls back to the level-up heuristic
    when no moves are surfaced."""
    from gbax.plugins.emerald_formulas import type_effectiveness
    # Real moveset from substructure decode
    real_moves = slot_data.get("moves") or []
    if real_moves:
        candidates = [(m["name"], m.get("type") or "NORMAL", m.get("power") or 0)
                      for m in real_moves]
    else:
        from gbax.plugins.emerald_data import load_moves
        moves_table = load_moves()
        candidates = []
        for m in _likely_moves(slot_data["species"], slot_data["level"]):
            info = moves_table.get(str(m["move_id"])) or {}
            candidates.append((m["move_name"], info.get("type", "NORMAL"), info.get("power", 0)))
    best = None
    for name, type_name, power in candidates:
        if power == 0:
            continue
        type_id = _type_id_for_name(type_name)
        if type_id is None:
            continue
        mul = type_effectiveness(type_id, defender_types)
        score = power * mul
        if best is None or score > best["score"]:
            best = {
                "move_name": name,
                "type_name": type_name,
                "mul": mul,
                "power": power,
                "score": score,
            }
    return best


def _build_opponent_panel(runtime=None):
    """Rich Panel for the currently tagged opponent. None if no opponent set."""
    if _opponent is None:
        return None
    from rich.panel import Panel
    from rich.table import Table
    from gbax.plugins.emerald_formulas import species_types, weaknesses, resistances
    from gbax.plugins.emerald_data import load_types
    sp = _opponent["species"]
    lv = _opponent["level"]
    types = species_types(sp) or []
    type_names = load_types()
    name = SPECIES_NAMES.get(sp, f"#{sp}")
    types_str = " / ".join(type_names.get(str(t), f"#{t}") for t in types) or "?"

    # Top section: weakness/resistance bands
    bands = Table.grid(padding=(0, 2))
    bands.add_column(style="bold")
    bands.add_column()
    bands.add_row("[red]4×[/red]",
        ", ".join(type_names.get(str(t), f"#{t}") for t, m in weaknesses(types) if m == 4.0) or "—")
    bands.add_row("[yellow]2×[/yellow]",
        ", ".join(type_names.get(str(t), f"#{t}") for t, m in weaknesses(types) if m == 2.0) or "—")
    bands.add_row("[green]½×[/green]",
        ", ".join(type_names.get(str(t), f"#{t}") for t, m in resistances(types) if m == 0.5) or "—")
    bands.add_row("[green]¼×[/green]",
        ", ".join(type_names.get(str(t), f"#{t}") for t, m in resistances(types) if m == 0.25) or "—")
    bands.add_row("[blue]0×[/blue]",
        ", ".join(type_names.get(str(t), f"#{t}") for t, m in resistances(types) if m == 0.0) or "—")

    # Per-party recommendations (needs runtime to read party)
    recs = None
    if runtime is not None:
        recs = Table(show_header=True, header_style="bold cyan", expand=False)
        recs.add_column("slot")
        recs.add_column("best move")
        recs.add_column("type")
        recs.add_column("×", justify="right")
        rows = []
        for i in range(SLOT_COUNT):
            slot = read_slot(runtime, i)
            if slot is None:
                continue
            best = _best_move_against(slot, types)
            if best is None:
                rows.append((slot["species_name"], "(status only)", "—", 0))
                continue
            rows.append((slot["species_name"], best["move_name"], best["type_name"], best["mul"]))
        rows.sort(key=lambda r: r[3], reverse=True)
        for sp_name, mv_name, ty_name, mul in rows:
            mul_str = f"{mul:g}"
            mark = "✓" if mul >= 2.0 else (" " if mul == 1.0 else "✗")
            style = "bold green" if mul >= 2.0 else ("dim red" if mul < 1.0 else "white")
            recs.add_row(
                f"[{style}]{mark} {sp_name}[/{style}]",
                f"[{style}]{mv_name}[/{style}]",
                f"[{style}]{ty_name}[/{style}]",
                f"[{style}]{mul_str}×[/{style}]",
            )

    if recs is None:
        body = bands
    else:
        from rich.console import Group
        body = Group(bands, "", recs)

    return Panel(body,
                 title=f"[bold]opponent — {name} L{lv} ({types_str})[/bold]",
                 border_style="red")


def _build_table(runtime):
    from rich.table import Table
    t = Table(title="party (live)", show_header=True, header_style="bold cyan", expand=False)
    t.add_column("#", justify="right")
    t.add_column("species", justify="right")
    t.add_column("lv", justify="right")
    t.add_column("hp", justify="right")
    t.add_column("xp →", justify="right")
    t.add_column("next move", justify="left")
    t.add_column("next evo", justify="left")
    for i in range(SLOT_COUNT):
        slot = read_slot(runtime, i)
        if slot is None:
            continue
        hp_color = "green" if slot["hp"] >= slot["max_hp"] * 0.5 else "yellow" if slot["hp"] >= slot["max_hp"] * 0.25 else "red"
        span = slot["exp_level_span"]
        into = slot["exp_into_level"]
        pct = int(100 * into / span) if span else 0

        nm = slot.get("next_move")
        next_move_str = f"{nm['move_name']} @L{nm['level']} (+{nm['in']})" if nm else "—"

        ev = slot.get("next_evolution")
        if ev and ev.get("trigger") == "LEVEL":
            next_evo_str = f"{ev['target_name']} @L{ev['at_level']} (+{ev['in']})"
        elif ev:
            next_evo_str = f"{ev['target_name']} ({ev['trigger'].lower()})"
        else:
            next_evo_str = "—"

        t.add_row(
            str(slot["slot"]),
            slot["species_name"],
            str(slot["level"]),
            f"[{hp_color}]{slot['hp']}/{slot['max_hp']}[/{hp_color}]",
            f"{slot['exp_to_next_level']} ({pct}%)",
            next_move_str,
            next_evo_str,
        )
    return t


@p.route("/party")
def http_party(ctx):
    """Full party as structured JSON."""
    slots = []
    for i in range(SLOT_COUNT):
        s = read_slot(ctx.runtime, i)
        if s is not None:
            slots.append(s)
    return {"count": len(slots), "slots": slots}


@p.route("/slot/{idx}")
def http_slot(ctx, idx: int):
    """One slot by index (0-5). 404 if empty."""
    from fastapi import HTTPException
    if not 0 <= idx < SLOT_COUNT:
        raise HTTPException(status_code=400, detail=f"slot index {idx} out of range")
    s = read_slot(ctx.runtime, idx)
    if s is None:
        raise HTTPException(status_code=404, detail=f"slot {idx} is empty")
    return s


@p.route("/weaknesses/{species_id}")
def http_weaknesses(ctx, species_id: int):
    """Type weaknesses for a species — no party context needed.

    GET /plugins/emerald_party/weaknesses/74  → Geodude.
    """
    from gbax.plugins.emerald_formulas import species_types, weaknesses
    from gbax.plugins.emerald_data import load_species_info, load_types
    from fastapi import HTTPException
    info = load_species_info().get(str(species_id))
    if not info:
        raise HTTPException(status_code=404, detail=f"unknown species {species_id}")
    types = species_types(species_id)
    if not types:
        raise HTTPException(status_code=500, detail=f"no types for species {species_id}")
    type_names = load_types()
    weak = weaknesses(types)
    return {
        "species": species_id,
        "species_name": SPECIES_NAMES.get(species_id, f"#{species_id}"),
        "types": [type_names.get(str(t), f"#{t}") for t in types],
        "weaknesses": [
            {"type": type_names.get(str(t), f"#{t}"), "mul": m} for t, m in weak
        ],
    }


# --- Battle state reader (Pokémon Emerald US v1.0) ---
#
# gBattleMons[4] sits in EWRAM as a fully-decoded BattlePokemon array
# (88 bytes per battler). Singles: opponent is index 1.
# Source: include/pokemon.h struct BattlePokemon, src/battle_main.c:164.
#
# Address is the well-known Emerald US v1.0 (rev 0) offset.
# ROM SHA1 we expect: f3ae088181bf583e55daf962a92bb46f4f1d07b7

EMERALD_US_V10_SHA1 = "f3ae088181bf583e55daf962a92bb46f4f1d07b7"
GBATTLE_MONS_BASE = 0x02024084
GBATTLE_TYPE_FLAGS = 0x02022FEC   # zeroed when battle ends — gate for stale reads
BATTLE_MON_SIZE = 88
OPP_SINGLES_SLOT = 1

# Offsets within a BattlePokemon, source: include/pokemon.h
BMON_OFF_SPECIES = 0x00
BMON_OFF_MOVES = 0x0C    # u16 × 4
BMON_OFF_PP = 0x24       # u8 × 4
BMON_OFF_HP = 0x28
BMON_OFF_LEVEL = 0x2A
BMON_OFF_MAX_HP = 0x2C
BMON_OFF_TYPES = 0x21    # u8 × 2
BMON_PLAYER_SLOT = 0


def in_battle(runtime) -> bool:
    """gBattleTypeFlags non-zero ⇒ currently in a battle."""
    flags = struct.unpack("<I", runtime.read_memory(GBATTLE_TYPE_FLAGS, 4))[0]
    # In battle, only the low ~24 bits are populated. A wild value here
    # (e.g. > 0x00FFFFFF) signals our address is wrong on this build.
    return 0 < flags < 0x01000000


def _read_battle_mon(runtime, slot: int) -> dict | None:
    """Read gBattleMons[slot]. Returns None if validation fails."""
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


def read_battle_opponent(runtime):
    """Read gBattleMons[1]. Return a dict if a live opponent, else None."""
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


# --- Opponent tracking — auto-detected in battle, overridable via POST ---

_opponent: dict | None = None  # {"species": int, "level": int, "auto": bool?}
_autodetect_enabled = False  # set at on_setup once we verify the ROM


@p.route("/opponent", methods=["GET"])
def http_opponent_get(ctx):
    """Current 'opponent' tag — what the dashboard's matchup panel uses."""
    return _opponent or {}


@p.route("/opponent/{species_id}/{level}", methods=["POST"])
def http_opponent_set(ctx, species_id: int, level: int):
    """Tag what you're fighting. Live panel grows a matchup section."""
    global _opponent
    from gbax.plugins.emerald_data import load_species_info
    from fastapi import HTTPException
    if not load_species_info().get(str(species_id)):
        raise HTTPException(status_code=404, detail=f"unknown species {species_id}")
    _opponent = {"species": species_id, "level": level}
    return {"set": _opponent}


@p.route("/opponent/clear", methods=["POST"])
def http_opponent_clear(ctx):
    """Drop the opponent tag — panel returns to party-only view."""
    global _opponent
    _opponent = None
    return {"cleared": True}


# --- High-level battle driver ---
#
# Press sequences that hide menu navigation behind one POST per decision.
# Each command emits its full button choreography, waits a generous settle
# window for animations + HP updates, then returns /battle/state so the
# caller can chain decisions without polling.

SETTLE_FRAMES = 150        # frames to wait after final A in a sequence
NAV_GAP_FRAMES = 8         # frames between d-pad presses
PRESS_FRAMES = 3           # how long to hold each button
MENU_TRANSITION_FRAMES = 30  # action menu → move menu transition

# Button gbax button names (lowercase, GBA D-pad + A/B/Start/Select/L/R)


def _home_cursor_steps():
    """Press Up Up Left Left to drive any 2x2 menu cursor to slot 0 (top-left).
    Idempotent — extra presses do nothing if already at top-left."""
    return [
        {"hold": ["up"], "frames": PRESS_FRAMES}, {"release": True, "frames": NAV_GAP_FRAMES},
        {"hold": ["up"], "frames": PRESS_FRAMES}, {"release": True, "frames": NAV_GAP_FRAMES},
        {"hold": ["left"], "frames": PRESS_FRAMES}, {"release": True, "frames": NAV_GAP_FRAMES},
        {"hold": ["left"], "frames": PRESS_FRAMES}, {"release": True, "frames": NAV_GAP_FRAMES},
    ]


def _nav_to_2x2_slot_steps(slot: int):
    """From slot 0 (top-left), navigate to slot ∈ {0,1,2,3}."""
    out = []
    if slot in (1, 3):
        out += [{"hold": ["right"], "frames": PRESS_FRAMES},
                {"release": True, "frames": NAV_GAP_FRAMES}]
    if slot in (2, 3):
        out += [{"hold": ["down"], "frames": PRESS_FRAMES},
                {"release": True, "frames": NAV_GAP_FRAMES}]
    return out


def _press_a_steps(settle=SETTLE_FRAMES, screenshot=False):
    return [
        {"hold": ["a"], "frames": PRESS_FRAMES},
        {"release": True, "frames": settle, "screenshot": screenshot},
    ]


def _run_action(runtime, steps):
    """Execute an action sequence atomically against the runtime's lock and
    return any screenshots (raw RGB framebuffers)."""
    from gbax.input import button_from_str
    import base64
    from io import BytesIO
    from PIL import Image

    screenshots = []
    with runtime._lock:
        for step in steps:
            if step.get("release"):
                runtime.set_buttons(set())
            if step.get("hold") is not None:
                runtime.set_buttons({button_from_str(b) for b in step["hold"]})
            if step.get("frames", 0) > 0:
                runtime.step(step["frames"])
            if step.get("screenshot"):
                fb = runtime.framebuffer()
                buf = BytesIO()
                Image.fromarray(fb).save(buf, format="PNG")
                screenshots.append(base64.b64encode(buf.getvalue()).decode())
        runtime.set_buttons(set())
    return screenshots


def _battle_state_dict(runtime):
    """Re-compute /battle/state without re-routing through FastAPI."""
    from gbax.plugins.emerald_data import load_moves, load_types
    from gbax.plugins.emerald_formulas import type_effectiveness
    if not in_battle(runtime):
        return {"in_battle": False}
    active = _read_battle_mon(runtime, BMON_PLAYER_SLOT)
    opp = _read_battle_mon(runtime, OPP_SINGLES_SLOT)
    if not active or not opp:
        return {"in_battle": True, "active": active, "opponent": opp}
    types_lookup = load_types()
    moves_table = load_moves()
    for m in (active, opp):
        m["type_names"] = [types_lookup.get(str(t), f"#{t}") for t in m["types"]]
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
    return {
        "in_battle": True, "active": active, "opponent": opp,
        "ranked_moves": ranked,
        "best_move": ranked[0] if ranked and ranked[0]["score"] > 0 else None,
    }


@p.route("/battle/advance", methods=["POST"])
def http_battle_advance(ctx):
    """Press A once, settle, return state + screenshot. Use to dismiss text
    or accept Yes/No prompts (Yes is the default)."""
    shots = _run_action(ctx.runtime, _press_a_steps(screenshot=True))
    return {"state": _battle_state_dict(ctx.runtime), "screenshot_b64": shots[0] if shots else None}


@p.route("/battle/use_move/{slot}", methods=["POST"])
def http_battle_use_move(ctx, slot: int):
    """From the action menu, select FIGHT then move {slot} ∈ {0..3}.
    Returns state + post-resolution screenshot."""
    from fastapi import HTTPException
    if not 0 <= slot <= 3:
        raise HTTPException(400, detail=f"slot {slot} not in 0..3")
    steps = []
    # Home cursor on action menu → press A (FIGHT)
    steps += _home_cursor_steps()
    steps += [{"hold": ["a"], "frames": PRESS_FRAMES},
              {"release": True, "frames": MENU_TRANSITION_FRAMES}]
    # Now in move menu — home cursor, nav to slot, press A
    steps += _home_cursor_steps()
    steps += _nav_to_2x2_slot_steps(slot)
    steps += _press_a_steps(settle=SETTLE_FRAMES, screenshot=True)
    shots = _run_action(ctx.runtime, steps)
    return {"state": _battle_state_dict(ctx.runtime),
            "screenshot_b64": shots[-1] if shots else None}


@p.route("/battle/switch/{party_slot}", methods=["POST"])
def http_battle_switch(ctx, party_slot: int):
    """Switch to party slot {0..5}. Works from both the action menu (you
    initiated the switch) and the 'Choose a POKéMON' forced-switch screen.

    Party menu layout in Emerald: position 0 (active) is the left column;
    positions 1..5 are stacked top-to-bottom in the right column. Navigation
    from the active Pokémon is Right (→ position 1) then Down for each
    further position.
    """
    from fastapi import HTTPException
    if not 0 <= party_slot <= 5:
        raise HTTPException(400, detail=f"party_slot {party_slot} not in 0..5")
    if party_slot == 0:
        raise HTTPException(400, detail="can't switch to the active slot")
    steps = []
    # First try selecting POKEMON from the action menu (Down then A).
    # If we're already on the 'Choose a POKéMON' screen this just navigates
    # within the action menu position and the subsequent A is harmless —
    # safer pattern is to assume the action menu and let it be a no-op via
    # the "already on party screen" error tolerance. For robustness, just
    # press B first (to dismiss any open sub-menu), then send the canonical
    # POKEMON-selection sequence.
    # Action menu layout: FIGHT(0) BAG(1) POKEMON(2) RUN(3). Home + Down → POKEMON.
    steps += _home_cursor_steps()
    steps += [{"hold": ["down"], "frames": PRESS_FRAMES},
              {"release": True, "frames": NAV_GAP_FRAMES}]
    steps += [{"hold": ["a"], "frames": PRESS_FRAMES},
              {"release": True, "frames": MENU_TRANSITION_FRAMES}]
    # Now on party menu — cursor on active (left). Right to jump to position 1.
    steps += [{"hold": ["right"], "frames": PRESS_FRAMES},
              {"release": True, "frames": NAV_GAP_FRAMES}]
    # Down (party_slot - 1) times to reach target
    for _ in range(party_slot - 1):
        steps += [{"hold": ["down"], "frames": PRESS_FRAMES},
                  {"release": True, "frames": NAV_GAP_FRAMES}]
    # Press A → sub-menu (SHIFT / SUMMARY / CANCEL) — cursor on SHIFT
    steps += [{"hold": ["a"], "frames": PRESS_FRAMES},
              {"release": True, "frames": MENU_TRANSITION_FRAMES}]
    # Press A → confirm SHIFT
    steps += _press_a_steps(settle=SETTLE_FRAMES, screenshot=True)
    shots = _run_action(ctx.runtime, steps)
    return {"state": _battle_state_dict(ctx.runtime),
            "screenshot_b64": shots[-1] if shots else None}


@p.route("/battle/state")
def http_battle_state(ctx):
    """Combined snapshot for an agent driving a battle: active battler + opponent
    + per-move type-effectiveness ranking. All numbers come from gBattleMons[]
    so the move order matches what's on the screen."""
    from gbax.plugins.emerald_data import load_moves, load_types
    from gbax.plugins.emerald_formulas import type_effectiveness
    if not in_battle(ctx.runtime):
        return {"in_battle": False}
    active = _read_battle_mon(ctx.runtime, BMON_PLAYER_SLOT)
    opp = _read_battle_mon(ctx.runtime, OPP_SINGLES_SLOT)
    if not active or not opp:
        return {"in_battle": True, "active": active, "opponent": opp,
                "warning": "could not read both battlers cleanly"}
    types_lookup = load_types()
    moves_table = load_moves()

    def _enrich_mon(m):
        return {
            **m,
            "type_names": [types_lookup.get(str(t), f"#{t}") for t in m["types"]],
        }

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
        accuracy = rec.get("accuracy", 100)
        mul = type_effectiveness(type_id, opp["types"]) if type_id is not None else 1.0
        ranked.append({
            "menu_slot": slot_idx,
            "move_id": mid,
            "name": rec.get("name", f"#{mid}"),
            "type": type_name,
            "power": power,
            "accuracy": accuracy,
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


@p.route("/debug/battle")
def http_debug_battle(ctx):
    """Raw read of the battle-state addresses, for troubleshooting auto-detect."""
    flags = struct.unpack("<I", ctx.runtime.read_memory(GBATTLE_TYPE_FLAGS, 4))[0]
    base = GBATTLE_MONS_BASE + OPP_SINGLES_SLOT * BATTLE_MON_SIZE
    species = struct.unpack("<H", ctx.runtime.read_memory(base, 2))[0]
    level = ctx.runtime.read_memory(base + BMON_OFF_LEVEL, 1)[0]
    hp = struct.unpack("<H", ctx.runtime.read_memory(base + BMON_OFF_HP, 2))[0]
    max_hp = struct.unpack("<H", ctx.runtime.read_memory(base + BMON_OFF_MAX_HP, 2))[0]
    return {
        "rom_sha1": getattr(ctx.runtime, "rom_sha1", None),
        "expected_sha1": EMERALD_US_V10_SHA1,
        "autodetect_enabled": _autodetect_enabled,
        "gBattleTypeFlags_addr": f"0x{GBATTLE_TYPE_FLAGS:08X}",
        "gBattleTypeFlags_value": f"0x{flags:08X}",
        "in_battle_judgment": 0 < flags < 0x01000000,
        "gBattleMons_1_addr": f"0x{base:08X}",
        "species": species,
        "species_name": SPECIES_NAMES.get(species, f"#{species}") if species else None,
        "level": level,
        "hp": hp,
        "max_hp": max_hp,
    }


@p.on_frame(every=30)
def _poll_battle_opponent(ctx):
    """Auto-detect: when a battle Pokémon is live in gBattleMons[1], tag it.
    When it goes away, clear (but only if the current tag was auto-set —
    a manual POST takes precedence)."""
    global _opponent
    if not _autodetect_enabled:
        return
    try:
        detected = read_battle_opponent(ctx.runtime)
    except Exception:
        detected = None
    if detected is not None:
        _opponent = detected
        return
    if _opponent is not None and _opponent.get("auto"):
        _opponent = None


@p.on_setup
def setup(ctx):
    global _live, _render_fn, _autodetect_enabled
    from rich.console import Console, Group
    from rich.live import Live

    rom_sha = getattr(ctx.runtime, "rom_sha1", None)
    if rom_sha == EMERALD_US_V10_SHA1:
        _autodetect_enabled = True
        ctx.log("emerald-party: auto-detect enabled (Emerald US v1.0)")
    else:
        ctx.log(f"emerald-party: auto-detect off (rom sha {rom_sha} != Emerald US v1.0); manual POST /opponent only")

    def render():
        party = _build_table(ctx.runtime)
        opp = _build_opponent_panel(ctx.runtime)
        if opp is None:
            return party
        return Group(party, opp)

    _render_fn = render
    _live = Live(render(), console=Console(), refresh_per_second=4, transient=False)
    _live.__enter__()
    ctx.log("emerald-party plugin loaded")


@p.on_frame(every=20)
def refresh(ctx):
    if _live is not None and _render_fn is not None:
        try:
            _live.update(_render_fn())
        except Exception as exc:
            ctx.log(f"party-panel refresh error: {exc}")


@p.on_teardown
def teardown(ctx):
    global _live
    if _live is not None:
        _live.__exit__(None, None, None)
        _live = None
