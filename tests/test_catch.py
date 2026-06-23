"""Tests for the gen-3 catch-chance math and best-ball selection."""
from __future__ import annotations

from retrokix.plugins.pokemon.shared import catch as C


def test_high_catch_rate_and_ball_is_certain():
    # catch_rate 255 with an Ultra Ball (a = 255*2/3 = 170) is not certain, but
    # a Master-equivalent bonus pushes a >= 255 → guaranteed.
    assert C.catch_chance(255, 255.0) == 1.0


def test_low_catch_rate_full_hp_is_small():
    chance = C.catch_chance(45, 1.0)  # ~6% at full HP with a Poké Ball
    assert 0.03 < chance < 0.10


def test_catch_chance_monotonic_in_catch_rate():
    assert C.catch_chance(255, 1.0) > C.catch_chance(45, 1.0)


def test_better_ball_improves_chance():
    assert C.catch_chance(45, 2.0) > C.catch_chance(45, 1.0)


def test_lower_hp_improves_chance():
    assert C.catch_chance(45, 1.0, hp_fraction=0.1) > C.catch_chance(45, 1.0, hp_fraction=1.0)


def test_best_ball_picks_highest_bonus_owned():
    bag = {"Balls": [
        {"name": "Poke-Ball", "qty": 3},
        {"name": "Great-Ball", "qty": 2},
    ]}
    assert C.best_ball(bag) == ("Great-Ball", 1.5)


def test_best_ball_defaults_when_empty():
    assert C.best_ball({"Balls": []}) == ("Poke-Ball", 1.0)
