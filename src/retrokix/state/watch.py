"""Live state readout for the Rich panel.

`StateReader` loads a compiled-state JSON and exposes `read_all()` which
returns a dict mapping each tag to its current value. Values are read
from the emulator runtime via `read_memory` (numeric / categorical) or
through the v0.11 `SceneClassifier` (scene tags).

The Rich panel itself is plumbed into the SDL play loop — it calls
`StateReader.read_all()` on a timer and re-renders a `Table`.
"""
from __future__ import annotations

import json
import struct
from pathlib import Path


_WIDTH_TO_BYTES = {"u8": 1, "u16_le": 2, "u32_le": 4}


def _decode(width: str, data: bytes) -> int:
    if width == "u8":
        return data[0]
    if width == "u16_le":
        return struct.unpack("<H", data)[0]
    if width == "u32_le":
        return struct.unpack("<I", data)[0]
    raise ValueError(f"unknown width: {width!r}")


class StateReader:
    def __init__(
        self,
        compiled_path: Path,
        runtime,
        *,
        plugin_scene_resolvers: list | None = None,
    ) -> None:
        self._runtime = runtime
        self._tags: dict[str, dict] = {}
        if compiled_path.exists():
            payload = json.loads(compiled_path.read_text())
            self._tags = payload.get("tags", {})
        self._scene_classifiers: dict[str, object] = {}
        if plugin_scene_resolvers or any(
            t.get("kind") == "scene" for t in self._tags.values()
        ):
            from retrokix.state.scene import SceneClassifier
            for tag, info in self._tags.items():
                if info.get("kind") == "scene":
                    self._scene_classifiers[tag] = SceneClassifier(
                        info, runtime,
                        plugin_resolvers=plugin_scene_resolvers or [],
                    )

    @property
    def has_tags(self) -> bool:
        return bool(self._tags) or bool(self._scene_classifiers)

    def read_all(self) -> dict[str, int | str | None]:
        out: dict[str, int | str | None] = {}
        for tag, info in self._tags.items():
            kind = info.get("kind")
            if kind == "scene":
                classifier = self._scene_classifiers.get(tag)
                out[tag] = classifier.classify() if classifier else None
                continue
            addr = int(info["addr"], 16)
            width = info["width"]
            n = _WIDTH_TO_BYTES[width]
            data = self._runtime.read_memory(addr, n)
            raw = _decode(width, data)
            if kind == "numeric":
                out[tag] = raw
            else:
                lookup = info.get("values", {})
                out[tag] = lookup.get(hex(raw), "?")
        return out
