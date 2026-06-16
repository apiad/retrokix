"""/mode, /step, /speed, /frame_count — control-plane endpoints."""

from __future__ import annotations

from fastapi import APIRouter, HTTPException, Request
from pydantic import BaseModel, Field

from retrokix.runtime import Mode


class ModeBody(BaseModel):
    mode: Mode


class SpeedBody(BaseModel):
    multiplier: float = Field(..., gt=0)


def build_router() -> APIRouter:
    router = APIRouter()

    @router.get("/mode")
    def get_mode(request: Request) -> dict:
        return {"mode": request.app.state.runtime.mode.value}

    @router.post("/mode")
    def set_mode(body: ModeBody, request: Request) -> dict:
        rt = request.app.state.runtime
        was_free = rt.mode == Mode.FREE
        rt.mode = body.mode
        if body.mode == Mode.FREE and not was_free:
            rt.start_free_run_ticker()
        elif body.mode == Mode.STEP and was_free:
            rt.stop_free_run_ticker()
        return {"mode": body.mode.value}

    @router.post("/step")
    def step(request: Request, frames: int = 1) -> dict:
        rt = request.app.state.runtime
        if rt.mode == Mode.FREE:
            raise HTTPException(409, detail="cannot /step in free mode; switch to step mode first")
        if frames < 1:
            raise HTTPException(400, detail="frames must be >= 1")
        rt.step(frames=frames)
        return {"frame_count": rt.frame_count}

    @router.get("/frame_count")
    def frame_count(request: Request) -> dict:
        return {"frame_count": request.app.state.runtime.frame_count}

    @router.get("/speed")
    def get_speed(request: Request) -> dict:
        return {"multiplier": request.app.state.runtime.speed_multiplier}

    @router.post("/speed")
    def post_speed(body: SpeedBody, request: Request) -> dict:
        try:
            request.app.state.runtime.speed_multiplier = body.multiplier
        except ValueError as exc:
            raise HTTPException(400, detail=str(exc)) from exc
        return {"multiplier": body.multiplier}

    return router
