"""Regression tests for `RomLibrary.download` archive-extract behaviour.

The .7z code path covers GB / GBC where the No-Intro mirror packs ROMs
as 7-zip per entry. The GB-family cross-extension test guards against
the Pokemon Yellow case: a Yellow archive in the GBC mirror packs a
`.gb` member (Yellow is CGB-enhanced but runs on original GB), so the
extract step must accept either `.gb` or `.gbc` inside any GB-family
archive.
"""

from __future__ import annotations

import zipfile
from pathlib import Path

import py7zr

from retrokix.library import _extract_first_rom


def _make_zip(path: Path, members: dict[str, bytes]) -> None:
    with zipfile.ZipFile(path, "w") as z:
        for name, data in members.items():
            z.writestr(name, data)


def _make_7z(path: Path, members: dict[str, bytes], tmp: Path) -> None:
    """Write real files to disk then archive them — py7zr's `writestr`
    omits file permissions, which makes the extracted file unreadable.
    `writeall` from a real source preserves +r."""
    staging = tmp / f".staging-{path.stem}"
    staging.mkdir(parents=True, exist_ok=True)
    for name, data in members.items():
        (staging / name).write_bytes(data)
    with py7zr.SevenZipFile(path, "w") as z:
        for name in members:
            z.write(staging / name, name)


def test_extract_zip(tmp_path):
    arc = tmp_path / "Game.zip"
    dest = tmp_path / "out"
    dest.mkdir()
    _make_zip(arc, {"Game (USA).gba": b"\x00" * 32})
    out = _extract_first_rom(arc, dest, (".gba",))
    assert out.read_bytes() == b"\x00" * 32
    assert out.name == "Game (USA).gba"


def test_extract_7z(tmp_path):
    arc = tmp_path / "Game.7z"
    dest = tmp_path / "out"
    dest.mkdir()
    _make_7z(arc, {"Game (USA).gb": b"\xff" * 64}, tmp_path)
    out = _extract_first_rom(arc, dest, (".gb",))
    assert out.read_bytes() == b"\xff" * 64
    assert out.name == "Game (USA).gb"


def test_extract_7z_with_gb_in_gbc_archive_pokemon_yellow_regression(tmp_path):
    """The fix for the Pokemon Yellow bug: archives in the GBC No-Intro
    mirror sometimes pack a `.gb` member (Yellow runs on original GB
    plus has CGB enhancements). The download path passes (".gb", ".gbc")
    for any gb-family entry so this extract succeeds."""
    arc = tmp_path / "Pokemon - Yellow (USA, Europe) (CGB+SGB Enhanced).7z"
    dest = tmp_path / "out"
    dest.mkdir()
    _make_7z(arc, {
        "Pokemon - Yellow Version - Special Pikachu Edition (USA, Europe) (CGB+SGB Enhanced).gb": b"\x33" * 128,
    }, tmp_path)
    # Mimics the call site in RomLibrary.download for a GB-family entry.
    out = _extract_first_rom(arc, dest, (".gb", ".gbc"))
    assert out.read_bytes() == b"\x33" * 128
    assert out.suffix == ".gb"


def test_extract_raises_on_missing_extension(tmp_path):
    arc = tmp_path / "junk.zip"
    _make_zip(arc, {"README.txt": b"hello"})
    try:
        _extract_first_rom(arc, tmp_path, (".gba",))
    except RuntimeError as exc:
        assert "no member with extension" in str(exc)
    else:
        raise AssertionError("expected RuntimeError")
