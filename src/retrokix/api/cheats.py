"""/cheats — list, enable, disable, custom inject."""

from __future__ import annotations

from fastapi import APIRouter, HTTPException, Request
from pydantic import BaseModel


class CustomCheatBody(BaseModel):
    name: str
    code: str


def build_router() -> APIRouter:
    router = APIRouter()

    @router.get("/cheats")
    def get_cheats(request: Request) -> dict:
        rt = request.app.state.runtime
        active = {c.slug() for c in rt.active_cheats()}
        return {
            "catalog": [
                {"slug": c.slug(), "name": c.name, "code": c.code, "active": c.slug() in active}
                for c in rt.list_cheats()
            ]
        }

    @router.get("/cheats/active")
    def get_active(request: Request) -> dict:
        rt = request.app.state.runtime
        return {
            "active": [
                {"slug": c.slug(), "name": c.name, "code": c.code}
                for c in rt.active_cheats()
            ]
        }

    @router.post("/cheats/{slug}/enable")
    def post_enable(slug: str, request: Request) -> dict:
        rt = request.app.state.runtime
        try:
            c = rt.enable_cheat(slug)
        except KeyError as exc:
            raise HTTPException(404, detail=str(exc)) from exc
        return {"slug": c.slug(), "name": c.name, "active": True}

    @router.post("/cheats/{slug}/disable")
    def post_disable(slug: str, request: Request) -> dict:
        rt = request.app.state.runtime
        try:
            c = rt.disable_cheat(slug)
        except KeyError as exc:
            raise HTTPException(404, detail=str(exc)) from exc
        return {"slug": c.slug(), "name": c.name, "active": False}

    @router.post("/cheats/custom")
    def post_custom(body: CustomCheatBody, request: Request) -> dict:
        rt = request.app.state.runtime
        c = rt.add_custom_cheat(body.name, body.code)
        return {"slug": c.slug(), "name": c.name, "code": c.code, "active": True}

    @router.delete("/cheats")
    def clear(request: Request) -> dict:
        rt = request.app.state.runtime
        rt.clear_cheats()
        return {"active": []}

    return router
