"""Scene-detection classifier (v0.11).

Three strategies tried in priority order at runtime:

1. Plugin override — a registered ``@p.scene_resolver`` (highest trust).
2. Memory-pattern vote — read K compiled addresses, majority vote.
3. pHash framebuffer template — 1-NN against per-scene dHash templates.

The compile step finds candidate gold addresses (memory) and computes
per-scene template hashes (pixels) from labelled captures with PNG
sidecars. The runtime classifier reads the addresses and frame each
tick.

See ``vault/Atlas/Architecture/2026-06-10-gbax-scene-detection-design.md``
for the design rationale; the empirical session at
``vault/+/agent_drafts/handoffs/report-2026-06-10-1254-gbax-scene-detection.md``
showed pHash alone fails on visually-unbounded scenes (overworld) and
memory voting at u32-LE width surfaces cross-session-consistent
fingerprints.
"""
from __future__ import annotations

import struct
from collections import Counter
from typing import Any


# --- constants --------------------------------------------------------

DEFAULT_K = 15
DEFAULT_VOTE_THRESHOLD = 0.5  # require ≥K * threshold matching votes
DEFAULT_PHASH_VARIANT = "dhash"
DEFAULT_PHASH_HASH_SIZE = 8

EWRAM_BASE = 0x02000000
IWRAM_BASE = 0x03000000


_WIDTHS = ("u8", "u16_le", "u32_le")


def _width_bytes(width: str) -> int:
    return {"u8": 1, "u16_le": 2, "u32_le": 4}[width]


def _decode(width: str, data: bytes) -> int:
    if width == "u8":
        return data[0]
    if width == "u16_le":
        return struct.unpack("<H", data)[0]
    if width == "u32_le":
        return struct.unpack("<I", data)[0]
    raise ValueError(f"unknown width: {width!r}")


# --- memory vote inference (compile-time) -----------------------------

def _decode_at(sparse, region: str, offset: int, width: str) -> int | None:
    """Decode `width` bytes at (region, offset) from a sparse capture, or None."""
    n = _width_bytes(width)
    bs = [sparse.get((region, offset + i)) for i in range(n)]
    if any(b is None for b in bs):
        return None
    if width == "u8":
        return bs[0]
    if width == "u16_le":
        return bs[0] | (bs[1] << 8)
    return bs[0] | (bs[1] << 8) | (bs[2] << 16) | (bs[3] << 24)


def _region_base(region: str) -> int:
    return EWRAM_BASE if region == "ewram" else IWRAM_BASE


def find_memory_addresses(
    captures: list[tuple[dict, str]],
    *,
    trap_filter: bool = True,
    k: int = DEFAULT_K,
) -> list[dict]:
    """Find top-K discriminating memory addresses across u8/u16/u32-LE widths.

    ``captures`` is a list of ``(sparse_dict, scene_label)`` tuples.

    Returns a list of dicts shaped like the ``compiled.json`` memory-vote
    schema: ``{"addr": "0x...", "width": "u32_le", "trap": False, "values": {scene: "0x..."}}``.

    Priority: non-trap u32-LE first (highest discrimination), then non-trap
    u16, u8; then trap variants in the same order if K isn't filled.
    """
    from gbax.state.capture import EWRAM_SIZE, IWRAM_SIZE

    # Group by scene
    scenes = sorted({lbl for _, lbl in captures})
    by_scene: dict[str, list[dict]] = {s: [] for s in scenes}
    for sparse, lbl in captures:
        if isinstance(lbl, str):
            by_scene[lbl].append(sparse)

    region_sizes = {"ewram": EWRAM_SIZE, "iwram": IWRAM_SIZE}

    non_trap: list[dict] = []
    trap: list[dict] = []

    for region, size in region_sizes.items():
        for width in ("u32_le", "u16_le", "u8"):
            n = _width_bytes(width)
            # For each offset find the value per scene
            for off in range(0, size - n + 1):
                values_per_scene: dict[str, int] = {}
                ok = True
                for s in scenes:
                    sample_values = []
                    for sparse in by_scene[s]:
                        v = _decode_at(sparse, region, off, width)
                        if v is None:
                            ok = False
                            break
                        sample_values.append(v)
                    if not ok:
                        break
                    # constant within scene?
                    if len(set(sample_values)) != 1:
                        ok = False
                        break
                    values_per_scene[s] = sample_values[0]
                if not ok:
                    continue
                # distinct across all scenes?
                if len(set(values_per_scene.values())) != len(scenes):
                    continue
                addr = _region_base(region) + off
                is_trap = trap_filter and any(v == 0 for v in values_per_scene.values())
                entry = {
                    "addr": hex(addr),
                    "width": width,
                    "trap": is_trap,
                    "values": {s: hex(v) for s, v in values_per_scene.items()},
                    "_priority": (
                        -("u32_le u16_le u8".split().index(width)),  # u32 best
                        -min(
                            abs(a - b) for a in values_per_scene.values()
                            for b in values_per_scene.values() if a != b
                        ),  # widest gap better
                    ),
                }
                (trap if is_trap else non_trap).append(entry)

    # Sort by priority (best first)
    non_trap.sort(key=lambda e: e["_priority"])
    trap.sort(key=lambda e: e["_priority"])
    selected = non_trap[:k]
    if len(selected) < k:
        selected.extend(trap[: k - len(selected)])
    for e in selected:
        e.pop("_priority", None)
    return selected


