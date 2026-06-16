"""Renderer Protocol + bundled WGSL shader registry."""
from __future__ import annotations

from pathlib import Path
from typing import Protocol


class Renderer(Protocol):
    available_shaders: list[str]
    current_shader: str

    def init(self, sdl_window, gba_width: int, gba_height: int) -> None: ...

    def present_frame(self, rgb_bytes: bytes) -> None: ...

    def set_shader(self, name: str) -> None: ...

    def cycle_shader(self) -> str: ...

    def set_fullscreen(self, fullscreen: bool) -> None: ...

    def close(self) -> None: ...


def _load_shader(name: str) -> str:
    path = Path(__file__).parent / "shaders" / f"{name}.wgsl"
    if path.exists():
        return path.read_text()
    return ""


SHADERS: dict[str, str] = {}
for _name in ("nearest", "linear", "crt_lottes", "xbrz"):
    _src = _load_shader(_name)
    if _src:
        # Filenames use underscore; registry keys use hyphen.
        key = _name.replace("_", "-")
        SHADERS[key] = _src
