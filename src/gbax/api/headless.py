"""Headless play loop — emulator + FastAPI, no SDL window/audio/keyboard.

Used by `gbax play --no-sdl`. A daemon thread steps the runtime at
60 Hz (or 8× when fast_forward is set via the browser TURBO button),
the libretro core's audio callback fans PCM into the AudioBus that
/stream/audio/ws subscribers read from, and the main thread runs
uvicorn until SIGINT.

This is intentionally smaller than render/sdl.py — no plugin
dispatch, no macros, no save-state hotkeys. All those tools work
fine over the HTTP API; you just lose the keyboard surface.
"""

from __future__ import annotations

import threading
import time
import webbrowser

import uvicorn

from gbax.api.server import create_app
from gbax.runtime import EmulatorRuntime


#: Native GBA wall-clock frame rate. The libretro core measures frames
#: per second internally, but the headless loop schedules in real time
#: against this. 1/60 ≈ 16.67 ms per tick.
TARGET_FRAME_RATE = 60
FAST_FORWARD_MULTIPLIER = 8


def run_headless(
    runtime: EmulatorRuntime,
    host: str = "127.0.0.1",
    port: int = 8420,
    open_browser: bool = True,
) -> None:
    """Boot the FastAPI app, the play-loop thread, and (optionally)
    open the controller viewer in the user's default browser.

    Blocks until uvicorn exits (SIGINT/SIGTERM)."""
    app = create_app(runtime)
    bus = app.state.audio_bus

    def _on_audio(buf: bytes) -> None:
        # Mute during fast-forward, same policy as the SDL path: the
        # core emits 8× the samples in wall time, which is chipmunk
        # garbage no matter how we play it back.
        if app.state.fast_forward:
            return
        bus.publish(buf)

    runtime._core.on_audio = _on_audio

    stop_event = threading.Event()

    def _play_loop() -> None:
        target_period = 1.0 / TARGET_FRAME_RATE
        while not stop_event.is_set():
            t0 = time.monotonic()
            n = FAST_FORWARD_MULTIPLIER if app.state.fast_forward else 1
            try:
                runtime.step(frames=n)
            except Exception:
                import traceback
                traceback.print_exc()
                return
            elapsed = time.monotonic() - t0
            slack = target_period - elapsed
            if slack > 0:
                time.sleep(slack)

    play_thread = threading.Thread(
        target=_play_loop, name="gbax-headless-play", daemon=True,
    )
    play_thread.start()

    if open_browser:
        url = f"http://{host}:{port}/stream?mode=controller"
        try:
            webbrowser.open(url, new=2)
        except Exception:
            pass

    try:
        uvicorn.run(app, host=host, port=port, log_level="warning")
    finally:
        stop_event.set()
        runtime._core.on_audio = None
        play_thread.join(timeout=2)
