"""Tests for the v0.11 scene-detection classifier."""
from __future__ import annotations

from retrokix.state.scene import (
    SceneClassifier,
    compute_phash_templates,
    find_memory_addresses,
)


def _sparse(*pairs):
    """Build a sparse dict from (offset, byte_value) pairs at EWRAM."""
    return {("ewram", off): v for off, v in pairs}


def test_find_memory_addresses_u8_discrimination():
    captures = [
        (_sparse((0x100, 0x11), (0x200, 0xff)), "overworld"),
        (_sparse((0x100, 0x11), (0x200, 0xff)), "overworld"),
        (_sparse((0x100, 0x22), (0x200, 0xff)), "battle"),
        (_sparse((0x100, 0x22), (0x200, 0xff)), "battle"),
    ]
    addrs = find_memory_addresses(captures, trap_filter=False)
    addrs_at_100 = [a for a in addrs if int(a["addr"], 16) == 0x02000100]
    assert addrs_at_100, "should find 0x02000100 as discriminating"
    a = addrs_at_100[0]
    assert a["values"]["overworld"] == "0x11"
    assert a["values"]["battle"] == "0x22"


def test_find_memory_addresses_u32_le_discrimination():
    captures = [
        (_sparse((0x100, 0x00), (0x101, 0x01), (0x102, 0x00), (0x103, 0x00)), "overworld"),
        (_sparse((0x100, 0x00), (0x101, 0x08), (0x102, 0x00), (0x103, 0x00)), "battle"),
    ]
    addrs = find_memory_addresses(captures, trap_filter=False)
    u32s = [a for a in addrs if a["width"] == "u32_le" and int(a["addr"], 16) == 0x02000100]
    assert u32s, "u32-LE at 0x02000100 should be a candidate"
    assert u32s[0]["values"]["overworld"] == "0x100"
    assert u32s[0]["values"]["battle"] == "0x800"


def test_find_memory_addresses_trap_filter():
    """Addresses where any scene reads 0x00 are tagged as traps."""
    captures = [
        (_sparse((0x100, 0x00), (0x200, 0xff)), "overworld"),
        (_sparse((0x100, 0x42), (0x200, 0xff)), "battle"),
    ]
    with_filter = find_memory_addresses(captures, trap_filter=True)
    addr_0x100 = [a for a in with_filter if int(a["addr"], 16) == 0x02000100]
    assert addr_0x100
    assert any(a["trap"] for a in addr_0x100)


def test_scene_classifier_memory_vote():
    spec = {
        "memory_vote": {
            "addresses": [
                {"addr": "0x02000100", "width": "u8", "trap": False,
                 "values": {"overworld": "0x11", "battle": "0x22"}},
                {"addr": "0x02000200", "width": "u8", "trap": False,
                 "values": {"overworld": "0x33", "battle": "0x44"}},
            ],
            "k_required": 1,
        },
    }

    class FakeRuntime:
        def __init__(self, mem):
            self._mem = mem
        def read_memory(self, addr, length):
            return bytes(self._mem.get(addr + i, 0) for i in range(length))

    rt = FakeRuntime({0x02000100: 0x11, 0x02000200: 0x33})
    assert SceneClassifier(spec, rt).classify() == "overworld"

    rt = FakeRuntime({0x02000100: 0x22, 0x02000200: 0x44})
    assert SceneClassifier(spec, rt).classify() == "battle"


def test_scene_classifier_plugin_resolver_priority():
    spec = {"memory_vote": {"addresses": []}}

    class FakeRuntime:
        def read_memory(self, addr, length):
            return b"\x00" * length

    def resolver(rt):
        return "from-plugin"

    c = SceneClassifier(spec, FakeRuntime(), plugin_resolvers=[resolver])
    assert c.classify() == "from-plugin"


def test_scene_classifier_plugin_resolver_returns_none_falls_through():
    spec = {
        "memory_vote": {
            "addresses": [
                {"addr": "0x02000100", "width": "u8", "trap": False,
                 "values": {"overworld": "0x11", "battle": "0x22"}},
            ],
            "k_required": 1,
        },
    }

    class FakeRuntime:
        def read_memory(self, addr, length):
            return bytes([0x11] * length)

    def resolver(rt):
        return None

    c = SceneClassifier(spec, FakeRuntime(), plugin_resolvers=[resolver])
    assert c.classify() == "overworld"


def test_scene_classifier_empty_returns_none():
    class FakeRuntime:
        def read_memory(self, addr, length):
            return b"\x00" * length

    assert SceneClassifier({}, FakeRuntime()).classify() is None


def test_compute_phash_templates_basic():
    try:
        import imagehash  # noqa: F401
        import numpy as np
        from PIL import Image
    except ImportError:
        return

    rng = np.random.default_rng(42)
    scene_a = [Image.fromarray((rng.uniform(0, 100, (64, 64, 3))).astype(np.uint8))
               for _ in range(3)]
    scene_b = [Image.fromarray((rng.uniform(155, 255, (64, 64, 3))).astype(np.uint8))
               for _ in range(3)]
    samples = [(im, "dark") for im in scene_a] + [(im, "light") for im in scene_b]
    block = compute_phash_templates(samples, variant="dhash", hash_size=8)
    assert block["variant"] == "dhash"
    assert block["hash_size"] == 8
    assert len({t["scene"] for t in block["templates"]}) == 2
