"""FastAPI app factory. Wires the EmulatorRuntime into the endpoint routers."""

from __future__ import annotations

from fastapi import FastAPI

from gbax import __version__
from gbax.runtime import EmulatorRuntime


def create_app(runtime: EmulatorRuntime) -> FastAPI:
    from gbax.api.action import build_router as build_action_router
    from gbax.api.buttons import build_router as build_buttons_router
    from gbax.api.cheats import build_router as build_cheats_router
    from gbax.api.control import build_router as build_control_router
    from gbax.api.frame import build_router as build_frame_router
    from gbax.api.memory import build_router as build_memory_router

    app = FastAPI(title="gbax", version=__version__)
    app.state.runtime = runtime
    app.include_router(build_control_router())
    app.include_router(build_frame_router())
    app.include_router(build_buttons_router())
    app.include_router(build_memory_router())
    app.include_router(build_cheats_router())
    app.include_router(build_action_router())
    return app
