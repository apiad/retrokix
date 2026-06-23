"""Tests for Pokédex seen/caught bitfield decoding (shared/pokedex.py)."""
from __future__ import annotations

from retrokix.plugins.pokemon.shared import pokedex as D


def _bits(*national_nums: int) -> bytes:
    """Build a 52-byte dex bitfield with the given national numbers set."""
    arr = bytearray(52)
    for n in national_nums:
        i = n - 1
        arr[i >> 3] |= 1 << (i & 7)
    return bytes(arr)


def test_decode_maps_bit_to_national_number():
    owned = _bits(1, 63, 386)
    seen = _bits(1, 63, 183, 386)
    dex = D.decode_dex_bitfields(owned, seen)
    assert dex["caught"] == {1, 63, 386}
    assert dex["seen"] == {1, 63, 183, 386}


def test_decode_empty_is_empty():
    dex = D.decode_dex_bitfields(bytes(52), bytes(52))
    assert dex["caught"] == set()
    assert dex["seen"] == set()


def test_decode_ignores_bits_beyond_386():
    # The 52-byte array has 416 bits; only national 1..386 are meaningful.
    owned = _bits(386)
    owned = bytearray(owned)
    owned[51] = 0xFF  # bits 408..415 — must be ignored
    dex = D.decode_dex_bitfields(bytes(owned), bytes(52))
    assert dex["caught"] == {386}


def test_counts():
    dex = {"caught": {1, 2, 3}, "seen": {1, 2, 3, 4, 5}}
    caught, seen, total = D.counts(dex)
    assert (caught, seen, total) == (3, 5, 386)
