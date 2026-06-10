"""Matchup engine — given a defender (species, level, types, HP), report
weaknesses and rank our party's moves by predicted damage range.

Pure-function composition over emerald_formulas + emerald_data. No I/O.
Source attribution per function lives in emerald_formulas.py.
"""
from __future__ import annotations

from dataclasses import dataclass, field

from gbax.plugins.emerald_data import (
    load_moves,
    load_species_info,
    load_types,
)
from gbax.plugins.emerald_formulas import (
    calc_damage,
    type_effectiveness,
    weaknesses,
)


@dataclass
class Defender:
    species: int
    level: int
    types: list[int]
    hp: int | None = None
    max_hp: int | None = None
    defense: int | None = None    # if known (in battle); else estimate from base
    sp_defense: int | None = None
    nickname: str | None = None
    is_wild: bool = True


@dataclass
class Attacker:
    """One of our party slots, ready to evaluate against a defender."""
    species: int
    level: int
    types: list[int]
    attack: int
    sp_attack: int
    nickname: str | None = None
    moves: list[int] = field(default_factory=list)
    held_item: int | None = None


@dataclass
class MoveOutcome:
    move_id: int
    move_name: str
    move_type: int
    move_type_name: str
    power: int
    accuracy: int
    effective_mul: float
    damage_min: int
    damage_max: int
    likely_ohko: bool   # min >= defender.hp
    guaranteed_ohko: bool   # max >= defender.hp (technically: 85% roll OHKO)


def _type_name(type_id: int) -> str:
    return load_types().get(str(type_id), f"#{type_id}")


def _is_physical_type(type_id: int) -> bool:
    """Gen-3 uses per-type phys/spec split. Source: include/constants/battle.h
    (a move's category derives from its type)."""
    # 0=Normal, 1=Fighting, 2=Flying, 3=Poison, 4=Ground, 5=Rock, 6=Bug, 7=Ghost, 8=Steel
    return type_id in (0, 1, 2, 3, 4, 5, 6, 7, 8)


def weakness_report(defender: Defender) -> list[dict]:
    """Defender's type weaknesses, sorted by multiplier desc."""
    rows = []
    for atk_id, mul in weaknesses(defender.types):
        rows.append({
            "type_id": atk_id,
            "type_name": _type_name(atk_id),
            "mul": mul,
        })
    return rows


def evaluate_move(
    attacker: Attacker,
    defender: Defender,
    move_id: int,
    *,
    defender_def_estimate: int | None = None,
    defender_spdef_estimate: int | None = None,
) -> MoveOutcome | None:
    moves = load_moves()
    rec = moves.get(str(move_id))
    if not rec:
        return None
    power = rec.get("power", 0)
    accuracy = rec.get("accuracy", 100)
    type_name = rec.get("type", "NORMAL")
    types_lookup = load_types()
    type_id = next(
        (int(k) for k, v in types_lookup.items() if v.upper() == type_name.upper()),
        0,
    )
    physical = _is_physical_type(type_id)
    atk_stat = attacker.attack if physical else attacker.sp_attack
    if defender_def_estimate is not None and physical:
        def_stat = defender_def_estimate
    elif defender_spdef_estimate is not None and not physical:
        def_stat = defender_spdef_estimate
    elif defender.defense is not None and physical:
        def_stat = defender.defense
    elif defender.sp_defense is not None and not physical:
        def_stat = defender.sp_defense
    else:
        def_stat = _estimate_defense_from_base(defender, physical)
    dmg_min, dmg_max = calc_damage(
        attacker_level=attacker.level,
        attacker_atk=atk_stat,
        defender_def=def_stat,
        move_power=power,
        move_type=type_id,
        attacker_types=attacker.types,
        defender_types=defender.types,
    )
    eff = type_effectiveness(type_id, defender.types)
    hp = defender.hp if defender.hp is not None else _estimate_max_hp(defender)
    return MoveOutcome(
        move_id=move_id,
        move_name=rec.get("name", f"#{move_id}"),
        move_type=type_id,
        move_type_name=_type_name(type_id),
        power=power,
        accuracy=accuracy,
        effective_mul=eff,
        damage_min=dmg_min,
        damage_max=dmg_max,
        likely_ohko=hp is not None and dmg_min >= hp,
        guaranteed_ohko=hp is not None and dmg_max >= hp,
    )


def _estimate_max_hp(defender: Defender) -> int | None:
    """If defender HP isn't directly known, estimate from baseHP + level
    with neutral IV/EV. Cheap approximation for out-of-battle previews."""
    info = load_species_info().get(str(defender.species))
    if not info:
        return None
    base = info.get("baseHP")
    if base is None:
        return None
    # Neutral assumption: IV=15 (mid-roll), EV=0
    return ((2 * base + 15) * defender.level) // 100 + defender.level + 10


def _estimate_defense_from_base(defender: Defender, physical: bool) -> int:
    info = load_species_info().get(str(defender.species)) or {}
    base = info.get("baseDefense" if physical else "baseSpDefense", 50)
    return ((2 * base + 15) * defender.level) // 100 + 5


def matchup(attacker: Attacker, defender: Defender) -> dict:
    """Top-level report — weaknesses + per-move outcomes, sorted best-first."""
    outcomes = []
    for mid in attacker.moves:
        oc = evaluate_move(attacker, defender, mid)
        if oc is not None:
            outcomes.append(oc)
    outcomes.sort(key=lambda o: o.damage_max, reverse=True)
    return {
        "defender": _defender_dict(defender),
        "attacker": _attacker_dict(attacker),
        "weaknesses": weakness_report(defender),
        "move_outcomes": [_outcome_dict(o) for o in outcomes],
        "best_move": _outcome_dict(outcomes[0]) if outcomes else None,
    }


def _defender_dict(d: Defender) -> dict:
    return {
        "species": d.species,
        "level": d.level,
        "types": [_type_name(t) for t in d.types],
        "type_ids": d.types,
        "hp": d.hp,
        "max_hp": d.max_hp,
        "nickname": d.nickname,
    }


def _attacker_dict(a: Attacker) -> dict:
    return {
        "species": a.species,
        "level": a.level,
        "types": [_type_name(t) for t in a.types],
        "attack": a.attack,
        "sp_attack": a.sp_attack,
        "nickname": a.nickname,
    }


def _outcome_dict(o: MoveOutcome) -> dict:
    return {
        "move_id": o.move_id,
        "name": o.move_name,
        "type": o.move_type_name,
        "power": o.power,
        "accuracy": o.accuracy,
        "effective_mul": round(o.effective_mul, 2),
        "damage_min": o.damage_min,
        "damage_max": o.damage_max,
        "likely_ohko": o.likely_ohko,
        "guaranteed_ohko": o.guaranteed_ohko,
    }
