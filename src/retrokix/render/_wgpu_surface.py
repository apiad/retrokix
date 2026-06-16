"""SDL window → wgpu canvas-context adapter.

Extracts the platform-native window handle from an SDL window and builds
the ``present_info`` dict that ``wgpu.gpu.get_canvas_context`` accepts.
Linux X11 + Wayland supported; Windows / macOS deferred.
"""
from __future__ import annotations

import sys


def build_canvas_context(device, sdl_window):
    """Return (canvas_context, preferred_format).

    The canvas_context is configured for the device; call
    `ctx.get_current_texture()` each frame to obtain the next swapchain
    texture, render to it, then `ctx.present()` to publish.
    """
    import sdl2
    import wgpu

    info = sdl2.SDL_SysWMinfo()
    sdl2.SDL_VERSION(info.version)
    if sdl2.SDL_GetWindowWMInfo(sdl_window.window, info) == 0:
        raise RuntimeError("SDL_GetWindowWMInfo failed")

    if info.subsystem == sdl2.SDL_SYSWM_X11:
        present_info = {
            "method": "screen",
            "platform": "x11",
            "window": int(info.info.x11.window),
            "display": int(info.info.x11.display),
        }
    elif info.subsystem == sdl2.SDL_SYSWM_WAYLAND:
        present_info = {
            "method": "screen",
            "platform": "wayland",
            "window": int(info.info.wl.surface),
            "display": int(info.info.wl.display),
        }
    elif sys.platform == "win32" and info.subsystem == sdl2.SDL_SYSWM_WINDOWS:
        present_info = {
            "method": "screen",
            "platform": "windows",
            "window": int(info.info.win.window),
        }
    else:
        raise RuntimeError(
            f"wgpu renderer doesn't support SDL subsystem {info.subsystem}"
        )

    ctx = wgpu.gpu.get_canvas_context(present_info)

    # Tell the context the current window pixel dimensions so
    # get_current_texture can allocate the right size.
    w = sdl2.c_int()
    h = sdl2.c_int()
    sdl2.SDL_GetWindowSizeInPixels(sdl_window.window, w, h)
    ctx.set_physical_size(w.value, h.value)

    preferred_format = ctx.get_preferred_format(device.adapter)
    ctx.configure(
        device=device,
        format=preferred_format,
        alpha_mode="opaque",
    )
    return ctx, preferred_format
