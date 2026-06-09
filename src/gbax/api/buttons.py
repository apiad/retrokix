"""/buttons — get held set, replace held set."""

from __future__ import annotations

from fastapi import APIRouter, HTTPException, Request
from pydantic import BaseModel

from gbax.input import button_from_str


class ButtonsBody(BaseModel):
    buttons: list[str]


def build_router() -> APIRouter:
    router = APIRouter()

    @router.get("/buttons")
    def get_buttons(request: Request) -> dict:
        held = request.app.state.runtime.buttons_held()
        return {"buttons": sorted(b.name.lower() for b in held)}

    @router.post("/buttons")
    def set_buttons(body: ButtonsBody, request: Request) -> dict:
        try:
            buttons = {button_from_str(b) for b in body.buttons}
        except ValueError as exc:
            raise HTTPException(400, detail=str(exc)) from exc
        rt = request.app.state.runtime
        rt.set_buttons(buttons)
        return {"buttons": sorted(b.name.lower() for b in buttons)}

    return router
