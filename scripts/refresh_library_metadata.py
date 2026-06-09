#!/usr/bin/env python3
"""Regenerate src/gbax/data/no_intro_gba.json from archive.org.

Dev tool — run when the upstream archive.org snapshot moves to a new item,
or when entries change. The bundled snapshot is what `gbax search` uses;
this script doesn't run at install or runtime.

Usage:
    python scripts/refresh_library_metadata.py
"""

from __future__ import annotations

import json
import urllib.request
from pathlib import Path


ITEM = "ef_gba_no-intro_2024-02-21"
OUT = Path(__file__).resolve().parent.parent / "src" / "gbax" / "data" / "no_intro_gba.json"


def main() -> None:
    url = f"https://archive.org/metadata/{ITEM}"
    print(f"fetching {url} …")
    with urllib.request.urlopen(url, timeout=60) as resp:
        meta = json.load(resp)

    entries = []
    for f in meta.get("files", []):
        name = f.get("name", "")
        if not name.lower().endswith((".zip", ".gba")):
            continue
        entries.append({
            "name": name,
            "size": int(f.get("size", 0) or 0),
            "sha1": f.get("sha1"),
        })
    entries.sort(key=lambda e: e["name"])

    OUT.parent.mkdir(parents=True, exist_ok=True)
    with open(OUT, "w") as out:
        json.dump({"item": ITEM, "entries": entries}, out, separators=(",", ":"))

    print(f"wrote {OUT}  ({len(entries)} entries, {OUT.stat().st_size} bytes)")


if __name__ == "__main__":
    main()
