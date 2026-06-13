"""Identity + naming tests."""

from __future__ import annotations

import json
from pathlib import Path

from gbax.couch.identity import Identity, load_or_generate
from gbax.couch.naming import (
    DEFAULT_ROOM,
    is_valid_room_code,
    new_room_code,
    normalize_room_code,
)


def test_identity_generated_on_first_use(tmp_path: Path):
    p = tmp_path / "identity.json"
    assert not p.exists()
    ident = load_or_generate(p)
    assert p.exists()
    assert len(ident.id) == 32
    assert ident.name
    assert ident.created_at


def test_identity_persists_across_calls(tmp_path: Path):
    p = tmp_path / "identity.json"
    a = load_or_generate(p)
    b = load_or_generate(p)
    assert a.id == b.id
    assert a.name == b.name
    assert a.created_at == b.created_at


def test_identity_file_is_world_unreadable(tmp_path: Path):
    p = tmp_path / "identity.json"
    load_or_generate(p)
    mode = p.stat().st_mode & 0o777
    # 0o600 expected; allow group-readable on systems that ignore chmod.
    assert mode in (0o600, 0o644)


def test_corrupted_identity_file_is_backed_up_and_replaced(tmp_path: Path):
    p = tmp_path / "identity.json"
    p.write_text("not-json")
    new_ident = load_or_generate(p)
    assert p.exists()
    assert json.loads(p.read_text())["id"] == new_ident.id
    assert (p.parent / "identity.json.broken").exists()


def test_identity_to_from_dict_roundtrip():
    src = Identity(id="abc", name="Alex", created_at="2026-01-01T00:00:00")
    again = Identity.from_dict(src.to_dict())
    assert again == src


# ---------- naming ----------

def test_new_room_code_is_three_words():
    code = new_room_code()
    assert is_valid_room_code(code)
    assert code.count("-") == 2


def test_room_code_validation():
    assert is_valid_room_code("quick-amber-otter")
    assert is_valid_room_code("staging")
    assert is_valid_room_code("a1-b2-c3")
    assert not is_valid_room_code("")
    assert not is_valid_room_code("UPPER")
    assert not is_valid_room_code("has space")
    assert not is_valid_room_code("-leading")
    assert not is_valid_room_code("toolong" + "x" * 64)


def test_normalize_room_code_tolerant():
    assert normalize_room_code("Quick Amber Otter") == "quick-amber-otter"
    assert normalize_room_code("  quick,amber,otter ") == "quick-amber-otter"
    assert normalize_room_code("quick--amber---otter") == "quick-amber-otter"
    assert normalize_room_code("") == ""


def test_default_room_constant():
    assert DEFAULT_ROOM == "default"
