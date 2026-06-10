"""Tests for gbax.state.watch — StateReader pulls live values from a runtime."""
from __future__ import annotations

import json
from pathlib import Path

from gbax.state.watch import StateReader


def _write_compiled(tmp_path: Path, payload):
    p = tmp_path / "compiled.json"
    p.write_text(json.dumps(payload))
    return p


class _FakeRuntime:
    def __init__(self, memory: dict[int, int]):
        self._m = memory

    def read_memory(self, addr: int, length: int) -> bytes:
        return bytes(self._m.get(addr + i, 0) for i in range(length))


def test_reader_reads_numeric_u8(tmp_path):
    p = _write_compiled(tmp_path, {
        "tags": {"hp": {"kind": "numeric", "addr": "0x02024382", "width": "u8"}}
    })
    rt = _FakeRuntime({0x02024382: 45})
    reader = StateReader(p, rt)
    assert reader.read_all() == {"hp": 45}


def test_reader_reads_numeric_u16_le(tmp_path):
    p = _write_compiled(tmp_path, {
        "tags": {"money": {"kind": "numeric", "addr": "0x02025e34", "width": "u16_le"}}
    })
    rt = _FakeRuntime({0x02025e34: 0x84, 0x02025e35: 0x30})
    reader = StateReader(p, rt)
    assert reader.read_all() == {"money": 12420}


def test_reader_reads_categorical(tmp_path):
    p = _write_compiled(tmp_path, {
        "tags": {
            "scene": {
                "kind": "categorical",
                "addr": "0x03000fa4",
                "width": "u8",
                "values": {"0x12": "fight-menu", "0x34": "overworld"},
            }
        }
    })
    rt = _FakeRuntime({0x03000fa4: 0x12})
    reader = StateReader(p, rt)
    assert reader.read_all() == {"scene": "fight-menu"}


def test_reader_unknown_categorical_value(tmp_path):
    p = _write_compiled(tmp_path, {
        "tags": {
            "scene": {
                "kind": "categorical",
                "addr": "0x03000fa4",
                "width": "u8",
                "values": {"0x12": "fight-menu"},
            }
        }
    })
    rt = _FakeRuntime({0x03000fa4: 0x99})
    reader = StateReader(p, rt)
    assert reader.read_all() == {"scene": "?"}


def test_reader_missing_compiled_is_empty(tmp_path):
    rt = _FakeRuntime({})
    reader = StateReader(tmp_path / "nope.json", rt)
    assert reader.read_all() == {}
