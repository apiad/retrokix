"""Bag pockets — items, balls, berries, key items, TMs.

TODO(slice 4): read the five pocket arrays from gSaveBlock1Ptr at offsets
0x560 (items), 0x5D8 (keys), 0x650 (balls), 0x690 (TM/HM), 0x790 (berries).
Each slot is {u16 item_id, u16 quantity_xor_encryption_key}.
"""
from __future__ import annotations

# TODO(slice 4)
