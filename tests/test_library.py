"""Tests for the ROM library — uses a stub metadata response, no network."""

from __future__ import annotations


import pytest

from retrokix.library import RomEntry, RomLibrary, list_local_roms


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
    from retrokix.library import _load_bundled_metadata

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
    from retrokix.library import resolve_rom

    f = tmp_path / "anywhere.gba"
    f.touch()
    assert resolve_rom(str(f)) == f


def test_resolve_rom_fuzzy_single_match(tmp_path, monkeypatch):
    from retrokix.library import resolve_rom

    (tmp_path / "Pokemon - Emerald Version (USA, Europe).gba").touch()
    (tmp_path / "Mario Kart - Super Circuit (USA).gba").touch()
    monkeypatch.setattr("retrokix.library.DEFAULT_ROMS_DIR", tmp_path)
    result = resolve_rom("emerald", roms_dir=tmp_path)
    assert result.name == "Pokemon - Emerald Version (USA, Europe).gba"


def test_resolve_rom_fuzzy_multi_token(tmp_path):
    from retrokix.library import resolve_rom

    (tmp_path / "Pokemon - Emerald Version (USA, Europe).gba").touch()
    (tmp_path / "Pokemon - Emerald Version (Japan).gba").touch()
    result = resolve_rom("emerald japan", roms_dir=tmp_path)
    assert "Japan" in result.name


def test_resolve_rom_no_match(tmp_path):
    import pytest
    from retrokix.library import resolve_rom

    (tmp_path / "Pokemon - Emerald Version (USA, Europe).gba").touch()
    with pytest.raises(FileNotFoundError):
        resolve_rom("metroid", roms_dir=tmp_path)


def test_resolve_rom_ambiguous(tmp_path):
    import pytest
    from retrokix.library import resolve_rom

    (tmp_path / "Pokemon - Emerald Version (USA, Europe).gba").touch()
    (tmp_path / "Pokemon - Emerald Version (Japan).gba").touch()
    with pytest.raises(RuntimeError, match="ambiguous"):
        resolve_rom("emerald", roms_dir=tmp_path)


# ---------- multi-console (NES + GBA) ----------

def test_bundled_metadata_includes_both_consoles():
    """Default RomLibrary loads GBA + NES entries together."""
    from retrokix.library import RomLibrary

    lib = RomLibrary()
    entries = lib.entries()
    consoles = {e.console for e in entries}
    assert {"gba", "nes"}.issubset(consoles)
    # Pokemon Emerald (GBA) and Super Mario Bros. (NES) are both
    # canonical anchors in their sets.
    assert any(e.console == "gba" and "Pokemon" in e.name and "Emerald" in e.name for e in entries)
    assert any(e.console == "nes" and "Super Mario Bros." in e.name for e in entries)


def test_console_filter_constrains_to_one_set():
    from retrokix.library import RomLibrary

    nes_only = RomLibrary(console="nes").entries()
    assert nes_only
    assert all(e.console == "nes" for e in nes_only)
    assert all(e.name.lower().endswith(".zip") for e in nes_only)


def test_search_returns_cross_console_matches():
    """A query like 'mario' hits both GBA and NES — caller is expected
    to disambiguate by inspecting entry.console."""
    from retrokix.library import RomLibrary

    lib = RomLibrary()
    hits = lib.search("mario")
    consoles = {h.console for h in hits}
    assert {"gba", "nes"}.issubset(consoles)


def test_console_for_path_dispatches_by_extension(tmp_path):
    from retrokix.library import console_for_path

    assert console_for_path(tmp_path / "rom.gba") == "gba"
    assert console_for_path(tmp_path / "rom.nes") == "nes"
    assert console_for_path(tmp_path / "rom.smc") is None
    assert console_for_path("Pokemon.gba") == "gba"


def test_list_local_roms_finds_both_extensions(tmp_path):
    """list_local_roms picks up .gba AND .nes — single roms dir, mixed."""
    from retrokix.library import list_local_roms

    (tmp_path / "Pokemon.gba").touch()
    (tmp_path / "Super Mario Bros.nes").touch()
    (tmp_path / "not_a_rom.txt").touch()
    out = sorted(p.name for p in list_local_roms(tmp_path))
    assert out == ["Pokemon.gba", "Super Mario Bros.nes"]


def test_rom_entry_title_strips_known_extensions():
    from retrokix.library import RomEntry

    e = RomEntry(name="Pokemon - Emerald Version (USA, Europe).zip",
                 size=0, sha1=None, console="gba")
    assert e.title == "Pokemon - Emerald Version (USA, Europe)"
    e2 = RomEntry(name="Super Mario Bros..nes", size=0, sha1=None, console="nes")
    assert e2.title == "Super Mario Bros."
