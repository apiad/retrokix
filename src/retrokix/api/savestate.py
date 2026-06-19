"""/savestate — list, save (running), load (running by name or
numbered slot), load_latest.

Mirrors the SDL hotkeys for the browser:

  POST /savestate/save           → like Ctrl+S in the SDL window
  POST /savestate/load_latest    → like Ctrl+L
  POST /savestate/load           → like Shift+N or `--load`
  GET  /savestate/list           → enumerate everything on disk

Paths from the client are never trusted: `running` is matched by
*filename only* against the running directory, and `slot` is an
integer 1..9. The hand-rolled `retrokix play --load <path>` keeps
arbitrary paths for CLI use.
"""

from __future__ import annotations

from datetime import datetime, timezone

from fastapi import APIRouter, HTTPException, Request, Response
from pydantic import BaseModel


class LoadBody(BaseModel):
    slot: int | None = None
    #: Filename within ~/.retrokix/saves/<sha1>/running/. Path components
    #: are rejected — clients can't traverse out of the running dir.
    running: str | None = None


def _ts_iso(mtime: float) -> str:
    return datetime.fromtimestamp(mtime, tz=timezone.utc).isoformat(timespec="seconds")


def build_router() -> APIRouter:
    router = APIRouter()

    @router.get("/savestate/list")
    def list_states(request: Request) -> dict:
        """Enumerate every save on disk for the running ROM:
          - slots: 1..9 numbered save points
          - running: append-only running stream, newest first
        """
        rt = request.app.state.runtime

        slots: list[dict] = []
        for n in range(1, 10):
            path = rt._slot_path(n)
            if path.exists():
                st = path.stat()
                entry = {
                    "slot": n,
                    "size": st.st_size,
                    "mtime": _ts_iso(st.st_mtime),
                }
                if path.with_suffix(".png").exists():
                    entry["thumb"] = f"/savestate/thumb?slot={n}"
                slots.append(entry)

        running: list[dict] = []
        running_dir = rt._running_dir()
        if running_dir.exists():
            for path in sorted(running_dir.glob("running-*.state"), reverse=True):
                st = path.stat()
                entry = {
                    "name": path.name,
                    "size": st.st_size,
                    "mtime": _ts_iso(st.st_mtime),
                }
                if path.with_suffix(".png").exists():
                    entry["thumb"] = f"/savestate/thumb?running={path.name}"
                running.append(entry)

        return {"slots": slots, "running": running}

    @router.get("/savestate/thumb")
    def get_thumb(request: Request, slot: int | None = None, running: str | None = None) -> Response:
        """Return the PNG screenshot captured at save time.

        Accepts either `slot=N` or `running=<filename>`; filename matched
        against the running directory only (no path traversal). 404 when
        the sidecar is missing — the UI hides the <img> in that case.
        """
        rt = request.app.state.runtime

        if slot is not None:
            if not 1 <= slot <= 9:
                raise HTTPException(400, detail="slot must be 1..9")
            png_path = rt._slot_path(slot).with_suffix(".png")
        elif running:
            name = running
            if "/" in name or "\\" in name or ".." in name or name.startswith("."):
                raise HTTPException(400, detail="invalid running save name")
            png_path = (rt._running_dir() / name).with_suffix(".png")
        else:
            raise HTTPException(400, detail="provide either `slot` or `running`")

        if not png_path.exists() or not png_path.is_file():
            raise HTTPException(404, detail="no thumbnail")
        return Response(content=png_path.read_bytes(), media_type="image/png")

    @router.post("/savestate/save")
    def save_running(request: Request) -> dict:
        """Append a new running save (Ctrl+S equivalent)."""
        rt = request.app.state.runtime
        path = rt.save_state_running()
        st = path.stat()
        return {
            "name": path.name,
            "size": st.st_size,
            "mtime": _ts_iso(st.st_mtime),
        }

    @router.post("/savestate/load_latest")
    def load_latest(request: Request) -> dict:
        """Load the newest running save (Ctrl+L equivalent)."""
        rt = request.app.state.runtime
        latest = rt.latest_running_save()
        if latest is None:
            raise HTTPException(404, detail="no running saves yet")
        rt.load_state_from_file(latest)
        return {"loaded": latest.name}

    @router.post("/savestate/load")
    def load_state(body: LoadBody, request: Request) -> dict:
        """Load a specific save — either `{"slot": N}` or
        `{"running": "<filename>"}`. The filename is matched against
        the running directory only; path traversal is rejected."""
        rt = request.app.state.runtime

        if body.slot is not None:
            if not 1 <= body.slot <= 9:
                raise HTTPException(400, detail="slot must be 1..9")
            try:
                rt.load_state_from_slot(body.slot)
            except KeyError as exc:
                raise HTTPException(404, detail=str(exc)) from exc
            return {"loaded": f"slot-{body.slot}"}

        if body.running:
            name = body.running
            # Filename only. No traversal, no nested dirs.
            if "/" in name or "\\" in name or ".." in name or name.startswith("."):
                raise HTTPException(400, detail="invalid running save name")
            path = rt._running_dir() / name
            if not path.exists() or not path.is_file():
                raise HTTPException(404, detail=f"no save at {name!r}")
            try:
                rt.load_state_from_file(path)
            except (OSError, RuntimeError) as exc:
                raise HTTPException(500, detail=str(exc)) from exc
            return {"loaded": name}

        raise HTTPException(400, detail="provide either `slot` or `running`")

    return router
