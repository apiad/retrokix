"""Tests for WGPURenderer — gated on the [gpu] extra being installed."""
from __future__ import annotations

import os

import pytest

os.environ.setdefault("SDL_VIDEODRIVER", "dummy")

try:
    import wgpu  # noqa: F401
    _HAS_WGPU = True
except ImportError:
    _HAS_WGPU = False


def test_import_error_when_wgpu_missing(monkeypatch):
    import sys
    # Hide wgpu — set to None which `_require_wgpu` detects as "missing".
    monkeypatch.setitem(sys.modules, "wgpu", None)
    from retrokix.render.wgpu_renderer import WGPURenderer
    with pytest.raises(RuntimeError, match=r"\[gpu\]"):
        WGPURenderer()


@pytest.mark.skipif(not _HAS_WGPU, reason="retrokix[gpu] not installed")
@pytest.mark.skipif(
    os.environ.get("SDL_VIDEODRIVER") == "dummy",
    reason="wgpu surface needs a real video driver",
)
def test_wgpu_renderer_present_smoke():
    import sdl2
    import sdl2.ext

    from retrokix.render.wgpu_renderer import WGPURenderer

    sdl2.ext.init()
    try:
        window = sdl2.ext.Window("retrokix-wgpu", size=(480, 320))
        window.show()
        try:
            renderer = WGPURenderer()
            renderer.init(window, gba_width=240, gba_height=160)
        except Exception as exc:
            pytest.skip(f"wgpu surface unavailable: {exc}")
        renderer.present_frame(bytes(240 * 160 * 3))
        renderer.set_shader("nearest")
        renderer.set_shader("linear")
        renderer.set_shader("crt-lottes")
        renderer.close()
    finally:
        sdl2.ext.quit()
