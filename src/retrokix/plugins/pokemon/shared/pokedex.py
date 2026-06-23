"""Pokédex bitfield decoding — seen / caught per species, completion stats.

Decodes the ``owned`` / ``seen`` bitfields from the Emerald Pokédex struct in
SaveBlock2. Bits are indexed by *national dex number − 1*; the returned sets
hold national dex numbers (1..386).

Addresses empirically validated against the bundled Emerald ROM + savestates
(party species ⊆ owned ⊆ seen) — see
2026-06-23-retrokix-pokedex-caught-overlay-design.
"""
from __future__ import annotations

import struct

from retrokix.plugins.pokemon.shared.addresses import (
    DEX_FLAGS_BYTES,
    DEX_OWNED_OFF,
    DEX_SEEN_OFF,
    GSAVEBLOCK2_PTR,
)

NATIONAL_DEX_COUNT = 386


def _bitset_to_national(arr: bytes) -> set[int]:
    """National dex numbers whose bit is set in a dex bitfield (bit n-1 → n)."""
    out: set[int] = set()
    for n in range(1, NATIONAL_DEX_COUNT + 1):
        i = n - 1
        if (i >> 3) < len(arr) and (arr[i >> 3] >> (i & 7)) & 1:
            out.add(n)
    return out


def decode_dex_bitfields(owned: bytes, seen: bytes) -> dict[str, set[int]]:
    """Decode the two dex bitfields into national-dex-number sets."""
    return {
        "caught": _bitset_to_national(owned),
        "seen": _bitset_to_national(seen),
    }


def counts(dex: dict[str, set[int]]) -> tuple[int, int, int]:
    """(caught, seen, total) completion counts."""
    return len(dex["caught"]), len(dex["seen"]), NATIONAL_DEX_COUNT


def read_dex(runtime) -> dict[str, set[int]] | None:
    """Read the live Pokédex from a running Emerald runtime, or None if the
    SaveBlock2 pointer is implausible (wrong game / no save yet) or a read fails."""
    try:
        sb2 = struct.unpack("<I", runtime.read_memory(GSAVEBLOCK2_PTR, 4))[0]
        # SaveBlock2 lives in EWRAM (0x02000000..0x0203FFFF). Anything else
        # means this isn't an Emerald save we can decode.
        if not (0x02000000 <= sb2 <= 0x0203FFFF):
            return None
        owned = runtime.read_memory(sb2 + DEX_OWNED_OFF, DEX_FLAGS_BYTES)
        seen = runtime.read_memory(sb2 + DEX_SEEN_OFF, DEX_FLAGS_BYTES)
    except Exception:
        return None
    return decode_dex_bitfields(owned, seen)
