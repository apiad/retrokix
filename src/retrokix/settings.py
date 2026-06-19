"""Per-ROM persistent settings.

A small JSON sidecar at `~/.retrokix/settings/<rom_sha1>.json` that
remembers playback preferences across sessions: emulator speed, SDL
window state, last-used save slot. Loaded once on runtime init,
persisted on change.

Defaults match the CLI defaults so a missing file behaves identically
to a fresh user. Unknown JSON keys are ignored (forward-compat for
new fields added later in the same file).

Atomic writes via tmp-file + rename so a crash mid-write can't leave a
corrupt JSON behind.
"""
from __future__ import annotations

import json
import os
import tempfile
from dataclasses import asdict, dataclass, fields, replace
from pathlib import Path


DEFAULT_SETTINGS_DIR = Path.home() / ".retrokix" / "settings"


@dataclass(frozen=True)
class RomSettings:
    """Persistent per-ROM playback preferences.

    Frozen so callers explicitly produce new instances rather than
    mutating shared state — keeps the save semantics obvious.
    """
    speed_multiplier: float = 1.0
    fullscreen: bool = False
    window_scale: int = 3
    last_slot: int | None = None

    @classmethod
    def from_dict(cls, data: dict) -> "RomSettings":
        kwargs = {}
        names = {f.name for f in fields(cls)}
        for k, v in (data or {}).items():
            if k not in names:
                continue
            kwargs[k] = v
        return cls(**kwargs)

    def to_dict(self) -> dict:
        return asdict(self)


def _path_for(rom_sha1: str, root: Path | None = None) -> Path:
    base = Path(root) if root else DEFAULT_SETTINGS_DIR
    return base / f"{rom_sha1}.json"


def load(rom_sha1: str, root: Path | None = None) -> RomSettings:
    """Return persisted settings, or `RomSettings()` defaults if absent
    or unreadable. Never raises."""
    p = _path_for(rom_sha1, root)
    if not p.exists():
        return RomSettings()
    try:
        data = json.loads(p.read_text())
    except (json.JSONDecodeError, OSError):
        return RomSettings()
    if not isinstance(data, dict):
        return RomSettings()
    return RomSettings.from_dict(data)


def save(rom_sha1: str, settings: RomSettings, root: Path | None = None) -> Path:
    """Atomically write settings to disk. Returns the target path."""
    p = _path_for(rom_sha1, root)
    p.parent.mkdir(parents=True, exist_ok=True)
    payload = json.dumps(settings.to_dict(), indent=2, sort_keys=True)
    # tmp file in same dir so os.replace is atomic across the rename.
    fd, tmp_name = tempfile.mkstemp(
        prefix=f".{rom_sha1}.", suffix=".tmp", dir=p.parent
    )
    try:
        with os.fdopen(fd, "w") as f:
            f.write(payload)
        os.replace(tmp_name, p)
    except Exception:
        # Best-effort cleanup if the rename never happened.
        try:
            os.unlink(tmp_name)
        except FileNotFoundError:
            pass
        raise
    return p


def update(rom_sha1: str, root: Path | None = None, **changes) -> RomSettings:
    """Load → merge changes → save. Returns the new settings.

    Keys not on `RomSettings` are silently ignored to keep callers
    forward-compatible with future fields they don't know about.
    """
    current = load(rom_sha1, root)
    valid = {f.name for f in fields(RomSettings)}
    filtered = {k: v for k, v in changes.items() if k in valid}
    new = replace(current, **filtered)
    if new == current:
        return current
    save(rom_sha1, new, root)
    return new
