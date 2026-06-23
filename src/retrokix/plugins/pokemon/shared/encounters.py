"""Wild encounters — read the current map's encounter table from gWildMonHeaders.

`decode_method` / `find_header` are pure over a `rom_read(addr, n) -> bytes`
callable (ROM bus addresses); `read_encounters(runtime)` wires them to the live
game. Per-slot weight tables give each species an aggregate encounter rate.
"""
from __future__ import annotations

import struct
from pathlib import Path

from retrokix.plugins.pokemon.shared.addresses import GWILD_MON_HEADERS, LOCATION_OFF
from retrokix.plugins.pokemon.shared.party import SPECIES_NAMES
from retrokix.plugins.pokemon.shared.saveblock import sb1

_HSIZE = 20
LAND_RATES = [20, 20, 10, 10, 10, 10, 5, 5, 4, 4, 1, 1]
WATER_RATES = [60, 30, 5, 4, 1]
# Fishing: old(2) + good(3) + super(5) rods. Used as per-slot weights for a
# rod-agnostic listing (not a true single-rod %).
FISH_RATES = [70, 30, 60, 20, 20, 40, 40, 15, 4, 1]


def decode_method(rom_read, info_addr: int, weights: list[int]) -> list[dict]:
    """Decode one *MonsInfo struct into aggregated per-species encounters."""
    info = rom_read(info_addr, 8)
    if len(info) < 8:
        return []
    mons_ptr = struct.unpack_from("<I", info, 4)[0]
    n = len(weights)
    mons = rom_read(mons_ptr, n * 4)
    if len(mons) < n * 4:
        return []
    agg: dict[int, dict] = {}
    for i in range(n):
        mn, mx = mons[i * 4], mons[i * 4 + 1]
        sp = struct.unpack_from("<H", mons, i * 4 + 2)[0]
        if sp == 0:
            continue
        e = agg.get(sp)
        if e is None:
            agg[sp] = {
                "species": sp, "name": SPECIES_NAMES.get(sp, f"#{sp}"),
                "rate": weights[i], "min": mn, "max": mx,
            }
        else:
            e["rate"] += weights[i]
            e["min"] = min(e["min"], mn)
            e["max"] = max(e["max"], mx)
    return sorted(agg.values(), key=lambda e: -e["rate"])


def find_header(rom_read, group: int, num: int, base: int = GWILD_MON_HEADERS) -> dict | None:
    """Find the (land, water, fishing) MonsInfo pointers for a map, or None."""
    for i in range(256):
        hdr = rom_read(base + i * _HSIZE, _HSIZE)
        if len(hdr) < _HSIZE or hdr[0] == 0xFF:
            break
        if hdr[0] == group and hdr[1] == num:
            land, water, _rock, fish = struct.unpack_from("<IIII", hdr, 4)
            return {"land": land, "water": water, "fishing": fish}
    return None


def _rom_reader(runtime):
    """A rom_read(addr, n) over the ROM file on disk (stable, deterministic)."""
    data = Path(runtime.rom_path).read_bytes()

    def read(addr: int, n: int) -> bytes:
        o = addr - 0x08000000
        return data[o:o + n] if 0 <= o and o + n <= len(data) else b""

    return read


def read_encounters(runtime) -> dict | None:
    """The current map's wild encounters, or None on a non-Emerald save."""
    try:
        a1 = sb1(runtime)
        if a1 is None:
            return None
        loc = runtime.read_memory(a1 + LOCATION_OFF, 2)
        group, num = loc[0], loc[1]
        rom_read = _rom_reader(runtime)
        result: dict = {"location": (group, num), "land": [], "water": [], "fishing": []}
        hdr = find_header(rom_read, group, num)
        if hdr is None:
            return result
        if hdr["land"]:
            result["land"] = decode_method(rom_read, hdr["land"], LAND_RATES)
        if hdr["water"]:
            result["water"] = decode_method(rom_read, hdr["water"], WATER_RATES)
        if hdr["fishing"]:
            result["fishing"] = decode_method(rom_read, hdr["fishing"], FISH_RATES)
    except Exception:
        return None
    return result
