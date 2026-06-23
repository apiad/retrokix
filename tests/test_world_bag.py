"""Tests for the Emerald world (money/badges) and bag pure decoders."""
from __future__ import annotations

import struct

from retrokix.plugins.pokemon.shared import bag as B
from retrokix.plugins.pokemon.shared import world as W
from retrokix.plugins.pokemon.shared.addresses import FLAG_BADGE01


def test_decode_money_xor():
    assert W.decode_money(0x846E2E69, 0x846E0CB1) == 8920


def test_read_badges_first_badge():
    flags = bytearray(0x120)
    flags[FLAG_BADGE01 >> 3] |= 1 << (FLAG_BADGE01 & 7)
    badges = W.read_badges(bytes(flags))
    assert badges[0] is True
    assert sum(badges) == 1


def test_read_badges_none():
    assert sum(W.read_badges(bytes(0x120))) == 0


def test_decode_pocket_decrypts_quantity_and_names():
    key16 = 0x0CB1
    raw = (
        struct.pack("<HH", 4, 3 ^ key16)  # Poke-Ball x3
        + struct.pack("<HH", 3, 2 ^ key16)  # Great-Ball x2
        + struct.pack("<HH", 0, 0)  # empty slot — skipped
    )
    pocket = B.decode_pocket(raw, key16, 3)
    assert pocket == [
        {"id": 4, "name": "Poke-Ball", "qty": 3},
        {"id": 3, "name": "Great-Ball", "qty": 2},
    ]


def test_decode_pocket_unknown_id_falls_back():
    key16 = 0x0000
    raw = struct.pack("<HH", 60000, 1)
    pocket = B.decode_pocket(raw, key16, 1)
    assert pocket[0]["name"] == "#60000"


def test_tm_hm_item_names():
    # TMs/HMs aren't in emerald_items.json; computed from id (289=TM01, 339=HM01).
    assert B._item_name(289) == "TM01"
    assert B._item_name(327) == "TM39"  # Roxanne's Rock Tomb
    assert B._item_name(338) == "TM50"
    assert B._item_name(339) == "HM01"
    assert B._item_name(346) == "HM08"
