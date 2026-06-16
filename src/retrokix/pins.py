"""Per-ROM cheat-hotkey pins.

`~/.retrokix/pins/<rom-sha1>.json` maps a function-key name ("F1" … "F9") to a
cheat slug. Used by the SDL play loop to toggle the same cheat with the
same key across sessions, regardless of which order cheats were enabled.
"""

from __future__ import annotations

import json
from pathlib import Path


DEFAULT_PINS_DIR = Path.home() / ".retrokix" / "pins"
VALID_KEYS = {f"F{i}" for i in range(1, 10)}  # F1..F9


def _path_for(rom_sha1: str, pins_dir: Path | None = None) -> Path:
    base = Path(pins_dir) if pins_dir else DEFAULT_PINS_DIR
    return base / f"{rom_sha1}.json"


def load(rom_sha1: str, pins_dir: Path | None = None) -> dict[str, str]:
    p = _path_for(rom_sha1, pins_dir)
    if not p.exists():
        return {}
    try:
        data = json.loads(p.read_text())
    except (json.JSONDecodeError, OSError):
        return {}
    return {k: v for k, v in data.items() if k in VALID_KEYS and isinstance(v, str)}


def save(rom_sha1: str, pins: dict[str, str], pins_dir: Path | None = None) -> Path:
    p = _path_for(rom_sha1, pins_dir)
    p.parent.mkdir(parents=True, exist_ok=True)
    cleaned = {k: v for k, v in pins.items() if k in VALID_KEYS and isinstance(v, str)}
    p.write_text(json.dumps(cleaned, indent=2, sort_keys=True))
    return p


def set_pin(rom_sha1: str, key: str, slug: str, pins_dir: Path | None = None) -> Path:
    if key not in VALID_KEYS:
        raise ValueError(f"key must be F1..F9, got {key!r}")
    pins = load(rom_sha1, pins_dir)
    pins[key] = slug
    return save(rom_sha1, pins, pins_dir)


def unset_pin(rom_sha1: str, key: str, pins_dir: Path | None = None) -> Path:
    if key not in VALID_KEYS:
        raise ValueError(f"key must be F1..F9, got {key!r}")
    pins = load(rom_sha1, pins_dir)
    pins.pop(key, None)
    return save(rom_sha1, pins, pins_dir)
