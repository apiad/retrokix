"""World state — location, money, badges, play time.

TODO(slice 4): add SaveBlock indirection (gSaveBlock1Ptr, gSaveBlock2Ptr),
read player location (mapGroup/mapNum/x/y), decoded money (XOR'd), badge
bitfield (0x867..0x86E flag IDs), play time hours/minutes/seconds.

Source: pokeemerald include/global.h struct SaveBlock1 / SaveBlock2,
src/money.c (GetMoney via gSaveBlock2Ptr->encryptionKey XOR).
"""
from __future__ import annotations

# TODO(slice 4)
