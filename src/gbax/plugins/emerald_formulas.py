"""Gen-3 Pokémon formulas — stat calc, type effectiveness, damage range.

Pure functions, no I/O. All integer arithmetic faithful to the C source
(truncating divides). Data and formulas are derived from pokeemerald
(https://github.com/pret/pokeemerald). Pokémon names and game data ©
Nintendo / Game Freak / Creatures.

Source citations are inline per function.
"""
from __future__ import annotations

from functools import cache

from gbax.plugins.emerald_data import (
    load_natures,
    load_species_info,
    load_type_chart,
    load_types,
)

NUM_STATS = 5  # atk, def, spe, spa, spd (HP handled separately)
STAT_NAMES = ["atk", "def", "spe", "spa", "spd"]


def nature_from_personality(personality: int) -> int:
    """`personality % 25`. Source: GetNatureFromPersonality in src/pokemon.c"""
    return personality % 25


def nature_mod(nature_id: int, stat_idx: int) -> int:
    """Return ±1 or 0 for the nature×stat cell, matching ×1.1/×1.0/×0.9.
    stat_idx: 0=atk, 1=def, 2=spe, 3=spa, 4=spd.
    Source: gNatureStatTable in src/pokemon.c"""
    natures = load_natures()
    rec = natures.get(str(nature_id))
    if not rec:
        return 0
    return rec["mods"][stat_idx]


