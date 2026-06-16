"""FastAPI app factory. Wires the EmulatorRuntime into the endpoint routers."""

from __future__ import annotations

import time

from fastapi import FastAPI

from retrokix import __version__
from retrokix.runtime import EmulatorRuntime


def create_app(runtime: EmulatorRuntime) -> FastAPI:
    from retrokix.api.action import build_router as build_action_router
    from retrokix.api.audio_bus import AudioBus
    from retrokix.api.buttons import build_router as build_buttons_router
    from retrokix.api.capture_state import build_router as build_capture_state_router
    from retrokix.api.cheats import build_router as build_cheats_router
    from retrokix.api.control import build_router as build_control_router
    from retrokix.api.frame import build_router as build_frame_router
    from retrokix.api.memory import build_router as build_memory_router
    from retrokix.api.savestate import build_router as build_savestate_router
    from retrokix.api.stream import build_router as build_stream_router

    app = FastAPI(title="retrokix", version=__version__)
    app.state.runtime = runtime
    # Shared state for /stream + headless coordination. Browser TURBO
    # writes here; SDL play loop and headless loop both read it.
    app.state.fast_forward = False
    # PCM bytes from the libretro core fan out via this bus to any
    # /stream/audio/ws subscribers.
    app.state.audio_bus = AudioBus()
    # Tracked by the /stream WS handlers; read by the hub's idle reaper
    # via /healthz to decide when a child has no viewers and can be
    # killed. Plain int — all WS handlers run on the same event loop.
    app.state.ws_clients = 0
    app.state.started_at = time.time()

    @app.get("/healthz")
    def healthz() -> dict:
        return {
            "ws_clients": int(app.state.ws_clients),
            "uptime": time.time() - app.state.started_at,
        }

    app.include_router(build_control_router())
    app.include_router(build_frame_router())
    app.include_router(build_buttons_router())
    app.include_router(build_memory_router())
    app.include_router(build_cheats_router())
    app.include_router(build_action_router())
    app.include_router(build_capture_state_router())
    app.include_router(build_savestate_router())
    app.include_router(build_stream_router())
    return app
