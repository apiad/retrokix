#!/usr/bin/env python3
"""Regenerate src/retrokix/data/no_intro_<console>.json from archive.org.

Dev tool — run when the upstream archive.org snapshot moves to a new
item, or when entries change. The bundled snapshots are what
`retrokix search`, `retrokix browse`, and `retrokix download` consult; this
script doesn't run at install or runtime.

Usage:
    python scripts/refresh_library_metadata.py           # all consoles
    python scripts/refresh_library_metadata.py gba       # GBA only
    python scripts/refresh_library_metadata.py nes       # NES only
"""

from __future__ import annotations

import json
import sys
import urllib.request
from pathlib import Path


# Each console points at an "edge of forever" archive.org mirror of the
# corresponding No-Intro set. Same shape for every entry: per-game .zip
# directly under the item, listed in the metadata `files` array.
CONSOLES: dict[str, dict[str, object]] = {
    "gba": {
        "item": "ef_gba_no-intro_2024-02-21",
        "rom_exts": (".gba",),
    },
    "nes": {
        "item": "ef_nintendo_entertainment_-system_-no-intro_2024-04-23",
        "rom_exts": (".nes",),
    },
}


def _data_path(console: str) -> Path:
    return (
        Path(__file__).resolve().parent.parent
        / "src" / "retrokix" / "data" / f"no_intro_{console}.json"
    )


def refresh(console: str) -> None:
    if console not in CONSOLES:
        raise SystemExit(
            f"unknown console {console!r}; choices: {', '.join(sorted(CONSOLES))}"
        )
    cfg = CONSOLES[console]
    item: str = cfg["item"]  # type: ignore[assignment]
    rom_exts: tuple[str, ...] = cfg["rom_exts"]  # type: ignore[assignment]

    url = f"https://archive.org/metadata/{item}"
    print(f"[{console}] fetching {url} …")
    with urllib.request.urlopen(url, timeout=60) as resp:
        meta = json.load(resp)

    entries = []
    for f in meta.get("files", []):
        name = f.get("name", "")
        lower = name.lower()
        # Accept the canonical .zip per-rom shape plus a bare-rom fallback.
        if not (lower.endswith(".zip") or lower.endswith(rom_exts)):
            continue
        entries.append({
            "name": name,
            "size": int(f.get("size", 0) or 0),
            "sha1": f.get("sha1"),
        })
    entries.sort(key=lambda e: e["name"])

    out = _data_path(console)
    out.parent.mkdir(parents=True, exist_ok=True)
    with open(out, "w") as fh:
        json.dump({"item": item, "console": console, "entries": entries}, fh, separators=(",", ":"))

    print(f"[{console}] wrote {out}  ({len(entries)} entries, {out.stat().st_size} bytes)")


def main() -> None:
    if len(sys.argv) > 1:
        targets = sys.argv[1:]
    else:
        targets = list(CONSOLES.keys())
    for c in targets:
        refresh(c)


if __name__ == "__main__":
    main()
