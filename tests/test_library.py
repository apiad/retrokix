"""Tests for the ROM library — uses a stub metadata response, no network."""

from __future__ import annotations


import pytest

from gbax.library import RomEntry, RomLibrary, list_local_roms


@pytest.fixture
def stub_lib(monkeypatch):
    lib = RomLibrary()
    stub_entries = [
        RomEntry(name="Pokemon - Emerald Version (USA, Europe).zip", size=6_976_143, sha1="aaa"),
        RomEntry(name="Pokemon - Emerald Version (Japan).zip", size=6_900_000, sha1="bbb"),
        RomEntry(name="Pokemon - FireRed Version (USA).zip", size=6_500_000, sha1="ccc"),
        RomEntry(name="Mario Kart - Super Circuit (USA).zip", size=4_000_000, sha1="ddd"),
    ]
    monkeypatch.setattr(lib, "_fetch_metadata", lambda: list(stub_entries))
    return lib


def test_search_single_token(stub_lib):
    hits = stub_lib.search("emerald")
    assert {h.name for h in hits} == {
        "Pokemon - Emerald Version (USA, Europe).zip",
        "Pokemon - Emerald Version (Japan).zip",
    }


def test_search_multi_token_and(stub_lib):
    hits = stub_lib.search("pokemon emerald japan")
    assert [h.name for h in hits] == ["Pokemon - Emerald Version (Japan).zip"]


def test_search_case_insensitive(stub_lib):
    hits = stub_lib.search("MARIO")
    assert len(hits) == 1


def test_search_no_match(stub_lib):
    assert stub_lib.search("doesnotexist") == []


def test_search_empty(stub_lib):
    assert stub_lib.search("") == []


def test_entries_cached(stub_lib):
    a = stub_lib.entries()
    b = stub_lib.entries()
    assert a is b  # same list object, not refetched


def test_bundled_metadata_loads():
    """The vendored snapshot ships in the wheel and parses cleanly."""
    from gbax.library import _load_bundled_metadata

    item, entries = _load_bundled_metadata()
    assert item.startswith("ef_gba_no-intro")
    assert len(entries) > 1000  # No-Intro GBA set has thousands of entries
    # Sanity: Pokemon Emerald is in there.
    assert any("Pokemon" in e.name and "Emerald" in e.name for e in entries)


def test_default_library_uses_bundled_snapshot():
    """No network when refresh=False — entries come from the bundled file."""
    lib = RomLibrary()
    hits = lib.search("pokemon emerald")
    assert any("Emerald" in h.name and "(USA" in h.name for h in hits)


def test_list_local_roms_empty(tmp_path):
    assert list_local_roms(tmp_path) == []


def test_list_local_roms_filters_extension(tmp_path):
    (tmp_path / "a.gba").touch()
    (tmp_path / "b.gba").touch()
    (tmp_path / "c.zip").touch()
    (tmp_path / "README.md").touch()
    roms = list_local_roms(tmp_path)
    assert [p.name for p in roms] == ["a.gba", "b.gba"]


# --- resolve_rom ---


def test_resolve_rom_existing_path(tmp_path):
    from gbax.library import resolve_rom

    f = tmp_path / "anywhere.gba"
    f.touch()
    assert resolve_rom(str(f)) == f


def test_resolve_rom_fuzzy_single_match(tmp_path, monkeypatch):
    from gbax.library import resolve_rom

    (tmp_path / "Pokemon - Emerald Version (USA, Europe).gba").touch()
    (tmp_path / "Mario Kart - Super Circuit (USA).gba").touch()
    monkeypatch.setattr("gbax.library.DEFAULT_ROMS_DIR", tmp_path)
    result = resolve_rom("emerald", roms_dir=tmp_path)
    assert result.name == "Pokemon - Emerald Version (USA, Europe).gba"


def test_resolve_rom_fuzzy_multi_token(tmp_path):
    from gbax.library import resolve_rom

    (tmp_path / "Pokemon - Emerald Version (USA, Europe).gba").touch()
    (tmp_path / "Pokemon - Emerald Version (Japan).gba").touch()
    result = resolve_rom("emerald japan", roms_dir=tmp_path)
    assert "Japan" in result.name


def test_resolve_rom_no_match(tmp_path):
    import pytest
    from gbax.library import resolve_rom

    (tmp_path / "Pokemon - Emerald Version (USA, Europe).gba").touch()
    with pytest.raises(FileNotFoundError):
        resolve_rom("metroid", roms_dir=tmp_path)


def test_resolve_rom_ambiguous(tmp_path):
    import pytest
    from gbax.library import resolve_rom

    (tmp_path / "Pokemon - Emerald Version (USA, Europe).gba").touch()
    (tmp_path / "Pokemon - Emerald Version (Japan).gba").touch()
    with pytest.raises(RuntimeError, match="ambiguous"):
        resolve_rom("emerald", roms_dir=tmp_path)
