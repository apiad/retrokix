"""Gen-3 (Emerald) in-game text → ASCII. Minimal charmap covering names:
letters, digits, space, and common punctuation. ``0xFF`` terminates a string.

Validated: ``BB C6 BF D2`` → "ALEX".
"""
from __future__ import annotations

_CHARMAP: dict[int, str] = {0x00: " "}
for _i, _c in enumerate("ABCDEFGHIJKLMNOPQRSTUVWXYZ"):
    _CHARMAP[0xBB + _i] = _c
for _i, _c in enumerate("abcdefghijklmnopqrstuvwxyz"):
    _CHARMAP[0xD5 + _i] = _c
for _i in range(10):
    _CHARMAP[0xA1 + _i] = str(_i)
# A few common punctuation glyphs (gen-3 codes).
_CHARMAP.update({0xAB: "!", 0xAC: "?", 0xAD: ".", 0xB8: ",", 0xBA: "/", 0xB0: "…"})

TERMINATOR = 0xFF


def decode_name(raw: bytes) -> str:
    """Decode a gen-3 name field to ASCII, stopping at the 0xFF terminator.
    Unknown bytes are dropped."""
    out = []
    for b in raw:
        if b == TERMINATOR:
            break
        ch = _CHARMAP.get(b)
        if ch is not None:
            out.append(ch)
    return "".join(out).rstrip()
