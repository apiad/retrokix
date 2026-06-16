"""Tests for retrokix.state.compile — inference from labeled captures."""
from __future__ import annotations

import json
from datetime import datetime, timezone

from retrokix.state.capture import EWRAM_BASE, save_capture
from retrokix.state.compile import compile_for_rom
from retrokix.state.storage import compiled_path_for_rom


SHA1 = "abc"


def _save(tmp_path, sparse, labels, suffix):
    ts = datetime(2026, 6, 10, 1, 0, int(suffix), tzinfo=timezone.utc)
    save_capture(SHA1, sparse, labels, ts, root=tmp_path)


def test_numeric_u8_value_match(tmp_path):
    _save(tmp_path,
          {("ewram", 0x100): 45, ("ewram", 0x200): 99},
          {"hp": 45},
          "1")
    _save(tmp_path,
          {("ewram", 0x100): 23, ("ewram", 0x200): 99},
          {"hp": 23},
          "2")
    out_path = compile_for_rom(SHA1, root=tmp_path)
    assert out_path == compiled_path_for_rom(SHA1, root=tmp_path)
    payload = json.loads(out_path.read_text())
    hp = payload["tags"]["hp"]
    assert hp["kind"] == "numeric"
    assert hp["width"] == "u8"
    assert int(hp["addr"], 16) == EWRAM_BASE + 0x100


def test_numeric_u16_le_value_match(tmp_path):
    _save(tmp_path,
          {("ewram", 0x300): 0x84, ("ewram", 0x301): 0x30},
          {"money": 12420},
          "1")
    _save(tmp_path,
          {("ewram", 0x300): 0xa0, ("ewram", 0x301): 0x86},
          {"money": 34464},
          "2")
    out_path = compile_for_rom(SHA1, root=tmp_path)
    payload = json.loads(out_path.read_text())
    money = payload["tags"]["money"]
    assert money["kind"] == "numeric"
    assert money["width"] == "u16_le"
    assert int(money["addr"], 16) == EWRAM_BASE + 0x300


def test_scene_kind_from_string_labels(tmp_path):
    """String labels now infer as the multi-modal scene kind (v0.11).

    The memory-vote block picks up the discriminating byte at 0x500;
    no PNG sidecars means the phash_templates block is empty.
    """
    _save(tmp_path,
          {("ewram", 0x500): 0x12, ("ewram", 0x600): 0xff},
          {"scene": "fight-menu"},
          "1")
    _save(tmp_path,
          {("ewram", 0x500): 0x12, ("ewram", 0x600): 0xff},
          {"scene": "fight-menu"},
          "2")
    _save(tmp_path,
          {("ewram", 0x500): 0x34, ("ewram", 0x600): 0xff},
          {"scene": "overworld"},
          "3")
    out_path = compile_for_rom(SHA1, root=tmp_path)
    payload = json.loads(out_path.read_text())
    scene = payload["tags"]["scene"]
    assert scene["kind"] == "scene"
    # memory_vote block holds the discriminating addresses
    addrs = scene["memory_vote"]["addresses"]
    assert len(addrs) >= 1
    # 0x02000500 should be in there with the right per-scene values
    matched = [a for a in addrs if int(a["addr"], 16) == EWRAM_BASE + 0x500]
    assert matched, f"expected 0x{EWRAM_BASE + 0x500:x} in addresses; got {addrs}"
    a = matched[0]
    assert a["width"] == "u8"
    assert a["values"]["fight-menu"] == "0x12"
    assert a["values"]["overworld"] == "0x34"


def test_ambiguity_reported(tmp_path):
    _save(tmp_path,
          {("ewram", 0x100): 45, ("ewram", 0x800): 45},
          {"hp": 45},
          "1")
    _save(tmp_path,
          {("ewram", 0x100): 23, ("ewram", 0x800): 23},
          {"hp": 23},
          "2")
    out_path = compile_for_rom(SHA1, root=tmp_path)
    payload = json.loads(out_path.read_text())
    assert int(payload["tags"]["hp"]["addr"], 16) == EWRAM_BASE + 0x100
    ambig = payload.get("ambiguous", {}).get("hp", [])
    assert any(int(c["addr"], 16) == EWRAM_BASE + 0x800 for c in ambig)


def test_unmatched_tag_omitted(tmp_path):
    _save(tmp_path,
          {("ewram", 0x100): 0xaa},
          {"score": 999},
          "1")
    out_path = compile_for_rom(SHA1, root=tmp_path)
    payload = json.loads(out_path.read_text())
    assert "score" not in payload["tags"]
