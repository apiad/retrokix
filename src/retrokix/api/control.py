"""/mode, /step, /speed, /frame_count — control-plane endpoints."""

from __future__ import annotations

from fastapi import APIRouter, HTTPException, Request
from pydantic import BaseModel, Field

from retrokix.runtime import Mode


class ModeBody(BaseModel):
    mode: Mode


class SpeedBody(BaseModel):
    multiplier: float = Field(..., gt=0)


class SettingsPatch(BaseModel):
    """Partial update — every field optional. Unknown keys 422 via
    pydantic. Validated values are pushed through the runtime so any
    side-effects (e.g. speed_multiplier setter) fire alongside the
    persisted write.
    """
    speed_multiplier: float | None = Field(None, gt=0)
    fullscreen: bool | None = None
    window_scale: int | None = Field(None, ge=1, le=10)
    last_slot: int | None = Field(None, ge=1, le=9)


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

    @router.get("/settings")
    def get_settings(request: Request) -> dict:
        rt = request.app.state.runtime
        return rt.settings.to_dict()

    @router.patch("/settings")
    def patch_settings(body: SettingsPatch, request: Request) -> dict:
        rt = request.app.state.runtime
        # Route speed_multiplier through the runtime setter so the
        # ticker picks up the new pace immediately; the setter already
        # persists. Other fields just get persisted directly.
        changes = body.model_dump(exclude_none=True)
        if "speed_multiplier" in changes:
            try:
                rt.speed_multiplier = changes.pop("speed_multiplier")
            except ValueError as exc:
                raise HTTPException(400, detail=str(exc)) from exc
        if changes:
            rt._persist_setting(**changes)
        return rt.settings.to_dict()

    return router
