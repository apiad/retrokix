"""Tests for the Pokémon party-slot substructure decoder.

Construct a known plaintext, encrypt it with a known personality/otId,
feed it through the decoder, assert we recover the original."""
from __future__ import annotations

import struct

from gbax.plugins.pokemon.shared.party import (
    _decode_status,
    _decrypt_block,
    _parse_attacks,
    _parse_evs,
    _parse_growth,
    _parse_misc,
    _split_substructures,
)


def _build_growth(species, held, exp, pp_bonuses, friendship):
    return struct.pack("<HHIBBH", species, held, exp, pp_bonuses, friendship, 0)


def _build_attacks(moves, pp):
    assert len(moves) == 4 and len(pp) == 4
    return struct.pack("<HHHH", *moves) + bytes(pp)


def _build_evs(hp, atk, df, spe, spa, spd, contest=(0,)*6):
    return bytes([hp, atk, df, spe, spa, spd]) + bytes(contest)


def _build_misc(pokerus, met_loc, met_level, origin_game, ball, ot_gender,
                ivs, is_egg, ability_num, ribbons):
    origin = (met_level & 0x7F) | ((origin_game & 0x0F) << 7) | ((ball & 0x0F) << 11) | ((ot_gender & 1) << 15)
    iv_word = (
        (ivs["hp"] & 0x1F)
        | ((ivs["atk"] & 0x1F) << 5)
        | ((ivs["def"] & 0x1F) << 10)
        | ((ivs["spe"] & 0x1F) << 15)
        | ((ivs["spa"] & 0x1F) << 20)
        | ((ivs["spd"] & 0x1F) << 25)
        | ((is_egg & 1) << 30)
        | ((ability_num & 1) << 31)
    )
    return struct.pack("<BBHII", pokerus, met_loc, origin, iv_word, ribbons)


def _xor_encrypt(plain: bytes, key: int) -> bytes:
    enc = bytearray()
    for i in range(0, 48, 4):
        w = struct.unpack("<I", plain[i:i + 4])[0] ^ key
        enc.extend(struct.pack("<I", w))
    return bytes(enc)


def test_decrypt_then_decrypt_identity():
    """XOR with the same key twice returns the original."""
    plain = bytes(range(48))
    key = 0xDEADBEEF
    enc = _xor_encrypt(plain, key)
    assert _decrypt_block(enc, key) == plain


def test_split_substructures_canonical_order():
    """Personality 0 → permutation 'GAEM' → first 12 bytes are Growth."""
    plain = bytes(range(48))
    subs = _split_substructures(plain, 0)
    assert subs["G"] == plain[0:12]
    assert subs["A"] == plain[12:24]
    assert subs["E"] == plain[24:36]
    assert subs["M"] == plain[36:48]


def test_split_substructures_permuted():
    """Personality 6 → permutation 'AGEM' → A first, G second."""
    plain = bytes(range(48))
    subs = _split_substructures(plain, 6)
    # AGEM: A at 0, G at 12, E at 24, M at 36
    assert subs["A"] == plain[0:12]
    assert subs["G"] == plain[12:24]


def test_growth_roundtrip():
    raw = _build_growth(species=280, held=0, exp=2625, pp_bonuses=0, friendship=138)
    out = _parse_growth(raw)
    assert out["species"] == 280
    assert out["experience"] == 2625
    assert out["friendship"] == 138


def test_attacks_roundtrip():
    moves = [33, 52, 24, 45]   # Tackle, Ember, Double Kick, Growl
    pp = [35, 25, 30, 40]
    raw = _build_attacks(moves, pp)
    out = _parse_attacks(raw)
    assert out["moves"] == moves
    assert out["pp"] == pp


def test_evs_roundtrip():
    raw = _build_evs(hp=100, atk=20, df=20, spe=0, spa=0, spd=0)
    out = _parse_evs(raw)
    assert out["hp"] == 100
    assert out["atk"] == 20
    assert out["def"] == 20


def test_misc_roundtrip_all_ivs_perfect():
    ivs = {"hp": 31, "atk": 31, "def": 31, "spe": 31, "spa": 31, "spd": 31}
    raw = _build_misc(pokerus=0, met_loc=10, met_level=12, origin_game=3,
                      ball=4, ot_gender=0, ivs=ivs, is_egg=0,
                      ability_num=1, ribbons=0)
    out = _parse_misc(raw)
    assert out["ivs"] == ivs
    assert out["met_level"] == 12
    assert out["poke_ball"] == 4
    assert out["ability_num"] == 1


def test_full_party_slot_roundtrip():
    """Build all 4 substructures, XOR-encrypt, then run the full decode chain
    (decrypt_block + split_substructures + per-substruct parse) against it."""
    personality = 0x12345678  # nature 22 → Sassy, perm 0x78%24 = 0
    otid = 0xAABBCCDD
    key = personality ^ otid

    growth = _build_growth(280, 0, 2625, 0, 138)
    attacks = _build_attacks([33, 52, 24, 0], [35, 25, 30, 0])
    evs = _build_evs(100, 0, 0, 0, 0, 0)
    misc = _build_misc(0, 0, 5, 0, 4, 0,
                       {"hp": 31, "atk": 31, "def": 31, "spe": 31, "spa": 31, "spd": 31},
                       0, 0, 0)

    order = ["GAEM", "GAME", "GEAM", "GEMA", "GMAE", "GMEA",
             "AGEM", "AGME", "AEGM", "AEMG", "AMGE", "AMEG",
             "EGAM", "EGMA", "EAGM", "EAMG", "EMGA", "EMAG",
             "MGAE", "MGEA", "MAGE", "MAEG", "MEGA", "MEAG"]
    o = order[personality % 24]
    by_letter = {"G": growth, "A": attacks, "E": evs, "M": misc}
    plain = b"".join(by_letter[c] for c in o)
    enc = _xor_encrypt(plain, key)

    out_plain = _decrypt_block(enc, key)
    assert out_plain == plain
    subs = _split_substructures(out_plain, personality)
    assert _parse_growth(subs["G"])["species"] == 280
    assert _parse_attacks(subs["A"])["moves"] == [33, 52, 24, 0]
    assert _parse_evs(subs["E"])["hp"] == 100
    assert _parse_misc(subs["M"])["ivs"]["atk"] == 31


def test_decode_status_clean():
    assert _decode_status(0) is None


def test_decode_status_sleep():
    assert _decode_status(0x05) == "sleep (5T)"


def test_decode_status_poison():
    assert _decode_status(0x08) == "poison"


def test_decode_status_burn():
    assert _decode_status(0x10) == "burn"
