"""SaveBlock indirection for Emerald — deref the gSaveBlock1/2 pointers and the
anti-cheat encryption key. Shared by the world (money/badges) and bag decoders.
"""
from __future__ import annotations

import struct

from retrokix.plugins.pokemon.shared.addresses import (
    ENCRYPTION_KEY_OFF,
    GSAVEBLOCK1_PTR,
    GSAVEBLOCK2_PTR,
)

_EWRAM_LO, _EWRAM_HI = 0x02000000, 0x0203FFFF


def _deref(runtime, ptr: int) -> int | None:
    addr = struct.unpack("<I", runtime.read_memory(ptr, 4))[0]
    return addr if _EWRAM_LO <= addr <= _EWRAM_HI else None


def sb1(runtime) -> int | None:
    """SaveBlock1 EWRAM address, or None if the pointer is implausible."""
    return _deref(runtime, GSAVEBLOCK1_PTR)


def sb2(runtime) -> int | None:
    """SaveBlock2 EWRAM address, or None if the pointer is implausible."""
    return _deref(runtime, GSAVEBLOCK2_PTR)


def encryption_key(runtime, sb2_addr: int | None = None) -> int | None:
    """The u32 anti-cheat key (XORs money + bag quantities)."""
    base = sb2_addr if sb2_addr is not None else sb2(runtime)
    if base is None:
        return None
    return struct.unpack("<I", runtime.read_memory(base + ENCRYPTION_KEY_OFF, 4))[0]
