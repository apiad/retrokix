"""Tests for the gen-3 charmap name decoder."""
from __future__ import annotations

from retrokix.plugins.pokemon.shared.text import decode_name


def test_decode_uppercase_name():
    # BB C6 BF D2 = A L E X, then 0xFF terminator
    assert decode_name(bytes([0xBB, 0xC6, 0xBF, 0xD2, 0xFF, 0xFF, 0xFF, 0xFF])) == "ALEX"


def test_decode_stops_at_terminator():
    assert decode_name(bytes([0xBB, 0xFF, 0xBB])) == "A"


def test_decode_digits_and_space():
    # 0xA1='0', 0x00=space
    assert decode_name(bytes([0xBB, 0x00, 0xA1, 0xFF])) == "A 0"


def test_decode_lowercase():
    # 0xD5='a'
    assert decode_name(bytes([0xD5, 0xFF])) == "a"


def test_decode_empty():
    assert decode_name(bytes([0xFF, 0xFF])) == ""
