"""World state — trainer identity, money, badges, play time.

Pure decoders (`decode_money`, `read_badges`) + a thin `read_world(runtime)`
that derefs the SaveBlocks. Money/key handling per src/money.c (XOR with
gSaveBlock2Ptr->encryptionKey). Addresses validated against the bundled save.
"""
from __future__ import annotations

import struct

from retrokix.plugins.pokemon.shared.addresses import (
    FLAG_BADGE01,
    FLAGS_OFF,
    MONEY_OFF,
    PLAYTIME_HOURS_OFF,
    TRAINER_GENDER_OFF,
    TRAINER_ID_OFF,
    TRAINER_NAME_OFF,
)
from retrokix.plugins.pokemon.shared.saveblock import encryption_key, sb1, sb2
from retrokix.plugins.pokemon.shared.text import decode_name


def decode_money(raw: int, key: int) -> int:
    return (raw ^ key) & 0xFFFFFFFF


def read_badges(flags: bytes) -> list[bool]:
    """The eight gym badges from the SaveBlock1 flags array."""
    out = []
    for i in range(8):
        fid = FLAG_BADGE01 + i
        out.append(bool((flags[fid >> 3] >> (fid & 7)) & 1))
    return out


def read_world(runtime) -> dict | None:
    """Trainer/money/badges/play-time from the running game, or None."""
    try:
        a1, a2 = sb1(runtime), sb2(runtime)
        if a1 is None or a2 is None:
            return None
        key = encryption_key(runtime, a2)
        if key is None:
            return None
        money_raw = struct.unpack("<I", runtime.read_memory(a1 + MONEY_OFF, 4))[0]
        flags = runtime.read_memory(a1 + FLAGS_OFF, 0x120)
        badges = read_badges(flags)
        h = struct.unpack("<H", runtime.read_memory(a2 + PLAYTIME_HOURS_OFF, 2))[0]
        m = runtime.read_memory(a2 + PLAYTIME_HOURS_OFF + 2, 1)[0]
        s = runtime.read_memory(a2 + PLAYTIME_HOURS_OFF + 3, 1)[0]
        name = decode_name(runtime.read_memory(a2 + TRAINER_NAME_OFF, 8))
        gender = runtime.read_memory(a2 + TRAINER_GENDER_OFF, 1)[0]
        tid = struct.unpack("<H", runtime.read_memory(a2 + TRAINER_ID_OFF, 2))[0]
    except Exception:
        return None
    return {
        "trainer": {"name": name, "id": tid, "gender": "F" if gender else "M"},
        "money": decode_money(money_raw, key),
        "badges": {"count": sum(badges), "list": badges},
        "play_time": {"h": h, "m": m, "s": s},
    }
