"""Anchor-point tests for emerald gen-3 formulas."""
from __future__ import annotations

from retrokix.plugins.pokemon.shared.formulas import (
    calc_hp,
    calc_stat,
    crit_chance_pct,
    decode_ivs,
    nature_from_personality,
    nature_mod,
    type_effectiveness,
    weaknesses,
)


def test_calc_hp_neutral():
    # Bulbasaur baseHP=45, IV=0, EV=0, L100: ((90+0+0)*100)/100 + 100 + 10 = 200
    assert calc_hp(45, 0, 0, 100) == 200


def test_calc_hp_perfect():
    # Bulbasaur baseHP=45, IV=31, EV=252 (max), L100:
    # ((90+31+63)*100)/100 + 100 + 10 = 184 + 110 = 294
    assert calc_hp(45, 31, 252, 100) == 294


def test_calc_hp_shedinja_special():
    assert calc_hp(1, 31, 252, 100) == 1


def test_calc_stat_adamant_attack_bulbasaur_L50():
    # baseAtk=49, nature=Adamant (+atk) is nature_id=3
    # base = ((98+31+0)*50)/100 + 5 = 64 + 5 = 69
    # *11/10 = 75
    assert calc_stat(49, 31, 0, 50, 3, 0) == 75


def test_nature_from_personality():
    assert nature_from_personality(0) == 0
    assert nature_from_personality(25) == 0
    assert nature_from_personality(3) == 3
    assert nature_from_personality(100) == 0


def test_nature_mod_adamant_attack():
    # Adamant (id 3): +atk -spa
    assert nature_mod(3, 0) == 1   # atk
    assert nature_mod(3, 3) == -1  # spa
    assert nature_mod(3, 1) == 0   # def unaffected


def test_nature_mod_hardy_neutral():
    # Hardy (id 0): all zero
    for i in range(5):
        assert nature_mod(0, i) == 0


def test_decode_ivs_zero():
    out = decode_ivs(0)
    assert out["hp"] == 0
    assert out["atk"] == 0
    assert out["is_egg"] == 0


def test_decode_ivs_max():
    # All 6 IVs = 31, isEgg=0, abilityNum=0
    word = 0x1F | (0x1F << 5) | (0x1F << 10) | (0x1F << 15) | (0x1F << 20) | (0x1F << 25)
    out = decode_ivs(word)
    for k in ("hp", "atk", "def", "spe", "spa", "spd"):
        assert out[k] == 31
    assert out["is_egg"] == 0


def test_type_effectiveness_grass_vs_rock_ground():
    # Geodude is Rock/Ground. Grass is super-effective vs both. 2×2 = 4×.
    # TYPE_GRASS=12, TYPE_ROCK=5, TYPE_GROUND=4
    assert type_effectiveness(12, [5, 4]) == 4.0


def test_type_effectiveness_water_vs_fire():
    # TYPE_WATER=11, TYPE_FIRE=10 — super effective ×2
    assert type_effectiveness(11, [10]) == 2.0


def test_type_effectiveness_electric_vs_ground():
    # TYPE_ELECTRIC=13, TYPE_GROUND=4 — no effect ×0
    assert type_effectiveness(13, [4]) == 0.0


def test_type_effectiveness_normal_vs_ghost():
    # TYPE_NORMAL=0, TYPE_GHOST=7 — no effect ×0
    assert type_effectiveness(0, [7]) == 0.0


def test_weaknesses_geodude():
    # Geodude is Rock/Ground. Grass and Water are 4× (2× on each leg).
    # Fighting is 2× on Rock but 1× on Ground → 2× total (NOT 4×).
    out = weaknesses([5, 4])
    top = [(t, m) for t, m in out if m == 4.0]
    top_ids = {t for t, _ in top}
    assert 11 in top_ids  # WATER
    assert 12 in top_ids  # GRASS
    # Fighting (1) should appear at 2×, not 4×
    fighting = [m for t, m in out if t == 1]
    assert fighting and fighting[0] == 2.0


def test_crit_chance_stages():
    # gen-3: 1/16 = 6.25%, 1/8 = 12.5%, 1/4 = 25%, 1/3 = ~33%, 1/2 = 50%
    assert crit_chance_pct(0) == 100 / 16
    assert crit_chance_pct(1) == 100 / 8
    assert crit_chance_pct(2) == 25.0
    assert abs(crit_chance_pct(3) - 33.33) < 0.5
    assert crit_chance_pct(4) == 50.0
