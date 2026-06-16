"""Tests for `retrokix browse` — pure helpers + a Textual Pilot smoke test."""

from __future__ import annotations

from unittest.mock import MagicMock

import pytest

from retrokix.browse import (
    BrowseApp,
    GroupRow,
    MAX_RESULTS,
    _fmt_size,
    _group_entries,
    _title_key,
    _trim_name,
)
from retrokix.library import RomEntry, RomLibrary


# ---------- helpers ----------

def test_fmt_size_megabytes():
    assert _fmt_size(6_976_143) == "6.7 MB"

def test_fmt_size_kilobytes_when_under_1mb():
    assert _fmt_size(500_000) == "488 KB"

def test_trim_name_strips_zip():
    assert _trim_name("Pokemon - Emerald.zip", 80) == "Pokemon - Emerald"

def test_trim_name_ellipsizes_when_too_long():
    long = "A" * 100 + ".zip"
    result = _trim_name(long, 20)
    assert result.endswith("…")
    assert len(result) == 20

def test_title_key_strips_parenthetical():
    assert (
        _title_key("Pokemon - Emerald Version (USA, Europe).zip")
        == "Pokemon - Emerald Version"
    )

def test_title_key_handles_no_parenthetical():
    assert _title_key("Mother 3.zip") == "Mother 3"

def test_group_entries_collapses_variants_and_canonicalizes_order():
    entries = [
        RomEntry(name="Pokemon - Emerald Version (Japan).zip", size=6_900_000, sha1="b"),
        RomEntry(name="Pokemon - Emerald Version (USA, Europe).zip", size=6_976_143, sha1="a"),
        RomEntry(name="Mario Kart - Super Circuit (USA).zip", size=4_000_000, sha1="c"),
    ]
    groups = _group_entries(entries)
    # First-appearance order preserved across titles.
    assert [g.title for g in groups] == [
        "Pokemon - Emerald Version",
        "Mario Kart - Super Circuit",
    ]
    emerald = groups[0]
    assert len(emerald.variants) == 2
    # USA/Europe should be canonical first, not Japan.
    assert emerald.primary.name == "Pokemon - Emerald Version (USA, Europe).zip"
    assert emerald.extra_count == 1


# ---------- pilot smoke ----------

@pytest.fixture
def stub_lib(monkeypatch):
    lib = RomLibrary()
    stub_entries = [
        RomEntry(name="Pokemon - Emerald Version (USA, Europe).zip", size=6_976_143, sha1="aaa"),
        RomEntry(name="Pokemon - Emerald Version (Japan).zip", size=6_900_000, sha1="bbb"),
        RomEntry(name="Pokemon - FireRed Version (USA).zip", size=6_500_000, sha1="ccc"),
        RomEntry(name="Legend of Zelda, The - The Minish Cap (USA).zip", size=8_000_000, sha1="ddd"),
        RomEntry(name="Mario Kart - Super Circuit (USA).zip", size=4_000_000, sha1="eee"),
    ]
    monkeypatch.setattr(lib, "_fetch_metadata", lambda: list(stub_entries))
    return lib


async def test_browse_default_shows_famous_groups(stub_lib):
    """Empty query → famous-games resolver returns RomGroup instances
    whose primary variants exist in the stub index."""
    app = BrowseApp(lib=stub_lib)
    async with app.run_test() as pilot:
        await pilot.pause()
        assert app._results, "famous resolver should return at least one group"
        stub_names = {e.name for e in stub_lib.entries()}
        assert all(g.primary.name in stub_names for g in app._results)


async def test_browse_caps_results_at_max(stub_lib):
    """Searching for 'pokemon' against a stub with 3 pokemon entries collapses
    them into 2 groups (Emerald has two variants, FireRed has one). Cap holds."""
    app = BrowseApp(lib=stub_lib, initial_query="pokemon")
    async with app.run_test() as pilot:
        await pilot.pause()
        assert len(app._results) == 2  # Emerald (group), FireRed (group)
        assert len(app._results) <= MAX_RESULTS
        emerald = next(g for g in app._results if "Emerald" in g.title)
        assert emerald.extra_count == 1


async def test_browse_filters_as_you_type(stub_lib):
    app = BrowseApp(lib=stub_lib)
    async with app.run_test() as pilot:
        await pilot.press("z", "e", "l", "d", "a")
        await pilot.pause()
        titles = [g.title for g in app._results]
        assert titles == ["Legend of Zelda, The - The Minish Cap"]


