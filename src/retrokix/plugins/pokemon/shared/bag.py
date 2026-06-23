"""Bag pockets — items, balls, berries, key items, TMs.

Each pocket is an array of `{u16 item_id, u16 quantity ^ (key & 0xFFFF)}` slots
in SaveBlock1. `decode_pocket` is pure; `read_bag` derefs the SaveBlock and
decodes all five pockets. Names/pocket from emerald_items.json.
"""
from __future__ import annotations

import struct

from retrokix.plugins.pokemon.shared.addresses import BAG_POCKETS
from retrokix.plugins.pokemon.shared.data import load_items
from retrokix.plugins.pokemon.shared.saveblock import encryption_key, sb1


def _item_name(item_id: int) -> str:
    return (load_items().get(str(item_id)) or {}).get("name", f"#{item_id}")


def decode_pocket(raw: bytes, key16: int, count: int) -> list[dict]:
    """Decode `count` 4-byte slots; skip empty (id 0) slots."""
    out = []
    for s in range(count):
        item_id = struct.unpack_from("<H", raw, s * 4)[0]
        raw_qty = struct.unpack_from("<H", raw, s * 4 + 2)[0]
        if item_id == 0:
            continue
        out.append({"id": item_id, "name": _item_name(item_id), "qty": raw_qty ^ key16})
    return out


def read_bag(runtime) -> dict[str, list[dict]] | None:
    """All five bag pockets from the running game, or None."""
    try:
        a1 = sb1(runtime)
        key = encryption_key(runtime)
        if a1 is None or key is None:
            return None
        key16 = key & 0xFFFF
        result: dict[str, list[dict]] = {}
        for pocket, (off, count) in BAG_POCKETS.items():
            raw = runtime.read_memory(a1 + off, count * 4)
            result[pocket] = decode_pocket(raw, key16, count)
    except Exception:
        return None
    return result