# --- pHash template inference (compile-time) --------------------------

def compute_phash_templates(
    samples: list[tuple[Any, str]],
    *,
    variant: str = DEFAULT_PHASH_VARIANT,
    hash_size: int = DEFAULT_PHASH_HASH_SIZE,
) -> dict:
    """Compute per-scene perceptual-hash templates from PIL Images.

    ``samples`` is a list of ``(pil_image, scene_label)`` tuples. Returns
    the schema dict for ``compiled.json`` (variant, hash_size, templates).
    """
    try:
        import imagehash
    except ImportError:
        return {}

    hash_fn = {
        "ahash": imagehash.average_hash,
        "dhash": imagehash.dhash,
        "phash": imagehash.phash,
    }.get(variant, imagehash.dhash)

    by_scene: dict[str, list] = {}
    for img, lbl in samples:
        by_scene.setdefault(lbl, []).append(hash_fn(img, hash_size=hash_size))

    templates = []
    for scene, hashes in by_scene.items():
        if not hashes:
            continue
        # within-scene max Hamming to set threshold
        max_within = 0
        for i in range(len(hashes)):
            for j in range(i + 1, len(hashes)):
                d = hashes[i] - hashes[j]
                if d > max_within:
                    max_within = d
        for h in hashes:
            templates.append({
                "scene": scene,
                "hash": str(h),  # imagehash.ImageHash → hex string via __str__
                "within_scene_max": max_within,
            })

    return {
        "variant": variant,
        "hash_size": hash_size,
        "templates": templates,
    }


# --- runtime classifier -----------------------------------------------


class SceneClassifier:
    """Three-strategy scene classifier wired around an EmulatorRuntime."""

    def __init__(
        self,
        spec: dict,
        runtime,
        *,
        plugin_resolvers: list | None = None,
    ) -> None:
        self._runtime = runtime
        self._memory_vote = spec.get("memory_vote") or {}
        self._phash = spec.get("phash_templates") or {}
        self._plugin_resolvers = list(plugin_resolvers or [])
        self._k_required_default = self._memory_vote.get(
            "k_required",
            max(1, int(len(self._memory_vote.get("addresses", [])) * DEFAULT_VOTE_THRESHOLD)),
        )

    def classify(self) -> str | None:
        """Return current scene name, or None if undetermined."""
        # Strategy 1: plugin override
        for resolver in self._plugin_resolvers:
            try:
                result = resolver(self._runtime)
            except Exception:
                import traceback
                traceback.print_exc()
                continue
            if result is not None:
                return result

        # Strategy 2: memory vote
        vote_result = self._memory_vote_classify()
        if vote_result is not None:
            return vote_result

        # Strategy 3: pHash fallback
        return self._phash_classify()

    def _memory_vote_classify(self) -> str | None:
        addresses = self._memory_vote.get("addresses", [])
        if not addresses:
            return None
        votes: Counter[str] = Counter()
        for entry in addresses:
            addr = int(entry["addr"], 16)
            width = entry["width"]
            data = self._runtime.read_memory(addr, _width_bytes(width))
            v = _decode(width, data)
            for scene, expected_hex in entry.get("values", {}).items():
                if int(expected_hex, 16) == v:
                    votes[scene] += 1
                    break
        if not votes:
            return None
        top_scene, top_count = votes.most_common(1)[0]
        if top_count >= self._k_required_default:
            return top_scene
        return None

    def _phash_classify(self) -> str | None:
        templates = self._phash.get("templates") or []
        if not templates:
            return None
        try:
            import imagehash
            from PIL import Image
        except ImportError:
            return None
        fb = self._runtime.framebuffer()
        img = Image.fromarray(fb)
        variant = self._phash.get("variant", DEFAULT_PHASH_VARIANT)
        hash_size = self._phash.get("hash_size", DEFAULT_PHASH_HASH_SIZE)
        hash_fn = {
            "ahash": imagehash.average_hash,
            "dhash": imagehash.dhash,
            "phash": imagehash.phash,
        }.get(variant, imagehash.dhash)
        live_h = hash_fn(img, hash_size=hash_size)
        best_scene = None
        best_distance = None
        best_within = None
        for t in templates:
            stored = imagehash.hex_to_hash(t["hash"])
            d = live_h - stored
            if best_distance is None or d < best_distance:
                best_distance = d
                best_scene = t["scene"]
                best_within = t.get("within_scene_max", 0)
        if best_distance is None:
            return None
        # threshold: 1.5x the template's within-scene max
        threshold = max(8, int((best_within or 0) * 1.5))
        if best_distance <= threshold:
            return best_scene
        return None
