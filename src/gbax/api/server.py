"""FastAPI app factory. Wires the EmulatorRuntime into the endpoint routers."""

from __future__ import annotations

from fastapi import FastAPI

from gbax import __version__
from gbax.runtime import EmulatorRuntime


def create_app(runtime: EmulatorRuntime) -> FastAPI:
    from gbax.api.action import build_router as build_action_router
    from gbax.api.audio_bus import AudioBus
    from gbax.api.buttons import build_router as build_buttons_router
    from gbax.api.capture_state import build_router as build_capture_state_router
    from gbax.api.cheats import build_router as build_cheats_router
    from gbax.api.control import build_router as build_control_router
    from gbax.api.frame import build_router as build_frame_router
    from gbax.api.memory import build_router as build_memory_router
    from gbax.api.stream import build_router as build_stream_router

    app = FastAPI(title="gbax", version=__version__)
    app.state.runtime = runtime
    # Shared state for /stream + headless coordination. Browser TURBO
    # writes here; SDL play loop and headless loop both read it.
    app.state.fast_forward = False
    # PCM bytes from the libretro core fan out via this bus to any
    # /stream/audio/ws subscribers.
    app.state.audio_bus = AudioBus()
    app.include_router(build_control_router())
    app.include_router(build_frame_router())
    app.include_router(build_buttons_router())
    app.include_router(build_memory_router())
    app.include_router(build_cheats_router())
    app.include_router(build_action_router())
    app.include_router(build_capture_state_router())
    app.include_router(build_stream_router())
    return app