async def test_browse_initial_query_prefills(stub_lib):
    app = BrowseApp(lib=stub_lib, initial_query="emerald")
    async with app.run_test() as pilot:
        await pilot.pause()
        assert [g.title for g in app._results] == ["Pokemon - Emerald Version"]
        # Both variants collapsed under one group.
        assert {v.name for v in app._results[0].variants} == {
            "Pokemon - Emerald Version (USA, Europe).zip",
            "Pokemon - Emerald Version (Japan).zip",
        }


async def test_browse_enter_on_single_variant_group_downloads(stub_lib, tmp_path):
    """Group with one variant → Enter triggers download immediately, no modal."""

    captured: list[RomEntry] = []
    def fake_download(entry, progress=True):
        captured.append(entry)
        return tmp_path / "fake.gba"

    stub_lib.download = MagicMock(side_effect=fake_download)

    # FireRed only has one variant in the stub.
    app = BrowseApp(lib=stub_lib, initial_query="firered")
    async with app.run_test() as pilot:
        await pilot.pause()
        assert len(app._results) == 1
        assert len(app._results[0].variants) == 1
        await pilot.press("enter")
        for _ in range(20):
            await pilot.pause()
            if captured:
                break
        assert len(captured) == 1
        assert captured[0].name == "Pokemon - FireRed Version (USA).zip"


async def test_browse_enter_on_multi_variant_group_opens_picker(stub_lib):
    """Group with >1 variants → Enter pushes the VariantPicker modal
    instead of downloading immediately."""
    from retrokix.browse import VariantPicker

    app = BrowseApp(lib=stub_lib, initial_query="emerald")
    async with app.run_test() as pilot:
        await pilot.pause()
        assert len(app._results) == 1
        assert app._results[0].extra_count == 1
        await pilot.press("enter")
        await pilot.pause()
        # Top of the screen stack is the picker.
        assert isinstance(app.screen, VariantPicker)
        assert app.screen.group.title == "Pokemon - Emerald Version"


async def test_picker_enter_dismisses_and_downloads(stub_lib, tmp_path):
    """In the picker, Enter on a variant dismisses the modal and starts
    the download on the chosen variant."""

    captured: list[RomEntry] = []
    def fake_download(entry, progress=True):
        captured.append(entry)
        return tmp_path / "fake.gba"
    stub_lib.download = MagicMock(side_effect=fake_download)

    app = BrowseApp(lib=stub_lib, initial_query="emerald")
    async with app.run_test() as pilot:
        await pilot.pause()
        await pilot.press("enter")  # open picker
        await pilot.pause()
        await pilot.press("down")   # second variant
        await pilot.pause()
        await pilot.press("enter")  # pick it
        for _ in range(30):
            await pilot.pause()
            if captured:
                break
        assert len(captured) == 1
        # Index 1 is the Japan variant (USA is canonical-first).
        assert captured[0].name == "Pokemon - Emerald Version (Japan).zip"


async def test_picker_escape_returns_without_download(stub_lib):
    captured: list[RomEntry] = []
    stub_lib.download = MagicMock(side_effect=lambda e, progress=True: captured.append(e))

    app = BrowseApp(lib=stub_lib, initial_query="emerald")
    async with app.run_test() as pilot:
        await pilot.pause()
        await pilot.press("enter")  # open picker
        await pilot.pause()
        await pilot.press("escape") # back out
        await pilot.pause()
        assert captured == []


async def test_browse_marks_group_as_owned_when_any_variant_present(stub_lib, tmp_path):
    """If any variant of a group is on disk, the group row is marked owned."""

    stub_lib.roms_dir = tmp_path
    (tmp_path / "Pokemon - Emerald Version (Japan).gba").write_bytes(b"")

    app = BrowseApp(lib=stub_lib, initial_query="pokemon")
    async with app.run_test() as pilot:
        await pilot.pause()
        listv = app.query_one("#results")
        rows = [c for c in listv.children if isinstance(c, GroupRow)]
        owned = {r.group.title: r.owned for r in rows}
        # Japan variant only — but the group is still marked owned.
        assert owned["Pokemon - Emerald Version"] is True
        assert owned["Pokemon - FireRed Version"] is False


async def test_browse_escape_clears_query(stub_lib):
    app = BrowseApp(lib=stub_lib, initial_query="emerald")
    async with app.run_test() as pilot:
        await pilot.pause()
        assert app.query_text == "emerald"
        await pilot.press("escape")
        await pilot.pause()
        assert app.query_text == ""
        assert app._results
