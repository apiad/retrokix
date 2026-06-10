"""Smoke tests for SDLRenderer extracted from play_loop.

These require a real SDL video driver (no `SDL_VIDEODRIVER=dummy`),
because the renderer creation needs an accelerated backend. Skipped in
CI / headless runs.
"""
from __future__ import annotations

import os

import pytest

pytestmark = pytest.mark.skipif(
    os.environ.get("SDL_VIDEODRIVER") == "dummy",
    reason="SDLRenderer needs a real video driver",
)


def test_sdl_renderer_constructs_and_presents():
    import sdl2
    import sdl2.ext

    from gbax.render.sdl_renderer import SDLRenderer

    sdl2.ext.init()
    try:
        window = sdl2.ext.Window("gbax-test", size=(240 * 2, 160 * 2), flags=sdl2.SDL_WINDOW_RESIZABLE)
        renderer = SDLRenderer()
        renderer.init(window, gba_width=240, gba_height=160)
        renderer.present_frame(bytes(240 * 160 * 3))
        renderer.set_shader("nearest")
        renderer.set_shader("linear")
        renderer.cycle_shader()
        renderer.set_fullscreen(True)
        renderer.set_fullscreen(False)
        renderer.close()
    finally:
        sdl2.ext.quit()


def test_sdl_renderer_rejects_unknown_shader():
    import sdl2
    import sdl2.ext

    from gbax.render.sdl_renderer import SDLRenderer

    sdl2.ext.init()
    try:
        window = sdl2.ext.Window("gbax-test", size=(240, 160))
        renderer = SDLRenderer()
        renderer.init(window, gba_width=240, gba_height=160)
        with pytest.raises(ValueError, match="unknown shader"):
            renderer.set_shader("crt-royale-mega-deluxe")
        renderer.close()
    finally:
        sdl2.ext.quit()
