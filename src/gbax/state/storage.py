"""Path helpers and label parser for the state tracker."""
from __future__ import annotations

from pathlib import Path


DEFAULT_STATE_ROOT = Path.home() / ".gbax" / "states"


def state_root_for_rom(rom_sha1: str, *, root: Path | None = None) -> Path:
    return (Path(root) if root else DEFAULT_STATE_ROOT) / rom_sha1


def captures_dir_for_rom(rom_sha1: str, *, root: Path | None = None) -> Path:
    return state_root_for_rom(rom_sha1, root=root) / "captures"


def compiled_path_for_rom(rom_sha1: str, *, root: Path | None = None) -> Path:
    return state_root_for_rom(rom_sha1, root=root) / "compiled.json"


def parse_labels(text: str) -> dict[str, int | str]:
    """Parse a comma-separated key=value label string.

    Integer values are coerced to int; everything else is left as a
    trimmed string. Empty pairs are silently skipped. A pair missing
    an '=' raises ValueError.
    """
    out: dict[str, int | str] = {}
    for chunk in text.split(","):
        s = chunk.strip()
        if not s:
            continue
        if "=" not in s:
            raise ValueError(f"label pair missing '=': {s!r}")
        k, v = s.split("=", 1)
        k = k.strip()
        v = v.strip()
        try:
            out[k] = int(v)
        except ValueError:
            out[k] = v
    return out
