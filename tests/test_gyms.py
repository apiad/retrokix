"""Tests for gym progression + computed type-matchup planning."""
from __future__ import annotations

from retrokix.plugins.pokemon.shared import gyms as G


def test_next_gym_by_badge_count():
    assert G.next_gym(0)["leader"] == "Roxanne"
    assert G.next_gym(1)["leader"] == "Brawly"
    assert G.next_gym(1)["type"] == "Fighting"
    assert G.next_gym(8) is None  # Elite Four next


def test_gym_plan_for_fighting_is_correct():
    # Internal species ids: Wingull 309 (Water/Flying), Abra 63 (Psychic),
    # Combusken 281 (Fire/Fighting).
    party = [
        {"name": "Wingull", "species": 309},
        {"name": "Abra", "species": 63},
        {"name": "Combusken", "species": 281},
    ]
    plan = G.gym_plan(1, party)  # Fighting
    # Flying & Psychic beat Fighting — the actual correct answer.
    assert "Flying" in plan["se_types"]
    assert "Psychic" in plan["se_types"]
    # Abra (Psychic) and Wingull (Flying) resist Fighting; Combusken does not.
    resist_names = " ".join(plan["resist"])
    assert "Abra" in resist_names
    assert "Wingull" in resist_names
    assert "Combusken" not in resist_names


def test_gym_plan_skips_unknown_species():
    plan = G.gym_plan(1, [{"name": "Mystery", "species": 0}])
    assert plan["resist"] == [] and plan["weak"] == [] and plan["neutral"] == []
