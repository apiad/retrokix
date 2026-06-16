"""Pokédex bitfield decoding — seen / caught per species, completion stats.

TODO(slice 4): decode dexSeen and dexCaught bitfields from SaveBlock1.
Each is ~52 bytes for 412 species. Expose count + per-species seen/caught.
"""
from __future__ import annotations

# TODO(slice 4)
