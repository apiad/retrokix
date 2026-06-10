"""/capture_state — equivalent of the in-game Ctrl+F hotkey over HTTP.

POST a labels dict; the server runs a 30-frame stability capture (during
which it holds the runtime lock so the SDL loop pauses) and writes the
.dump + .labels.json to the ROM's captures directory.

Lets an agent participate in the state-tracker iteration loop without
the human alt-tabbing to the terminal for every capture.
"""
from __future__ import annotations

from datetime import datetime, timezone
from typing import Any

from fastapi import APIRouter, HTTPException, Request
from pydantic import BaseModel


class _CaptureBody(BaseModel):
    labels: dict[str, Any]
    n_frames: int = 30


def build_router() -> APIRouter:
    router = APIRouter()

    @router.post("/capture_state")
    def post_capture_state(body: _CaptureBody, request: Request) -> dict:
        runtime = request.app.state.runtime

        from gbax.state.capture import save_capture, sparse_capture

        if body.n_frames < 1 or body.n_frames > 240:
            raise HTTPException(status_code=400, detail="n_frames must be 1..240")
        if not body.labels:
            raise HTTPException(status_code=400, detail="labels must be non-empty")

        with runtime._lock:
            sparse = sparse_capture(runtime, n_frames=body.n_frames)
            framebuffer = runtime.framebuffer()
            ts = datetime.now(timezone.utc)
            path = save_capture(
                runtime.rom_sha1, sparse, body.labels, ts,
                framebuffer=framebuffer,
            )

        return {
            "path": str(path),
            "stable_bytes": len(sparse),
            "n_frames": body.n_frames,
            "labels": body.labels,
            "captured_at": ts.isoformat(),
        }

    return router
