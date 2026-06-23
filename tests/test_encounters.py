"""Tests for wild-encounter decoding (pure + live ROM)."""
from __future__ import annotations

import struct
from pathlib import Path

import pytest

from retrokix.plugins.pokemon.shared import encounters as E


def _synthetic_rom():
    """A rom_read backed by a sparse byte map for two land slots of one species."""
    mem: dict[int, int] = {}

    def put(addr: int, b: bytes) -> None:
        for i, x in enumerate(b):
            mem[addr + i] = x

    # MonsInfo @ 0x08000100: rate=20, pad, ptr→0x08000200
    put(0x08000100, bytes([20, 0, 0, 0]) + struct.pack("<I", 0x08000200))
    # two WildPokemon slots: species 261, L2-2 then L2-3
    put(0x08000200, struct.pack("<BBH", 2, 2, 261) + struct.pack("<BBH", 2, 3, 261))

    def rom_read(addr: int, n: int) -> bytes:
        return bytes(mem.get(addr + i, 0) for i in range(n))

    return rom_read


def test_decode_method_aggregates_species_rate_and_levels():
    rom_read = _synthetic_rom()
    rows = E.decode_method(rom_read, 0x08000100, [20, 20])
    assert len(rows) == 1
    row = rows[0]
    assert row["species"] == 261
    assert row["rate"] == 40        # both slots same species
    assert row["min"] == 2 and row["max"] == 3


def test_decode_method_skips_zero_species():
    mem = {}

    def rom_read(addr, n):
        return bytes(mem.get(addr + i, 0) for i in range(n))

    # all-zero ROM → no mons
    assert E.decode_method(rom_read, 0x08000100, [20]) == []


# ---- live empirical ----

ROM = Path.home() / ".retrokix/roms/Pokemon - Emerald Version (USA, Europe).gba"


@pytest.mark.skipif(not ROM.exists(), reason="Emerald ROM not present")
def test_live_route101_land_encounters():
    data = ROM.read_bytes()

    def rom_read(addr, n):
        o = addr - 0x08000000
        return data[o:o + n] if 0 <= o and o + n <= len(data) else b""

    hdr = E.find_header(rom_read, 0, 16)  # map(0,16) = Route 101
    assert hdr is not None and hdr["land"]
    land = E.decode_method(rom_read, hdr["land"], E.LAND_RATES)
    names = {r["name"] for r in land}
    assert {"Poochyena", "Wurmple", "Zigzagoon"} <= names
    assert all(2 <= r["min"] <= r["max"] <= 3 for r in land)
