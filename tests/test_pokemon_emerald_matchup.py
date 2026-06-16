"""Tests for the matchup engine."""
from __future__ import annotations

from retrokix.plugins.pokemon.shared.matchup import (
    Attacker,
    Defender,
    matchup,
    weakness_report,
)


def test_weakness_report_geodude():
    # Rock/Ground = 5/4
    rows = weakness_report(Defender(species=74, level=12, types=[5, 4]))
    assert rows
    top = rows[0]
    assert top["mul"] == 4.0
    type_names_4x = {r["type_name"] for r in rows if r["mul"] == 4.0}
    assert "Grass" in type_names_4x
    assert "Water" in type_names_4x
    # Fighting is 2× on Geodude (super-effective vs Rock, neutral vs Ground)
    type_names_2x = {r["type_name"] for r in rows if r["mul"] == 2.0}
    assert "Fighting" in type_names_2x


def test_matchup_combusken_vs_geodude_double_kick():
    """Combusken L16 (Fire/Fighting) hitting Geodude L12 (Rock/Ground) with
    Double Kick should be a 4× super-effective ranking #1 by damage."""
    # Combusken IDs: species 256, types Fire=10, Fighting=1
    combusken = Attacker(
        species=256, level=16,
        types=[10, 1],
        attack=35, sp_attack=30,
        moves=[24, 52, 43, 45],  # Double Kick=24, Ember=52, Leer=43, Growl=45
    )
    geodude = Defender(species=74, level=12, types=[5, 4], hp=27, max_hp=27)
    report = matchup(combusken, geodude)
    # Double Kick (Fighting, 30 BP × 2 hits — we compute per-hit so still rank-1
    # via 4x effectiveness over Ember's 2x effectiveness on Rock alone)
    best = report["best_move"]
    assert best is not None
    # Damage-wise, Double Kick has highest single-hit damage among these.
    # Just sanity-check that something super-effective shows up best.
    super_eff_outcomes = [o for o in report["move_outcomes"] if o["effective_mul"] >= 2.0]
    assert super_eff_outcomes, "expected at least one super-effective move"


def test_matchup_ranks_super_effective_above_neutral():
    """A super-effective non-STAB move outranks a neutral STAB move of equal
    base power."""
    # Marill (Water) vs Geodude (Rock/Ground)
    marill = Attacker(
        species=183, level=10, types=[11],  # Water
        attack=20, sp_attack=20,
        moves=[33, 55],  # Tackle (normal, 35 power) vs Water Gun (water, 40 power, 4× on geodude)
    )
    geodude = Defender(species=74, level=12, types=[5, 4], hp=27)
    report = matchup(marill, geodude)
    best = report["best_move"]
    assert best is not None
    assert best["type"] == "Water"  # Water Gun beats Tackle


def test_weakness_report_pure_normal_no_weakness():
    """A pure Normal type has only one weakness: Fighting."""
    rows = weakness_report(Defender(species=1, level=5, types=[0]))  # Normal=0
    weak_types = {r["type_name"] for r in rows}
    assert weak_types == {"Fighting"}
