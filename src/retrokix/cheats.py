"""Cheat code database and runtime hookup.

The libretro mGBA core handles Code Breaker, Action Replay, and GameShark
codes natively — retrokix just passes the raw code string through
`retro_cheat_set`. The community database (libretro/libretro-database) of
~6700 named GBA cheats is vendored at `retrokix/data/libretro_cheats_gba.json`.
"""

from __future__ import annotations

import json
import re
import sys
from dataclasses import dataclass


if sys.version_info >= (3, 11):
    from importlib.resources import files as _resource_files
else:  # pragma: no cover
    from importlib_resources import files as _resource_files  # type: ignore


# Strip the trailing format suffix from a No-Intro / libretro ROM name so we
# can map either back to the canonical game key.
_FORMAT_SUFFIX = re.compile(
    r"\s*\((?:Code Breaker|Action Replay|GameShark|CodeBreaker|AR|GS)(?:[^)]*)\)$"
)


@dataclass(frozen=True)
class Cheat:
    name: str
    code: str

    def slug(self) -> str:
        """A URL-safe, lowercase, kebab-style identifier for API addressing."""
        s = self.name.lower()
        s = re.sub(r"[^a-z0-9]+", "-", s).strip("-")
        return s or "cheat"


def _load_bundled_cheats() -> dict[str, list[Cheat]]:
    blob = _resource_files("retrokix.data").joinpath("libretro_cheats_gba.json").read_text()
    data = json.loads(blob)
    out: dict[str, list[Cheat]] = {}
    for rom_key, entries in data["rom_to_cheats"].items():
        out[rom_key] = [Cheat(name=e["name"], code=e["code"]) for e in entries]
    return out


def _rom_key(filename: str) -> str:
    """Drop a `.gba` / `.zip` extension and the format suffix to get a stable key."""
    stem = filename
    for ext in (".gba", ".zip"):
        if stem.lower().endswith(ext):
            stem = stem[: -len(ext)]
            break
    return _FORMAT_SUFFIX.sub("", stem).strip()


def cheats_for_rom(rom_filename: str) -> list[Cheat]:
    """Return cheats matching the given ROM filename, or [] if none are catalogued."""
    db = _load_bundled_cheats()
    return db.get(_rom_key(rom_filename), [])
