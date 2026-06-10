"""Per-ROM, per-slot macros (recorded input sequences).

Macros are stored at ``~/.gbax/macros/<rom-sha1>/<slot>.json``, one file
per slot (F1..F9). Each file holds an event list of
``(delta_frames, buttons_held_set)`` tuples relative to the start of the
recording. Slot is the primary identity; ``name`` is optional metadata
shown in CLI listings.
"""
from __future__ import annotations

import json
from dataclasses import dataclass, field
from datetime import datetime
from pathlib import Path

from gbax.input import Button


DEFAULT_MACROS_ROOT = Path.home() / ".gbax" / "macros"
VALID_SLOTS = {f"F{i}" for i in range(1, 10)}


@dataclass
class Macro:
    slot: str
    name: str
    rom_sha1: str
    rom_name: str
    recorded_at: datetime
    total_frames: int
    events: list[tuple[int, frozenset[Button]]] = field(default_factory=list)


def _button_to_str(b: Button) -> str:
    return b.name.lower()


def _str_to_button(s: str) -> Button:
    return Button[s.upper()]


def macros_dir_for_rom(rom_sha1: str, *, macros_root: Path | None = None) -> Path:
    root = Path(macros_root) if macros_root else DEFAULT_MACROS_ROOT
    return root / rom_sha1


def _path_for(rom_sha1: str, slot: str, *, macros_root: Path | None = None) -> Path:
    return macros_dir_for_rom(rom_sha1, macros_root=macros_root) / f"{slot}.json"


def save(macro: Macro, *, macros_root: Path | None = None) -> Path:
    if macro.slot not in VALID_SLOTS:
        raise ValueError(f"slot must be F1..F9, got {macro.slot!r}")
    p = _path_for(macro.rom_sha1, macro.slot, macros_root=macros_root)
    p.parent.mkdir(parents=True, exist_ok=True)
    payload = {
        "slot": macro.slot,
        "name": macro.name,
        "rom_sha1": macro.rom_sha1,
        "rom_name": macro.rom_name,
        "recorded_at": macro.recorded_at.isoformat(),
        "total_frames": macro.total_frames,
        "events": [
            [delta, sorted(_button_to_str(b) for b in held)]
            for delta, held in macro.events
        ],
    }
    p.write_text(json.dumps(payload, indent=2))
    return p


def load(rom_sha1: str, slot: str, *, macros_root: Path | None = None) -> Macro | None:
    if slot not in VALID_SLOTS:
        return None
    p = _path_for(rom_sha1, slot, macros_root=macros_root)
    if not p.exists():
        return None
    try:
        data = json.loads(p.read_text())
        events = [
            (int(delta), frozenset(_str_to_button(s) for s in held))
            for delta, held in data["events"]
        ]
        return Macro(
            slot=data["slot"],
            name=data.get("name", ""),
            rom_sha1=data["rom_sha1"],
            rom_name=data.get("rom_name", ""),
            recorded_at=datetime.fromisoformat(data["recorded_at"]),
            total_frames=int(data["total_frames"]),
            events=events,
        )
    except (json.JSONDecodeError, KeyError, ValueError, OSError):
        return None


def delete(rom_sha1: str, slot: str, *, macros_root: Path | None = None) -> bool:
    p = _path_for(rom_sha1, slot, macros_root=macros_root)
    if not p.exists():
        return False
    p.unlink()
    return True


def list_for_rom(rom_sha1: str, *, macros_root: Path | None = None) -> list[Macro]:
    d = macros_dir_for_rom(rom_sha1, macros_root=macros_root)
    if not d.exists():
        return []
    out: list[Macro] = []
    for slot in sorted(VALID_SLOTS):
        m = load(rom_sha1, slot, macros_root=macros_root)
        if m is not None:
            out.append(m)
    return out
