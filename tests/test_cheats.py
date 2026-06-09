"""Tests for the cheat layer — DB lookup, runtime install, API endpoints."""

from __future__ import annotations

import pytest
from fastapi.testclient import TestClient

from gbax.api.server import create_app
from gbax.cheats import Cheat, _rom_key, cheats_for_rom
from gbax.runtime import EmulatorRuntime


# --- DB lookup ---


def test_rom_key_strips_extension_and_format_suffix():
    # _rom_key takes a ROM filename (.gba / .zip), not a .cht.
    assert _rom_key("Pokemon - Emerald Version (USA, Europe).gba") \
        == "Pokemon - Emerald Version (USA, Europe)"
    assert _rom_key("Pokemon - Emerald Version (USA, Europe).zip") \
        == "Pokemon - Emerald Version (USA, Europe)"
    # If a ROM is named with a "(Code Breaker)" suffix, that also gets stripped
    # so libretro DB entries match the canonical No-Intro name.
    assert _rom_key("Some Game (USA) (Code Breaker).gba") == "Some Game (USA)"


def test_cheats_for_emerald_includes_known_codes():
    catalog = cheats_for_rom("Pokemon - Emerald Version (USA, Europe).gba")
    names = {c.name for c in catalog}
    # These are canonical entries in the libretro DB for Emerald.
    assert "Master Code" in names
    assert "Max Money" in names
    assert "Complete Pokedex" in names


def test_cheats_for_unknown_rom_returns_empty():
    assert cheats_for_rom("Not A Real Game.gba") == []


def test_cheat_slug_is_url_safe():
    c = Cheat(name="No Random Battle!", code="aaaa+bbbb")
    assert c.slug() == "no-random-battle"


# --- runtime (smoke against the test ROM, which has no DB entry) ---


@pytest.fixture
def runtime_emerald(test_rom, mgba_core):
    """A runtime whose ROM happens to have a cheat catalog. We use the bundled
    test.gba ROM but override the catalog manually since libretro-database
    doesn't have an entry for an mGBA cinema test ROM."""
    rt = EmulatorRuntime(test_rom, core_path=mgba_core)
    rt._cheat_catalog = [
        Cheat(name="Foo", code="00000000+0000"),
        Cheat(name="Bar", code="11111111+1111"),
    ]
    yield rt
    rt.close()


def test_enable_disable_cheat(runtime_emerald):
    rt = runtime_emerald
    assert rt.active_cheats() == []
    rt.enable_cheat("foo")
    assert [c.name for c in rt.active_cheats()] == ["Foo"]
    rt.disable_cheat("foo")
    assert rt.active_cheats() == []


def test_toggle_cheat(runtime_emerald):
    rt = runtime_emerald
    _, on = rt.toggle_cheat("foo")
    assert on is True
    _, on = rt.toggle_cheat("foo")
    assert on is False


def test_enable_unknown_raises(runtime_emerald):
    with pytest.raises(KeyError):
        runtime_emerald.enable_cheat("nope")


def test_custom_cheat(runtime_emerald):
    c = runtime_emerald.add_custom_cheat("My Hack", "DEADBEEF+0001")
    assert c.slug() == "my-hack"
    assert [a.slug() for a in runtime_emerald.active_cheats()] == ["my-hack"]


def test_clear_cheats(runtime_emerald):
    runtime_emerald.enable_cheat("foo")
    runtime_emerald.enable_cheat("bar")
    runtime_emerald.clear_cheats()
    assert runtime_emerald.active_cheats() == []


# --- API ---


@pytest.fixture
def api_client(test_rom, mgba_core):
    rt = EmulatorRuntime(test_rom, core_path=mgba_core)
    rt._cheat_catalog = [
        Cheat(name="Walk Through Walls", code="00000000+0000"),
        Cheat(name="Infinite HP", code="11111111+1111"),
    ]
    yield TestClient(create_app(rt)), rt
    rt.close()


def test_get_cheats_lists_catalog(api_client):
    c, _ = api_client
    r = c.get("/cheats")
    assert r.status_code == 200
    catalog = r.json()["catalog"]
    slugs = [x["slug"] for x in catalog]
    assert "walk-through-walls" in slugs
    assert all(x["active"] is False for x in catalog)


def test_enable_then_active(api_client):
    c, _ = api_client
    r = c.post("/cheats/walk-through-walls/enable")
    assert r.status_code == 200
    r = c.get("/cheats/active")
    assert [x["slug"] for x in r.json()["active"]] == ["walk-through-walls"]


def test_disable_unknown_404(api_client):
    c, _ = api_client
    r = c.post("/cheats/no-such-cheat/disable")
    assert r.status_code == 404


def test_custom_cheat_endpoint(api_client):
    c, rt = api_client
    r = c.post("/cheats/custom", json={"name": "My Hack", "code": "DEADBEEF+0001"})
    assert r.status_code == 200
    assert r.json()["slug"] == "my-hack"
    assert any(a.slug() == "my-hack" for a in rt.active_cheats())


def test_delete_clears_all(api_client):
    c, _ = api_client
    c.post("/cheats/walk-through-walls/enable")
    c.post("/cheats/infinite-hp/enable")
    r = c.delete("/cheats")
    assert r.status_code == 200
    assert r.json() == {"active": []}
