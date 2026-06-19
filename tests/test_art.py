"""Tests for the per-ROM art cache (libretro-thumbnails fetcher)."""

from __future__ import annotations

from pathlib import Path
from urllib.error import HTTPError

import pytest

from retrokix import art


_PNG = (
    b"\x89PNG\r\n\x1a\n"
    b"\x00\x00\x00\rIHDR\x00\x00\x00\x01\x00\x00\x00\x01"
    b"\x08\x02\x00\x00\x00\x90wS\xde"
    b"\x00\x00\x00\x0cIDATx\x9cc\xf8\xcf\xc0\xc0\xc0\x00\x00\x00\x05\x00\x01"
    b"^\xf3*:"
    b"\x00\x00\x00\x00IEND\xaeB`\x82"
)


def test_sanitize_title_replaces_unsafe_chars() -> None:
    assert art._sanitize_title("Foo & Bar") == "Foo _ Bar"
    assert art._sanitize_title("A/B") == "A_B"
    assert art._sanitize_title("safe-name (USA)") == "safe-name (USA)"


def test_build_url_uses_console_repo_and_kind_dir() -> None:
    url = art._build_url("gba", "Pokemon - Emerald Version (USA, Europe)", "snap")
    assert "Nintendo_-_Game_Boy_Advance" in url
    assert "Named_Snaps" in url
    assert url.endswith(".png")
    # The (USA, Europe) parenthesis stays — no special-char hits.
    assert "Pokemon%20-%20Emerald%20Version" in url


def test_build_url_kinds() -> None:
    base = art._build_url("nes", "Foo", "boxart")
    assert "Named_Boxarts" in base
    assert "Nintendo_-_Nintendo_Entertainment_System" in base


def test_art_paths_for_rom_uses_console_subdir(tmp_path: Path) -> None:
    rom = tmp_path / "Pokemon - Emerald Version (USA, Europe).gba"
    rom.touch()
    paths = art.art_paths_for_rom(rom, root=tmp_path / "cache")
    assert paths is not None
    assert set(paths.keys()) == {"snap", "boxart", "title"}
    assert paths["snap"].parent.parent.name == "gba"
    assert paths["snap"].name == "snap.png"


def test_art_paths_for_rom_returns_none_for_unknown_console(tmp_path: Path) -> None:
    rom = tmp_path / "something.unknown"
    rom.touch()
    assert art.art_paths_for_rom(rom, root=tmp_path / "cache") is None


def test_fetch_art_writes_bytes_on_hit(monkeypatch: pytest.MonkeyPatch, tmp_path: Path) -> None:
    rom = tmp_path / "Tetris.gb"
    rom.touch()
    cache = tmp_path / "cache"

    def fake_fetch(url: str) -> bytes:
        return _PNG

    monkeypatch.setattr(art, "_fetch", fake_fetch)
    result = art.fetch_art_for_rom(rom, root=cache)
    assert result == {"snap": "hit", "boxart": "hit", "title": "hit"}
    paths = art.art_paths_for_rom(rom, root=cache)
    assert paths is not None
    for p in paths.values():
        assert p.read_bytes() == _PNG


def test_fetch_art_writes_sentinel_on_404(monkeypatch: pytest.MonkeyPatch, tmp_path: Path) -> None:
    rom = tmp_path / "Obscure.gba"
    rom.touch()
    cache = tmp_path / "cache"

    def fake_fetch(url: str) -> bytes | None:
        return None  # mimic 404

    monkeypatch.setattr(art, "_fetch", fake_fetch)
    result = art.fetch_art_for_rom(rom, root=cache)
    assert all(v == "missing" for v in result.values())
    for p in art.art_paths_for_rom(rom, root=cache).values():
        assert p.exists()
        assert p.stat().st_size == 0


