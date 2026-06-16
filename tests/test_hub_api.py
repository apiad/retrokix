"""Smoke tests for the hub FastAPI app.

Uses a HubState with a fake spawner so no real subprocess is launched.
The endpoints' wiring (route paths, status codes, redirect target,
landing HTML structure) is what we verify here.
"""

from __future__ import annotations

from pathlib import Path

import pytest
from fastapi.testclient import TestClient

from retrokix.hub.server import create_hub_app
from retrokix.hub.state import HubState


@pytest.fixture
def fake_hub(fake_process_cls) -> HubState:
    def spawner(cmd):
        return fake_process_cls()
    return HubState(host="127.0.0.1", spawner=spawner)


@pytest.fixture
def roms_dir(tmp_path: Path) -> Path:
    d = tmp_path / "roms"
    d.mkdir()
    # Two ROMs across two consoles
    (d / "Pokemon - Emerald Version (USA, Europe).gba").write_bytes(b"\x00" * 16)
    (d / "Super Mario Bros. (World).nes").write_bytes(b"\x00" * 16)
    return d


@pytest.fixture
def client(fake_hub: HubState, roms_dir: Path) -> TestClient:
    app = create_hub_app(host="127.0.0.1", roms_dir=roms_dir, hub_state=fake_hub)
    return TestClient(app)


def test_landing_returns_html_with_owned_roms(client: TestClient):
    r = client.get("/")
    assert r.status_code == 200
    assert "text/html" in r.headers["content-type"]
    body = r.text
    # Both owned ROMs surface as clickable tiles
    assert "Pokemon - Emerald Version" in body
    assert "Super Mario Bros." in body
    # Console chips
    assert "[GBA]" in body
    assert "[NES]" in body


def test_landing_uses_stream_visual_language(client: TestClient):
    """Same palette/typography as /stream so the hub feels coherent."""
    body = client.get("/").text
    # Palette tokens
    assert "--bg: #0b0a14" in body
    assert "--accent: #a78bfa" in body
    # Typography
    assert "JetBrains+Mono" in body
    assert "Press+Start+2P" in body
    # HUB badge + search bar
    assert "badge" in body and "HUB" in body
    assert 'id="search"' in body


def test_landing_groups_by_console_with_full_label(client: TestClient):
    body = client.get("/").text
    # Sectioned: every owned console gets its own console-section
    assert 'data-console="gba"' in body
    assert 'data-console="nes"' in body
    # Full label in the header alongside the chip
    assert "Game Boy Advance" in body
    assert "Nintendo Entertainment System" in body


def test_landing_empty_library_shows_friendly_message(tmp_path: Path, fake_hub: HubState):
    empty = tmp_path / "empty"
    empty.mkdir()
    app = create_hub_app(host="127.0.0.1", roms_dir=empty, hub_state=fake_hub)
    client = TestClient(app)
    r = client.get("/")
    assert r.status_code == 200
    assert "No ROMs" in r.text


def test_library_api_returns_grouped_entries(client: TestClient):
    r = client.get("/api/library")
    assert r.status_code == 200
    data = r.json()
    assert "groups" in data
    assert "consoles" in data
    titles = {g["title"] for g in data["groups"]}
    assert any("Pokemon - Emerald" in t for t in titles)
    assert any("Super Mario Bros." in t for t in titles)
    # Console metadata is present
    assert "gba" in data["consoles"]
    assert data["consoles"]["gba"]["label"] == "Game Boy Advance"


def test_launch_owned_rom_spawns_and_returns_url(client: TestClient, roms_dir: Path):
    rom = roms_dir / "Pokemon - Emerald Version (USA, Europe).gba"
    r = client.post("/games/launch", json={"rom_path": str(rom)})
    assert r.status_code == 200
    data = r.json()
    assert data["game_id"].startswith("g")
    assert data["url"] == f"/play/{data['game_id']}"
    assert data["console"] == "gba"
    assert data["rom"] == rom.name


def test_launch_missing_rom_returns_404(client: TestClient):
    r = client.post("/games/launch", json={"rom_path": "/no/such/file.gba"})
    assert r.status_code == 404


def test_launch_bad_extension_returns_400(client: TestClient, tmp_path: Path):
    junk = tmp_path / "readme.txt"
    junk.write_text("not a rom")
    r = client.post("/games/launch", json={"rom_path": str(junk)})
    assert r.status_code == 400


def test_play_redirects_to_child_stream(client: TestClient, roms_dir: Path):
    rom = roms_dir / "Pokemon - Emerald Version (USA, Europe).gba"
    launch = client.post("/games/launch", json={"rom_path": str(rom)}).json()
    game_id = launch["game_id"]

    r = client.get(f"/play/{game_id}", follow_redirects=False)
    assert r.status_code == 302
    loc = r.headers["location"]
    assert loc.startswith("http://127.0.0.1:")
    assert loc.endswith("/stream?mode=controller")


def test_play_unknown_id_returns_404(client: TestClient):
    r = client.get("/play/g9999", follow_redirects=False)
    assert r.status_code == 404


def test_games_api_lists_active_children(client: TestClient, roms_dir: Path):
    rom = roms_dir / "Pokemon - Emerald Version (USA, Europe).gba"
    client.post("/games/launch", json={"rom_path": str(rom)})
    client.post("/games/launch", json={"rom_path": str(rom)})

    r = client.get("/api/games")
    assert r.status_code == 200
    games = r.json()["games"]
    assert len(games) == 2
    assert {g["console"] for g in games} == {"gba"}
