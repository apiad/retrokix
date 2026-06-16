"""Supervised address inference from labeled captures.

For each tag the user labeled across multiple captures:

  * Numeric labels (integer values): search EWRAM+IWRAM at common widths
    (u8, u16-LE, u32-LE) for byte sequences whose decoded value matches
    the label in every snapshot where the tag appears.
  * Categorical labels (non-integer strings): find addresses where the
    byte is constant per label group AND different across groups.

Survivors are written to ``compiled.json``. Tags with multiple
surviving addresses are listed under ``ambiguous`` so the user can add
captures to disambiguate.
"""
from __future__ import annotations

import json
import struct
from collections import defaultdict
from pathlib import Path

from retrokix.state.capture import (
    EWRAM_BASE,
    EWRAM_SIZE,
    IWRAM_BASE,
    IWRAM_SIZE,
    SparseBytes,
    load_capture,
)
from retrokix.state.storage import captures_dir_for_rom, compiled_path_for_rom


_REGION_BASE = {"ewram": EWRAM_BASE, "iwram": IWRAM_BASE}
_REGION_SIZE = {"ewram": EWRAM_SIZE, "iwram": IWRAM_SIZE}


def _abs_addr(region: str, offset: int) -> int:
    return _REGION_BASE[region] + offset


def _read_u8(sparse: SparseBytes, region: str, offset: int) -> int | None:
    return sparse.get((region, offset))


def _read_u16_le(sparse: SparseBytes, region: str, offset: int) -> int | None:
    lo = sparse.get((region, offset))
    hi = sparse.get((region, offset + 1))
    if lo is None or hi is None:
        return None
    return lo | (hi << 8)


def _read_u32_le(sparse: SparseBytes, region: str, offset: int) -> int | None:
    bs = [sparse.get((region, offset + i)) for i in range(4)]
    if any(b is None for b in bs):
        return None
    return struct.unpack("<I", bytes(bs))[0]


_READERS = {"u8": _read_u8, "u16_le": _read_u16_le, "u32_le": _read_u32_le}


def _load_all_captures(rom_sha1: str, root: Path | None):
    cap_dir = captures_dir_for_rom(rom_sha1, root=root)
    out = []
    if not cap_dir.exists():
        return out
    for dump_path in sorted(cap_dir.glob("*.dump")):
        sparse, labels, ts = load_capture(dump_path)
        out.append((sparse, labels, ts))
    return out


def _candidate_addrs(captures, tag: str, value: int, width: str) -> set[tuple[str, int]]:
    """Offsets where read(addr, width) == value in every capture that labels `tag`=value."""
    relevant = [(s, lbls[tag]) for s, lbls, _ in captures if tag in lbls and lbls[tag] == value]
    if not relevant:
        return set()
    survivors: set[tuple[str, int]] | None = None
    for sparse, _ in relevant:
        matches: set[tuple[str, int]] = set()
        for region, size in (("ewram", EWRAM_SIZE), ("iwram", IWRAM_SIZE)):
            for offset in range(size):
                v = _READERS[width](sparse, region, offset)
                if v is not None and v == value:
                    matches.add((region, offset))
        survivors = matches if survivors is None else survivors & matches
    return survivors or set()


def _infer_numeric(captures, tag: str):
    """Return (primary, ambiguous) lists of (region, width, offset)."""
    label_values = {
        lbls[tag] for _, lbls, _ in captures
        if tag in lbls and isinstance(lbls[tag], int)
    }
    if not label_values:
        return [], []
    intersected_by_width: dict[str, set[tuple[str, int]]] = {}
    for width in ("u8", "u16_le", "u32_le"):
        survivors: set[tuple[str, int]] | None = None
        for value in label_values:
            cands = _candidate_addrs(captures, tag, value, width)
            survivors = cands if survivors is None else survivors & cands
        if survivors:
            intersected_by_width[width] = survivors
    if not intersected_by_width:
        return [], []
    primary: list[tuple[str, str, int]] = []
    ambiguous: list[tuple[str, str, int]] = []
    for width in ("u8", "u16_le", "u32_le"):
        if width not in intersected_by_width:
            continue
        survivors = sorted(intersected_by_width[width], key=lambda x: (x[0], x[1]))
        for region, offset in survivors:
            if not primary:
                primary.append((region, width, offset))
            else:
                ambiguous.append((region, width, offset))
    return primary, ambiguous


