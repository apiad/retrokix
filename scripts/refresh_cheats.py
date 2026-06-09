#!/usr/bin/env python3
"""Compile libretro-database GBA cheat files into a single bundled JSON.

Dev tool — run when libretro-database publishes new cheats. The output
(`src/gbax/data/libretro_cheats_gba.json`) is what `gbax cheats <rom>`
consults at runtime. Zero network at runtime.

Format of the output:
    {
      "source": {"repo": "libretro/libretro-database", "commit": "<sha>", "fetched": "<iso>"},
      "rom_to_cheats": {
        "Pokemon - Emerald Version (USA, Europe)": [
          {"name": "Master Code", "code": "D8BAE4D9+..."},
          {"name": "Max Money",   "code": "82000568+..."},
          ...
        ],
        ...
      }
    }

The ROM key strips the trailing format suffix (e.g. "(Code Breaker)",
"(Action Replay)") so it matches the No-Intro filename of a ROM directly.

Usage:
    git clone --depth=1 https://github.com/libretro/libretro-database /tmp/libretro-database
    python scripts/refresh_cheats.py /tmp/libretro-database
"""

from __future__ import annotations

import json
import re
import subprocess
import sys
from pathlib import Path


GBA_DIR_REL = "cht/Nintendo - Game Boy Advance"
OUT = Path(__file__).resolve().parent.parent / "src" / "gbax" / "data" / "libretro_cheats_gba.json"

# Filenames look like "Pokemon - Emerald Version (USA, Europe) (Code Breaker).cht".
# We strip the trailing format suffix to get the No-Intro ROM name.
_FORMAT_SUFFIX = re.compile(
    r"\s*\((?:Code Breaker|Action Replay|GameShark|CodeBreaker|AR|GS)(?:[^)]*)\)$"
)


def parse_cht(text: str) -> list[dict]:
    """Parse a libretro .cht file → list of {name, code, enabled} dicts."""
    # Simple key=value scanner; values may be quoted.
    fields: dict[str, str] = {}
    for raw in text.splitlines():
        line = raw.strip()
        if not line or line.startswith(("#", ";")) or "=" not in line:
            continue
        k, _, v = line.partition("=")
        v = v.strip()
        if v.startswith('"') and v.endswith('"'):
            v = v[1:-1]
        fields[k.strip()] = v

    try:
        n = int(fields.get("cheats", "0"))
    except ValueError:
        return []

    cheats = []
    for i in range(n):
        name = fields.get(f"cheat{i}_desc")
        code = fields.get(f"cheat{i}_code")
        if not name or not code:
            continue
        cheats.append({"name": name, "code": code})
    return cheats


def main(db_root: Path) -> None:
    gba_dir = db_root / GBA_DIR_REL
    if not gba_dir.is_dir():
        print(f"error: {gba_dir} not found", file=sys.stderr)
        sys.exit(1)

    commit = "unknown"
    try:
        commit = subprocess.check_output(
            ["git", "-C", str(db_root), "rev-parse", "HEAD"], text=True
        ).strip()
    except subprocess.CalledProcessError:
        pass

    rom_to_cheats: dict[str, list[dict]] = {}
    for cht in sorted(gba_dir.glob("*.cht")):
        stem = cht.stem  # filename without .cht
        rom_key = _FORMAT_SUFFIX.sub("", stem).strip()
        cheats = parse_cht(cht.read_text(encoding="utf-8", errors="replace"))
        if not cheats:
            continue
        # Multiple cheat files per ROM are merged — usually Code Breaker +
        # Action Replay versions of the same game. Dedupe by name.
        existing = {c["name"]: c for c in rom_to_cheats.get(rom_key, [])}
        for c in cheats:
            existing.setdefault(c["name"], c)
        rom_to_cheats[rom_key] = sorted(existing.values(), key=lambda c: c["name"])

    from datetime import UTC, datetime
    out_doc = {
        "source": {
            "repo": "libretro/libretro-database",
            "commit": commit,
            "fetched": datetime.now(UTC).strftime("%Y-%m-%d"),
        },
        "rom_to_cheats": rom_to_cheats,
    }
    OUT.parent.mkdir(parents=True, exist_ok=True)
    with open(OUT, "w") as f:
        json.dump(out_doc, f, separators=(",", ":"))

    total = sum(len(v) for v in rom_to_cheats.values())
    print(f"wrote {OUT}")
    print(f"  {len(rom_to_cheats)} ROMs, {total} cheats, {OUT.stat().st_size} bytes")


if __name__ == "__main__":
    if len(sys.argv) != 2:
        print(f"usage: {sys.argv[0]} <libretro-database-checkout>", file=sys.stderr)
        sys.exit(2)
    main(Path(sys.argv[1]))
