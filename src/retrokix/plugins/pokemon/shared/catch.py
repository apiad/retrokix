"""Gen-3 catch-chance math + best-ball selection.

`catch_chance` returns the probability of a successful capture for a single
throw, using the standard gen-3 shake formula. At full HP with no status the HP
term reduces to 1/3, so the chance depends only on catch_rate × ball bonus —
which is what the Route panel shows for a fresh wild encounter.
"""
from __future__ import annotations

import math

# Ball → capture multiplier (situational balls default to 1.0).
_BALL_BONUS = {
    "Master-Ball": 255.0,
    "Ultra-Ball": 2.0,
    "Great-Ball": 1.5,
    "Safari-Ball": 1.5,
}


def catch_chance(
    catch_rate: int,
    ball_bonus: float,
    hp_fraction: float = 1.0,
    status_bonus: float = 1.0,
) -> float:
    """Probability (0..1) of catching on one throw."""
    hp_term = (3.0 - 2.0 * hp_fraction) / 3.0
    a = catch_rate * ball_bonus * status_bonus * hp_term
    if a >= 255:
        return 1.0
    if a <= 0:
        return 0.0
    b = 1048560.0 / math.sqrt(math.sqrt(16711680.0 / a))
    per_shake = b / 65536.0
    return per_shake**4


def best_ball(bag: dict) -> tuple[str, float]:
    """The highest-bonus ball the player owns, or the default Poké Ball."""
    best_name, best_bonus = "Poke-Ball", 1.0
    for item in bag.get("Balls", []):
        if item.get("qty", 0) <= 0:
            continue
        bonus = _BALL_BONUS.get(item["name"], 1.0)
        if bonus > best_bonus:
            best_name, best_bonus = item["name"], bonus
    return best_name, best_bonus
