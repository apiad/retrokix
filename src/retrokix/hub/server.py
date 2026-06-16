"""FastAPI app for the retrokix hub.

The hub has three responsibilities:

  GET /                — landing page (game grid + search).
  GET /api/library     — JSON of owned ROMs grouped/sorted by fame.
  POST /games/launch   — spawn a child play --no-sdl, return its play URL.
  GET /play/{game_id}  — 302 to the child's /stream?mode=controller.

Per-game runtimes live in subprocesses, not in this app. See
`hub/state.py`.
"""

from __future__ import annotations

from dataclasses import dataclass
from pathlib import Path

from fastapi import FastAPI, HTTPException
from fastapi.responses import HTMLResponse, RedirectResponse
from pydantic import BaseModel

from retrokix import __version__
from retrokix.hub.state import HubState
from retrokix.hub.templates import render_landing
from retrokix.library import (
    CONSOLES,
    ALL_ROM_EXTS,
    DEFAULT_ROMS_DIR,
    console_for_path,
    fame_score,
    fame_stars,
    list_local_roms,
    title_key,
)


@dataclass
class LibraryGroup:
    """One title (one or more variants on disk) for the hub grid."""

    title: str
    console: str
    fame: int
    stars: int
    variants: list[Path]  # absolute paths to owned ROMs

    @property
    def primary(self) -> Path:
        return self.variants[0]


def _build_owned_library(roms_dir: Path) -> list[LibraryGroup]:
    """Collapse on-disk ROMs into per-title groups, fame-sorted DESC."""
    groups: dict[tuple[str, str], LibraryGroup] = {}
    for path in list_local_roms(roms_dir):
        console = console_for_path(path) or "gba"
        # `title_key` strips the trailing extension and the region tag.
        key_title = title_key(path.name)
        key = (console, key_title)
        g = groups.get(key)
        if g is None:
            g = LibraryGroup(
                title=key_title,
                console=console,
                fame=fame_score(console, key_title),
                stars=fame_stars(console, key_title),
                variants=[],
            )
            groups[key] = g
        g.variants.append(path)
    return sorted(groups.values(), key=lambda g: (-g.fame, g.title.lower()))


class LaunchRequest(BaseModel):
    rom_path: str


def create_hub_app(
    *,
    host: str = "127.0.0.1",
    roms_dir: Path | None = None,
    hub_state: HubState | None = None,
) -> FastAPI:
    """Build the hub's FastAPI app.

    Pass `hub_state` to inject a test double; otherwise a default
    HubState is constructed bound to `host`.
    """
    roms_dir = Path(roms_dir) if roms_dir else DEFAULT_ROMS_DIR
    state = hub_state or HubState(host=host)

    app = FastAPI(title="retrokix hub", version=__version__)
    app.state.hub = state
    app.state.roms_dir = roms_dir

    @app.get("/", response_class=HTMLResponse)
    def landing() -> HTMLResponse:
        groups = _build_owned_library(roms_dir)
        return HTMLResponse(render_landing(groups, version=__version__))

    @app.get("/api/library")
    def library() -> dict:
        groups = _build_owned_library(roms_dir)
        return {
            "groups": [
                {
                    "title": g.title,
                    "console": g.console,
                    "fame": g.fame,
                    "stars": g.stars,
                    "primary_path": str(g.primary),
                    "variant_count": len(g.variants),
                }
                for g in groups
            ],
            "consoles": {
                slug: {"label": info.label}
                for slug, info in CONSOLES.items()
            },
        }

    @app.post("/games/launch")
    def launch(req: LaunchRequest) -> dict:
        rom = Path(req.rom_path)
        if not rom.exists():
            raise HTTPException(404, f"ROM not found at {rom}")
        if rom.suffix.lower() not in ALL_ROM_EXTS:
            raise HTTPException(400, f"unrecognised ROM extension: {rom.suffix}")
        console = console_for_path(rom)
        gp = state.spawn(rom, console=console)
        return {
            "game_id": gp.game_id,
            "url": f"/play/{gp.game_id}",
            "console": gp.console,
            "rom": rom.name,
        }

    @app.get("/play/{game_id}")
    def play(game_id: str) -> RedirectResponse:
        url = state.play_url(game_id)
        if url is None:
            raise HTTPException(404, f"unknown game_id: {game_id}")
        return RedirectResponse(url, status_code=302)

    @app.get("/api/games")
    def games() -> dict:
        return {
            "games": [
                {
                    "game_id": gp.game_id,
                    "console": gp.console,
                    "rom": gp.rom_path.name,
                    "port": gp.port,
                    "started_at": gp.started_at,
                }
                for gp in state.list()
            ]
        }

    return app
