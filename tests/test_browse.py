"""Tests for `gbax browse` — pure helpers + a Textual Pilot smoke test."""

from __future__ import annotations

from unittest.mock import MagicMock

import pytest

from gbax.browse import BrowseApp, _fmt_size, _trim_name
from gbax.library import RomEntry, RomLibrary


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


async def test_browse_initial_state_shows_all(stub_lib):
    app = BrowseApp(lib=stub_lib)
    async with app.run_test() as pilot:
        await pilot.pause()
        assert len(app._results) == 5
        # ListView should have all 5 rows mounted
        listv = app.query_one("#results")
        assert len(list(listv.children)) == 5


async def test_browse_filters_as_you_type(stub_lib):
    app = BrowseApp(lib=stub_lib)
    async with app.run_test() as pilot:
        await pilot.press("z", "e", "l", "d", "a")
        await pilot.pause()
        names = [e.name for e in app._results]
        assert names == ["Legend of Zelda, The - The Minish Cap (USA).zip"]


async def test_browse_initial_query_prefills(stub_lib):
    app = BrowseApp(lib=stub_lib, initial_query="emerald")
    async with app.run_test() as pilot:
        await pilot.pause()
        assert {e.name for e in app._results} == {
            "Pokemon - Emerald Version (USA, Europe).zip",
            "Pokemon - Emerald Version (Japan).zip",
        }


async def test_browse_enter_triggers_download_on_selected(stub_lib, tmp_path):
    """Arrow-Down past the first row, then Enter — verify download is called
    with the *selected* entry, not the first one. The download itself is
    stubbed so no network is hit."""

    captured: list[RomEntry] = []

    def fake_download(entry, progress=True):
        captured.append(entry)
        return tmp_path / "fake.gba"

    stub_lib.download = MagicMock(side_effect=fake_download)

    app = BrowseApp(lib=stub_lib, initial_query="pokemon")
    async with app.run_test() as pilot:
        await pilot.pause()
        # Three pokemon entries; arrow-down once → second one selected
        await pilot.press("down")
        await pilot.pause()
        await pilot.press("enter")
        # wait for worker
        for _ in range(20):
            await pilot.pause()
            if captured:
                break
        assert len(captured) == 1
        # the second match — Japan or FireRed depending on stub order
        assert captured[0].name in {
            "Pokemon - Emerald Version (Japan).zip",
            "Pokemon - FireRed Version (USA).zip",
        }


async def test_browse_escape_clears_query(stub_lib):
    app = BrowseApp(lib=stub_lib, initial_query="emerald")
    async with app.run_test() as pilot:
        await pilot.pause()
        assert app.query_text == "emerald"
        await pilot.press("escape")
        await pilot.pause()
        assert app.query_text == ""
        assert len(app._results) == 5
