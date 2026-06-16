"""SDL-based renderer — today's play_loop rendering code, extracted."""
from __future__ import annotations

import sdl2
import sdl2.ext


_AVAILABLE_SHADERS = ["linear", "nearest"]


class SDLRenderer:
    available_shaders: list[str]
    current_shader: str

    def __init__(self) -> None:
        self.available_shaders = list(_AVAILABLE_SHADERS)
        self.current_shader = "linear"
        self._window = None
        self._renderer = None
        self._texture = None
        self._gba_width = 240
        self._gba_height = 160
        self._is_fullscreen = False

    def init(self, sdl_window, gba_width: int, gba_height: int) -> None:
        self._window = sdl_window
        self._gba_width = gba_width
        self._gba_height = gba_height
        sdl2.SDL_SetHint(sdl2.SDL_HINT_RENDER_SCALE_QUALITY, self.current_shader.encode())
        self._renderer = sdl2.ext.Renderer(sdl_window, flags=sdl2.SDL_RENDERER_ACCELERATED)
        sdl2.SDL_RenderSetLogicalSize(self._renderer.sdlrenderer, gba_width, gba_height)
        self._make_texture()

    def _make_texture(self) -> None:
        if self._texture is not None:
            sdl2.SDL_DestroyTexture(self._texture)
        sdl2.SDL_SetHint(sdl2.SDL_HINT_RENDER_SCALE_QUALITY, self.current_shader.encode())
        self._texture = sdl2.SDL_CreateTexture(
            self._renderer.sdlrenderer,
            sdl2.SDL_PIXELFORMAT_RGB24,
            sdl2.SDL_TEXTUREACCESS_STREAMING,
            self._gba_width,
            self._gba_height,
        )

    def present_frame(self, rgb_bytes: bytes) -> None:
        sdl2.SDL_UpdateTexture(self._texture, None, rgb_bytes, self._gba_width * 3)
        self._renderer.clear()
        sdl2.SDL_RenderCopy(self._renderer.sdlrenderer, self._texture, None, None)
        self._renderer.present()

    def set_shader(self, name: str) -> None:
        if name not in self.available_shaders:
            raise ValueError(f"unknown shader: {name!r}; available: {self.available_shaders}")
        if name == self.current_shader:
            return
        self.current_shader = name
        self._make_texture()

    def cycle_shader(self) -> str:
        idx = self.available_shaders.index(self.current_shader)
        new_name = self.available_shaders[(idx + 1) % len(self.available_shaders)]
        self.set_shader(new_name)
        return self.current_shader

    def set_fullscreen(self, fullscreen: bool) -> None:
        self._is_fullscreen = fullscreen
        sdl2.SDL_SetWindowFullscreen(
            self._window.window,
            sdl2.SDL_WINDOW_FULLSCREEN_DESKTOP if fullscreen else 0,
        )

    def close(self) -> None:
        if self._texture is not None:
            sdl2.SDL_DestroyTexture(self._texture)
            self._texture = None