def calc_hp(base: int, iv: int, ev: int, level: int) -> int:
    """HP = ((2*base + IV + EV/4) * level) / 100 + level + 10
    Source: CalculateMonStats in src/pokemon.c"""
    if base == 1:  # Shedinja special case
        return 1
    return ((2 * base + iv + ev // 4) * level) // 100 + level + 10


def calc_stat(base: int, iv: int, ev: int, level: int, nature_id: int, stat_idx: int) -> int:
    """stat = (((2*base + IV + EV/4) * level) / 100 + 5) * nature / 10
    Source: CalculateMonStats in src/pokemon.c"""
    base_stat = ((2 * base + iv + ev // 4) * level) // 100 + 5
    mod = nature_mod(nature_id, stat_idx)
    if mod > 0:
        return base_stat * 11 // 10
    if mod < 0:
        return base_stat * 9 // 10
    return base_stat


def decode_ivs(misc_word: int) -> dict:
    """Unpack the 32-bit Misc-substructure IV bitfield.
    Source: SetBoxMonData IV unpacking in src/pokemon.c."""
    return {
        "hp":  misc_word        & 0x1F,
        "atk": (misc_word >>  5) & 0x1F,
        "def": (misc_word >> 10) & 0x1F,
        "spe": (misc_word >> 15) & 0x1F,
        "spa": (misc_word >> 20) & 0x1F,
        "spd": (misc_word >> 25) & 0x1F,
        "is_egg": (misc_word >> 30) & 1,
        "ability_num": (misc_word >> 31) & 1,
    }


@cache
def _type_chart_indexed() -> dict[tuple[int, int], int]:
    """Map (atk_type, def_type) → multiplier×10. Last entry per pair wins.
    Source: gTypeEffectiveness in src/battle_main.c (pre-Foresight section)."""
    chart = load_type_chart()
    return {(atk, df): mul for atk, df, mul in chart}


def type_effectiveness(attack_type: int, defender_types: list[int]) -> float:
    """Effective multiplier for a move-type hitting a 1- or 2-typed defender.
    Each leg: 0/0.5/1/2. Combined: product of legs.
    Source: Cmd_typecalc in src/battle_script_commands.c (Levitate/Wonder-Guard
    handled by the caller — not in this pure function)."""
    chart = _type_chart_indexed()
    mul = 1.0
    seen = set()
    for d in defender_types:
        if d in seen:
            continue  # dual-type Pokémon with same type listed twice (single type)
        seen.add(d)
        m = chart.get((attack_type, d), 10)  # default ×1
        mul *= m / 10.0
    return mul


def weaknesses(defender_types: list[int]) -> list[tuple[int, float]]:
    """Return [(attack_type_id, multiplier), ...] sorted desc by multiplier,
    only entries with multiplier > 1."""
    types = load_types()
    out = []
    for atk_id_str in types:
        atk_id = int(atk_id_str)
        if atk_id == 9:  # TYPE_MYSTERY ('???') — skip
            continue
        mul = type_effectiveness(atk_id, defender_types)
        if mul > 1.0:
            out.append((atk_id, mul))
    out.sort(key=lambda x: (-x[1], x[0]))
    return out


def resistances(defender_types: list[int]) -> list[tuple[int, float]]:
    """Same shape as weaknesses, but for multiplier < 1 (including 0)."""
    types = load_types()
    out = []
    for atk_id_str in types:
        atk_id = int(atk_id_str)
        if atk_id == 9:
            continue
        mul = type_effectiveness(atk_id, defender_types)
        if mul < 1.0:
            out.append((atk_id, mul))
    out.sort(key=lambda x: (x[1], x[0]))
    return out


# --- Damage ---

# Stat-stage multiplier table: index = stage+6, gen-3 stat ratios are X/100.
# Source: gStatStageRatios in src/battle_util.c (numerator only — denominator
# is always 100 for stats, and 100/X for accuracy/evasion).
STAT_STAGE_NUM = [33, 36, 43, 50, 60, 75, 100, 133, 166, 200, 250, 300, 400]


def stat_stage_mul(stage: int) -> float:
    """Multiplier for a stat stage in [-6, +6]."""
    idx = max(-6, min(6, stage)) + 6
    return STAT_STAGE_NUM[idx] / 100.0


def calc_damage(
    *,
    attacker_level: int,
    attacker_atk: int,
    defender_def: int,
    move_power: int,
    move_type: int,
    attacker_types: list[int],
    defender_types: list[int],
    is_crit: bool = False,
    has_stab: bool | None = None,
    burn: bool = False,
    screen: bool = False,
    weather_mod: float = 1.0,
    flash_fire: bool = False,
    helping_hand: bool = False,
) -> tuple[int, int]:
    """Return (min, max) damage range for a single hit.

    Gen-3 damage chain (Source: CalculateBaseDamage in src/pokemon.c, applied
    around Cmd_damagecalc in src/battle_script_commands.c):

      base = (((2*L/5 + 2) * power * atk) / def) / 50
      apply burn (/2 if physical and burned), screens (/2), doubles, etc.
      base += 2
      base *= stab (×1.5 if move-type ∈ attacker types)
      base *= type_effectiveness (defender legs)
      base *= crit (×2)
      base *= rand in [85, 100] / 100

    Returns the min (85%) and max (100%) integer damage values.
    """
    if move_power == 0:
        return (0, 0)

    base = (((2 * attacker_level // 5 + 2) * move_power * attacker_atk) // defender_def) // 50

    if burn:
        base //= 2
    if screen:
        base //= 2
    if flash_fire:
        base = base * 3 // 2
    if helping_hand:
        base = base * 3 // 2

    base = int(base * weather_mod)
    base += 2

    stab = (move_type in attacker_types) if has_stab is None else has_stab
    if stab:
        base = base * 15 // 10

    eff = type_effectiveness(move_type, defender_types)
    base = int(base * eff)

    if is_crit:
        base *= 2

    if base <= 0:
        return (0, 0)

    return (base * 85 // 100, base)


# Source: sCriticalHitChance in src/battle_script_commands.c
CRIT_CHANCE_DENOM = [16, 8, 4, 3, 2]


def crit_chance_pct(stage: int) -> float:
    """Percent crit chance for a stage in [0, 4]."""
    s = max(0, min(4, stage))
    return 100.0 / CRIT_CHANCE_DENOM[s]


# --- Helpers ---

def species_base_stats(species_id: int) -> dict | None:
    info = load_species_info()
    return info.get(str(species_id))


def species_types(species_id: int) -> list[int] | None:
    """Return the species' type IDs (always a 2-element list; mono-types repeat)."""
    info = species_base_stats(species_id)
    if not info or "types" not in info:
        return None
    types_lookup = load_types()
    out = []
    for t in info["types"]:
        # "GRASS" → 12, "FIGHTING" → 1
        for tid_str, disp in types_lookup.items():
            if disp.upper() == t.upper():
                out.append(int(tid_str))
                break
    return out if len(out) == 2 else None