def _infer_categorical(captures, tag: str):
    """Return (primary, ambiguous) lists of (region, offset, {byte_value: label})."""
    groups: dict[str, list[SparseBytes]] = defaultdict(list)
    for sparse, lbls, _ in captures:
        if tag in lbls and isinstance(lbls[tag], str):
            groups[lbls[tag]].append(sparse)
    if len(groups) < 2:
        return [], []
    survivors: list[tuple[str, int, dict[int, str]]] = []
    for region, size in (("ewram", EWRAM_SIZE), ("iwram", IWRAM_SIZE)):
        for offset in range(size):
            group_values: dict[str, int] = {}
            ok = True
            for label, sparses in groups.items():
                vs = [s.get((region, offset)) for s in sparses]
                if any(v is None for v in vs):
                    ok = False
                    break
                if len(set(vs)) != 1:
                    ok = False
                    break
                group_values[label] = vs[0]
            if not ok:
                continue
            if len(set(group_values.values())) < 2:
                continue
            lookup = {v: lbl for lbl, v in group_values.items()}
            survivors.append((region, offset, lookup))
    if not survivors:
        return [], []
    survivors.sort(key=lambda x: (x[0], x[1]))
    return [survivors[0]], survivors[1:]


def compile_for_rom(rom_sha1: str, *, root: Path | None = None) -> Path:
    """Run inference over all captures for `rom_sha1` and write compiled.json."""
    captures = _load_all_captures(rom_sha1, root)
    all_tags: set[str] = set()
    for _, labels, _ in captures:
        all_tags.update(labels.keys())

    tags_out: dict[str, dict] = {}
    ambiguous_out: dict[str, list[dict]] = {}

    for tag in sorted(all_tags):
        label_kinds = {type(lbls[tag]).__name__ for _, lbls, _ in captures if tag in lbls}
        if "int" in label_kinds:
            primary, ambig = _infer_numeric(captures, tag)
            if primary:
                region, width, offset = primary[0]
                tags_out[tag] = {
                    "kind": "numeric",
                    "addr": hex(_abs_addr(region, offset)),
                    "width": width,
                    "confidence": 1.0,
                }
            if ambig:
                ambiguous_out[tag] = [
                    {"addr": hex(_abs_addr(r, o)), "width": w}
                    for r, w, o in ambig
                ]
        else:
            # String-labelled tag — try scene-detection first (multi-modal:
            # memory vote across u8/u16/u32-LE + pHash framebuffer templates),
            # falling back to the v0.10 single-byte categorical algorithm if
            # scene strategies don't produce enough discrimination.
            from retrokix.state.scene import find_memory_addresses, compute_phash_templates
            from retrokix.state.capture import png_path_for_capture

            scene_captures = [
                (sparse, lbls[tag]) for sparse, lbls, _ in captures
                if tag in lbls and isinstance(lbls[tag], str)
            ]
            scene_values = {lbl for _, lbl in scene_captures}
            if len(scene_values) >= 2:
                memory_addrs = find_memory_addresses(scene_captures)
                cap_dir = captures_dir_for_rom(rom_sha1, root=root)
                samples = []
                if cap_dir.exists():
                    try:
                        from PIL import Image
                        for dump in sorted(cap_dir.glob("*.dump")):
                            png = png_path_for_capture(dump)
                            if png is None:
                                continue
                            ts_part = dump.stem
                            # find matching label
                            for sparse, lbls, c_ts in captures:
                                if c_ts.strftime("%Y-%m-%dT%H-%M-%S") == ts_part and tag in lbls and isinstance(lbls[tag], str):
                                    samples.append((Image.open(png).convert("RGB"), lbls[tag]))
                                    break
                    except ImportError:
                        samples = []
                phash_block = compute_phash_templates(samples) if samples else {}

                if memory_addrs or phash_block.get("templates"):
                    tags_out[tag] = {
                        "kind": "scene",
                        "memory_vote": {
                            "addresses": memory_addrs,
                            "k_required": max(1, len(memory_addrs) // 2),
                        },
                        "phash_templates": phash_block,
                    }
                    continue

            # Fall back to v0.10 categorical for single-byte sub-states.
            primary, ambig = _infer_categorical(captures, tag)
            if primary:
                region, offset, lookup = primary[0]
                tags_out[tag] = {
                    "kind": "categorical",
                    "addr": hex(_abs_addr(region, offset)),
                    "width": "u8",
                    "values": {hex(k): v for k, v in lookup.items()},
                    "confidence": 1.0,
                }
            if ambig:
                ambiguous_out[tag] = [
                    {"addr": hex(_abs_addr(r, o)), "width": "u8"}
                    for r, o, _ in ambig
                ]

    out_path = compiled_path_for_rom(rom_sha1, root=root)
    out_path.parent.mkdir(parents=True, exist_ok=True)
    payload = {
        "version": 2,
        "rom_sha1": rom_sha1,
        "captures_used": len(captures),
        "tags": tags_out,
        "ambiguous": ambiguous_out,
    }
    out_path.write_text(json.dumps(payload, indent=2, sort_keys=True))
    return out_path
