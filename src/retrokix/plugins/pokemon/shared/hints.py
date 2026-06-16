"""Heuristics for "what to do next" hints.

TODO(slice 5): generate short suggestions based on party state + location +
dex completion. Examples:
  - "Combusken is one level from evolving (Blaziken@36). 1234 EXP to go."
  - "Heal at Pokémon Center: 2 party members below 50% HP."
  - "Your average party level (14) matches the next gym (Roxanne, 12-15)."
  - "You haven't caught any Bug-type Pokémon yet — try Petalburg Woods."
"""
from __future__ import annotations

# TODO(slice 5)
