"""Sparse-filtered GBA memory capture for the state tracker.

A capture is a 30-frame stability filter over EWRAM (`0x02000000`,
256 KB) and IWRAM (`0x03000000`, 32 KB). Only bytes whose value is
constant across every frame in the window are kept; volatile bytes
(frame counter, RNG, animation tweens) are dropped at capture time.
The resulting sparse dict is written to disk alongside the user's
labels for later supervised inference.
"""
from __future__ import annotations

import gzip
import json
import pickle
from datetime import datetime
from pathlib import Path

from gbax.state.storage import captures_dir_for_rom


EWRAM_BASE = 0x02000000
EWRAM_SIZE = 0x40000  # 256 KB
IWRAM_BASE = 0x03000000
IWRAM_SIZE = 0x8000   # 32 KB

SparseBytes = dict[tuple[str, int], int]


def sparse_capture(runtime, n_frames: int = 30) -> SparseBytes:
    """Run the runtime for `n_frames` and return the bytes that stayed constant."""
    frames: list[dict[str, bytes]] = []
    for i in range(n_frames):
        if i > 0:
            runtime.step(1)
        frames.append({
            "ewram": runtime.read_memory(EWRAM_BASE, EWRAM_SIZE),
            "iwram": runtime.read_memory(IWRAM_BASE, IWRAM_SIZE),
        })
    out: SparseBytes = {}
    for region, size in (("ewram", EWRAM_SIZE), ("iwram", IWRAM_SIZE)):
        first = frames[0][region]
        if n_frames == 1:
            for i, b in enumerate(first):
                out[(region, i)] = b
            continue
        for i, b0 in enumerate(first):
            if all(frames[f][region][i] == b0 for f in range(1, n_frames)):
                out[(region, i)] = b0
    return out


def _capture_dump_path(rom_sha1: str, ts: datetime, *, root: Path | None) -> Path:
    return captures_dir_for_rom(rom_sha1, root=root) / f"{ts.strftime('%Y-%m-%dT%H-%M-%S')}.dump"


def save_capture(
    rom_sha1: str,
    sparse: SparseBytes,
    labels: dict[str, int | str],
    ts: datetime,
    *,
    root: Path | None = None,
) -> Path:
    """Persist a sparse capture + labels alongside it. Returns the dump path."""
    dump_path = _capture_dump_path(rom_sha1, ts, root=root)
    dump_path.parent.mkdir(parents=True, exist_ok=True)
    payload = {
        "rom_sha1": rom_sha1,
        "captured_at": ts.isoformat(),
        "bytes": sparse,
    }
    with gzip.open(dump_path, "wb") as f:
        pickle.dump(payload, f, protocol=4)
    labels_path = dump_path.with_suffix(".labels.json")
    labels_path.write_text(json.dumps(labels, indent=2, sort_keys=True))
    return dump_path


def load_capture(dump_path: Path) -> tuple[SparseBytes, dict[str, int | str], datetime]:
    """Load a sparse capture + sidecar labels. Returns (sparse, labels, ts)."""
    with gzip.open(dump_path, "rb") as f:
        payload = pickle.load(f)
    labels_path = dump_path.with_suffix(".labels.json")
    labels = json.loads(labels_path.read_text()) if labels_path.exists() else {}
    ts = datetime.fromisoformat(payload["captured_at"])
    return payload["bytes"], labels, ts
