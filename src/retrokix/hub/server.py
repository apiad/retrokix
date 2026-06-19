"""FastAPI app for the retrokix hub.

The hub has these responsibilities:

  GET  /                          — landing page (game grid + search).
  GET  /api/library               — JSON: owned + top-N unowned per console.
  GET  /api/games                 — JSON: currently-spawned children.
  POST /games/launch              — spawn child for an owned ROM, return URL.
  POST /games/download            — start download job for an unowned ROM.
  GET  /downloads/{id}/events     — SSE stream of progress + ready/failed.
  GET  /play/{game_id}            — 302 to the child's /stream?mode=controller.

Per-game runtimes live in subprocesses, not in this app. See
`hub/state.py`.
"""

from __future__ import annotations

import json
from pathlib import Path

from fastapi import FastAPI, HTTPException
from fastapi.responses import FileResponse, HTMLResponse, RedirectResponse, StreamingResponse
from pydantic import BaseModel

from retrokix import __version__
from retrokix.hub.downloads import DownloadManager
from retrokix.hub.library_view import (
    SEARCH_LIMIT,
    HubGroup,
    build_library_view,
    search_library,
    warm_search_index,
)
from retrokix.hub.state import HubState
from retrokix.hub.templates import render_landing, render_search_fragment
from retrokix.library import (
    ALL_ROM_EXTS,
    CONSOLES,
    DEFAULT_ROMS_DIR,
    console_for_path,
)


class LaunchRequest(BaseModel):
    rom_path: str


class DownloadRequest(BaseModel):
    rom_name: str
    console: str


def _serialize_group(g: HubGroup) -> dict:
    return {
        "title": g.title,
        "console": g.console,
        "fame": g.fame,
        "stars": g.stars,
        "owned": g.owned,
        "primary_path": str(g.primary_path) if g.primary_path else None,
        "archive_name": g.archive_name,
        "variant_count": g.variant_count,
    }


def create_hub_app(
    *,
    host: str = "127.0.0.1",
    roms_dir: Path | None = None,
    hub_state: HubState | None = None,
    download_manager: DownloadManager | None = None,
) -> FastAPI:
    """Build the hub's FastAPI app.

    Pass `hub_state` and/or `download_manager` to inject test doubles;
    otherwise defaults bound to `host` + `roms_dir` are constructed.
    """
    roms_dir = Path(roms_dir) if roms_dir else DEFAULT_ROMS_DIR
    state = hub_state or HubState(host=host)
    downloads = download_manager or DownloadManager(hub=state, roms_dir=roms_dir)

    app = FastAPI(title="retrokix hub", version=__version__)
    app.state.hub = state
    app.state.downloads = downloads
    app.state.roms_dir = roms_dir
    # Build the cross-console title index now so the first /api/search
    # keystroke doesn't pay the JSON-parse cost.
    warm_search_index()

    @app.get("/", response_class=HTMLResponse)
    def landing() -> HTMLResponse:
        groups = build_library_view(roms_dir)
        return HTMLResponse(render_landing(groups, version=__version__))

    @app.get("/api/search")
    def search(q: str = "", limit: int = SEARCH_LIMIT) -> dict:
        groups = search_library(q, roms_dir, limit=limit)
        return {
            "query": q,
            "limit": limit,
            "count": len(groups),
            "groups": [_serialize_group(g) for g in groups],
        }

    @app.get("/api/search.html", response_class=HTMLResponse)
    def search_html(q: str = "", limit: int = SEARCH_LIMIT) -> HTMLResponse:
        groups = search_library(q, roms_dir, limit=limit)
        return HTMLResponse(render_search_fragment(groups, query=q))

    @app.get("/api/library")
    def library() -> dict:
        groups = build_library_view(roms_dir)
        return {
            "groups": [_serialize_group(g) for g in groups],
            "consoles": {
                slug: {"label": info.label}
                for slug, info in CONSOLES.items()
            },
        }

    @app.get("/art")
    def art(path: str, kind: str = "snap"):
        """Serve cached libretro-thumbnails art for a downloaded ROM.

        `path` must point inside `roms_dir`; `kind` is snap|boxart|title.
        404 when no art is cached (either upstream had nothing or we
        haven't fetched yet).
        """
        from retrokix.art import KINDS, art_path_if_present
        if kind not in KINDS:
            raise HTTPException(400, f"kind must be one of {KINDS}")
        rom = Path(path).resolve()
        roms_root = roms_dir.resolve()
        try:
            rom.relative_to(roms_root)
        except ValueError as exc:
            raise HTTPException(400, "path must live inside roms_dir") from exc
        art_path = art_path_if_present(rom, kind)
        if art_path is None:
            raise HTTPException(404, "no art cached")
        return FileResponse(art_path, media_type="image/png")

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

    @app.post("/games/download")
    def download(req: DownloadRequest) -> dict:
        if req.console not in CONSOLES:
            raise HTTPException(400, f"unknown console: {req.console!r}")
        job = downloads.start(req.rom_name, req.console)
        return {
            "job_id": job.job_id,
            "events_url": f"/downloads/{job.job_id}/events",
        }

    @app.get("/downloads/{job_id}/events")
    def download_events(job_id: str):
        job = downloads.get(job_id)
        if job is None:
            raise HTTPException(404, f"unknown job: {job_id}")

        def stream():
            for ev in downloads.events(job_id):
                yield f"data: {json.dumps(ev)}\n\n"

        return StreamingResponse(stream(), media_type="text/event-stream", headers={
            "Cache-Control": "no-cache",
            "X-Accel-Buffering": "no",
        })

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