def test_fetch_art_skips_cached(monkeypatch: pytest.MonkeyPatch, tmp_path: Path) -> None:
    rom = tmp_path / "Mario.nes"
    rom.touch()
    cache = tmp_path / "cache"
    # Pre-populate the snap.
    paths = art.art_paths_for_rom(rom, root=cache)
    paths["snap"].parent.mkdir(parents=True, exist_ok=True)
    paths["snap"].write_bytes(_PNG)

    calls: list[str] = []

    def fake_fetch(url: str) -> bytes:
        calls.append(url)
        return _PNG

    monkeypatch.setattr(art, "_fetch", fake_fetch)
    result = art.fetch_art_for_rom(rom, root=cache)
    assert result["snap"] == "cached"
    # boxart + title still fetched
    assert result["boxart"] == "hit"
    assert result["title"] == "hit"
    assert len(calls) == 2


def test_fetch_art_force_refetches(monkeypatch: pytest.MonkeyPatch, tmp_path: Path) -> None:
    rom = tmp_path / "Mario.nes"
    rom.touch()
    cache = tmp_path / "cache"
    paths = art.art_paths_for_rom(rom, root=cache)
    paths["snap"].parent.mkdir(parents=True, exist_ok=True)
    paths["snap"].write_bytes(b"stale")

    monkeypatch.setattr(art, "_fetch", lambda url: _PNG)
    result = art.fetch_art_for_rom(rom, root=cache, force=True)
    assert result["snap"] == "hit"
    assert paths["snap"].read_bytes() == _PNG


def test_fetch_art_swallows_non_404_errors(monkeypatch: pytest.MonkeyPatch, tmp_path: Path) -> None:
    rom = tmp_path / "X.gba"
    rom.touch()
    cache = tmp_path / "cache"

    def fake_fetch(url: str) -> bytes:
        raise RuntimeError("boom")

    monkeypatch.setattr(art, "_fetch", fake_fetch)
    result = art.fetch_art_for_rom(rom, root=cache)
    assert all(v == "error" for v in result.values())


def test_fetch_propagates_500_as_error(monkeypatch: pytest.MonkeyPatch) -> None:
    # White-box: _fetch should raise on non-404 HTTPError.
    def fake_urlopen(req, timeout=None):  # noqa: ARG001
        raise HTTPError("u", 500, "boom", {}, None)

    monkeypatch.setattr(art.urllib.request, "urlopen", fake_urlopen)
    with pytest.raises(HTTPError):
        art._fetch("https://example.invalid/x.png")


def test_best_art_prefers_snap(tmp_path: Path) -> None:
    rom = tmp_path / "Game.gba"
    rom.touch()
    cache = tmp_path / "cache"
    paths = art.art_paths_for_rom(rom, root=cache)
    paths["snap"].parent.mkdir(parents=True, exist_ok=True)
    paths["snap"].write_bytes(_PNG)
    paths["boxart"].write_bytes(_PNG)
    best = art.best_art_for_rom(rom, root=cache)
    assert best == paths["snap"]


def test_best_art_falls_back_to_boxart_then_title(tmp_path: Path) -> None:
    rom = tmp_path / "Game.gba"
    rom.touch()
    cache = tmp_path / "cache"
    paths = art.art_paths_for_rom(rom, root=cache)
    paths["snap"].parent.mkdir(parents=True, exist_ok=True)
    # snap sentinel (zero bytes), boxart has real content
    paths["snap"].write_bytes(b"")
    paths["boxart"].write_bytes(_PNG)
    assert art.best_art_for_rom(rom, root=cache) == paths["boxart"]

    # Now nothing but title
    paths["boxart"].write_bytes(b"")
    paths["title"].write_bytes(_PNG)
    assert art.best_art_for_rom(rom, root=cache) == paths["title"]


def test_best_art_returns_none_when_only_sentinels(tmp_path: Path) -> None:
    rom = tmp_path / "Game.gba"
    rom.touch()
    cache = tmp_path / "cache"
    paths = art.art_paths_for_rom(rom, root=cache)
    paths["snap"].parent.mkdir(parents=True, exist_ok=True)
    for p in paths.values():
        p.write_bytes(b"")
    assert art.best_art_for_rom(rom, root=cache) is None


def test_art_path_if_present_validates_kind(tmp_path: Path) -> None:
    rom = tmp_path / "Game.gba"
    rom.touch()
    assert art.art_path_if_present(rom, "bogus") is None
