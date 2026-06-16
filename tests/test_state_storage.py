"""Tests for retrokix.state.storage — label parser and path helpers."""
from __future__ import annotations

import pytest

from retrokix.state.storage import (
    captures_dir_for_rom,
    compiled_path_for_rom,
    parse_labels,
)


SHA1 = "f3ae088181bf583e55daf962a92bb46f4f1d07b7"


def test_parse_labels_integer_and_string():
    labels = parse_labels("hp=45, scene=fight-menu, money=12420")
    assert labels == {"hp": 45, "scene": "fight-menu", "money": 12420}


def test_parse_labels_trims_whitespace():
    assert parse_labels("  a = 1  ,  b = foo  ") == {"a": 1, "b": "foo"}


def test_parse_labels_empty_string():
    assert parse_labels("") == {}
    assert parse_labels("   ") == {}


def test_parse_labels_ignores_blank_pairs():
    assert parse_labels("a=1,,b=2") == {"a": 1, "b": 2}


def test_parse_labels_rejects_missing_equals():
    with pytest.raises(ValueError, match="missing '='"):
        parse_labels("a=1, justakey")


def test_parse_labels_negative_int():
    assert parse_labels("delta=-3") == {"delta": -3}


def test_captures_dir_for_rom(tmp_path):
    out = captures_dir_for_rom(SHA1, root=tmp_path)
    assert out == tmp_path / SHA1 / "captures"


def test_compiled_path_for_rom(tmp_path):
    out = compiled_path_for_rom(SHA1, root=tmp_path)
    assert out == tmp_path / SHA1 / "compiled.json"
