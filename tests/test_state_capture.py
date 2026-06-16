"""Tests for retrokix.state.capture — sparse memory snapshot + persistence."""
from __future__ import annotations

import json
from datetime import datetime, timezone

from retrokix.state.capture import (
    EWRAM_BASE,
    EWRAM_SIZE,
    IWRAM_BASE,
    IWRAM_SIZE,
    load_capture,
    save_capture,
    sparse_capture,
)


SHA1 = "f3ae088181bf583e55daf962a92bb46f4f1d07b7"


class _FakeRuntime:
    """Returns deterministic memory; some bytes flip between frames."""

    def __init__(self, ewram: bytes, iwram: bytes, volatile_offsets: dict):
        self._ewram = bytearray(ewram)
        self._iwram = bytearray(iwram)
        self._volatile = volatile_offsets
        self._frame = 0

    def step(self, frames: int = 1) -> None:
        for _ in range(frames):
            self._frame += 1
            for (region, offset), seq in self._volatile.items():
                target = self._ewram if region == "ewram" else self._iwram
                target[offset] = seq[self._frame % len(seq)]

    def read_memory(self, addr: int, length: int) -> bytes:
        if addr == EWRAM_BASE:
            return bytes(self._ewram[:length])
        if addr == IWRAM_BASE:
            return bytes(self._iwram[:length])
        raise AssertionError(f"unexpected read {addr:#x}+{length}")


def _make_runtime(*, volatile_offsets=None):
    ewram = bytes(i & 0xFF for i in range(EWRAM_SIZE))
    iwram = bytes((i * 3) & 0xFF for i in range(IWRAM_SIZE))
    return _FakeRuntime(ewram, iwram, volatile_offsets or {})


def test_sparse_capture_stable_bytes_only():
    rt = _make_runtime(volatile_offsets={
        ("ewram", 0x1000): bytes([1, 2, 3, 4, 5]),
        ("iwram", 0x100): bytes([10, 20]),
    })
    sparse = sparse_capture(rt, n_frames=10)
    assert ("ewram", 0x1000) not in sparse
    assert ("iwram", 0x100) not in sparse
    assert sparse[("ewram", 0x2000)] == 0x2000 & 0xFF


def test_sparse_capture_one_frame_keeps_everything():
    rt = _make_runtime()
    sparse = sparse_capture(rt, n_frames=1)
    assert len(sparse) == EWRAM_SIZE + IWRAM_SIZE
    assert sparse[("ewram", 0)] == 0
    assert sparse[("iwram", 0)] == 0


def test_save_and_load_capture_round_trip(tmp_path):
    rt = _make_runtime()
    sparse = sparse_capture(rt, n_frames=5)
    labels = {"scene": "fight-menu", "hp": 45}
    ts = datetime(2026, 6, 10, 1, 14, 22, tzinfo=timezone.utc)
    path = save_capture(SHA1, sparse, labels, ts, root=tmp_path)
    assert path.exists()
    sparse2, labels2, ts2 = load_capture(path)
    assert sparse2 == sparse
    assert labels2 == labels
    assert ts2 == ts


def test_save_capture_writes_labels_sidecar(tmp_path):
    rt = _make_runtime()
    sparse = sparse_capture(rt, n_frames=2)
    labels = {"scene": "overworld"}
    ts = datetime(2026, 6, 10, 1, 15, 44, tzinfo=timezone.utc)
    dump_path = save_capture(SHA1, sparse, labels, ts, root=tmp_path)
    labels_path = dump_path.with_suffix(".labels.json")
    assert labels_path.exists()
    assert json.loads(labels_path.read_text()) == labels
