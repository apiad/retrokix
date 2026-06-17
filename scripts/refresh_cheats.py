#!/usr/bin/env python3
"""Compile libretro-database cheat files into a bundled JSON per console.

Dev tool — run when libretro-database publishes new cheats. The output
(`src/retrokix/data/libretro_cheats_<console>.json`) is what `retrokix cheats
<rom>` consults at runtime. Zero network at runtime.

Format of the output:
    {
      "source": {"repo": "libretro/libretro-database", "commit": "<sha>", "fetched": "<iso>"},
      "console": "gba" | "nes" | …,
      "rom_to_cheats": {
        "Pokemon - Emerald Version (USA, Europe)": [
          {"name": "Master Code", "code": "D8BAE4D9+..."},
          ...
        ],
        ...
      }
    }

The ROM key strips trailing format suffixes ("(Code Breaker)",
"(Action Replay)", "(Game Genie)", …) so it matches the No-Intro
filename of a ROM directly.

Usage:
    git clone --depth=1 https://github.com/libretro/libretro-database /tmp/libretro-database
    python scripts/refresh_cheats.py /tmp/libretro-database         # all consoles
    python scripts/refresh_cheats.py /tmp/libretro-database gba     # one console
"""

from __future__ import annotations

import json
import re
import subprocess
import sys
from pathlib import Path


# Each console's libretro-database folder + the cheat-format suffix
# patterns that show up in filenames for that platform.
CONSOLES: dict[str, dict[str, object]] = {
    "gba": {
        "dir": "cht/Nintendo - Game Boy Advance",
        "suffix_re": re.compile(
            r"\s*\((?:Code Breaker|Action Replay|GameShark|CodeBreaker|AR|GS)(?:[^)]*)\)$"
        ),
    },
    "nes": {
        "dir": "cht/Nintendo - Nintendo Entertainment System",
        "suffix_re": re.compile(
            r"\s*\((?:Game Genie|Action Replay|GG|AR|Pro Action Replay)(?:[^)]*)\)$"
        ),
    },
    "snes": {
        "dir": "cht/Nintendo - Super Nintendo Entertainment System",
        "suffix_re": re.compile(
            r"\s*\((?:Game Genie|Pro Action Replay|Action Replay|GG|PAR|AR)(?:[^)]*)\)$"
        ),
    },
    "gb": {
        "dir": "cht/Nintendo - Game Boy",
        "suffix_re": re.compile(
            r"\s*\((?:Game Genie|GameShark|Game Shark|Pro Action Replay|GG|GS|PAR)(?:[^)]*)\)$"
        ),
    },
    "gbc": {
        "dir": "cht/Nintendo - Game Boy Color",
        "suffix_re": re.compile(
            r"\s*\((?:Game Genie|GameShark|Game Shark|Pro Action Replay|GG|GS|PAR)(?:[^)]*)\)$"
        ),
    },
}


def _data_path(console: str) -> Path:
    return (
        Path(__file__).resolve().parent.parent
        / "src" / "retrokix" / "data" / f"libretro_cheats_{console}.json"
    )


def parse_cht(text: str) -> list[dict]:
    """Parse a libretro .cht file → list of {name, code} dicts."""
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


def refresh(db_root: Path, console: str) -> None:
    if console not in CONSOLES:
        raise SystemExit(
            f"unknown console {console!r}; choices: {', '.join(sorted(CONSOLES))}"
        )
    cfg = CONSOLES[console]
    cht_dir = db_root / cfg["dir"]  # type: ignore[operator]
    if not cht_dir.is_dir():
        raise SystemExit(f"error: {cht_dir} not found")

    suffix_re: re.Pattern[str] = cfg["suffix_re"]  # type: ignore[assignment]

    commit = "unknown"
    try:
        commit = subprocess.check_output(
            ["git", "-C", str(db_root), "rev-parse", "HEAD"], text=True
        ).strip()
    except subprocess.CalledProcessError:
        pass

    rom_to_cheats: dict[str, list[dict]] = {}
    for cht in sorted(cht_dir.glob("*.cht")):
        stem = cht.stem
        rom_key = suffix_re.sub("", stem).strip()
        cheats = parse_cht(cht.read_text(encoding="utf-8", errors="replace"))
        if not cheats:
            continue
        # Multiple cheat files per ROM merge (e.g. Game Genie + Action
        # Replay variants); dedupe by name, first wins.
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
        "console": console,
        "rom_to_cheats": rom_to_cheats,
    }
    out = _data_path(console)
    out.parent.mkdir(parents=True, exist_ok=True)
    with open(out, "w") as fh:
        json.dump(out_doc, fh, separators=(",", ":"))

    total = sum(len(v) for v in rom_to_cheats.values())
    print(f"[{console}] wrote {out}")
    print(f"[{console}]   {len(rom_to_cheats)} ROMs, {total} cheats, {out.stat().st_size} bytes")


def main() -> None:
    if len(sys.argv) < 2:
        print(f"usage: {sys.argv[0]} <libretro-database-checkout> [console ...]", file=sys.stderr)
        sys.exit(2)
    db_root = Path(sys.argv[1])
    targets = sys.argv[2:] or list(CONSOLES.keys())
    for c in targets:
        refresh(db_root, c)


if __name__ == "__main__":
    main()
