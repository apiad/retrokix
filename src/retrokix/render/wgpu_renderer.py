"""wgpu-based renderer — fullscreen-quad shader pass over the GBA framebuffer.

Lazy-imports wgpu so the module is loadable without the [gpu] extra;
only `__init__` fails when wgpu is missing.
"""
from __future__ import annotations

import struct
from pathlib import Path

import numpy as np


def _require_wgpu():
    import sys

    if sys.modules.get("wgpu", "present") is None:
        raise RuntimeError(
            "--renderer=wgpu requires the [gpu] extra. "
            "Install with: pip install retrokix[gpu]"
        )
    try:
        import wgpu  # noqa: F401
        import rendercanvas  # noqa: F401
    except ImportError as exc:
        raise RuntimeError(
            "--renderer=wgpu requires the [gpu] extra. "
            "Install with: pip install retrokix[gpu]"
        ) from exc


_VERTEX_SHADER = (Path(__file__).parent / "shaders" / "_vertex.wgsl").read_text()


class WGPURenderer:
    available_shaders: list[str]
    current_shader: str

    def __init__(self) -> None:
        _require_wgpu()
        from retrokix.render.base import SHADERS

        candidate = ["linear", "nearest", "crt-lottes", "xbrz"]
        self.available_shaders = [s for s in candidate if s in SHADERS]
        self.current_shader = (
            "linear" if "linear" in self.available_shaders else self.available_shaders[0]
        )
        self._user_shader_src: str | None = None
        self._sdl_window = None
        self._device = None
        self._adapter = None
        self._ctx = None
        self._ctx_format = None
        self._texture = None
        self._pipeline = None
        self._bind_group = None
        self._bind_layout = None
        self._uniform_buf = None
        self._sampler_linear = None
        self._sampler_nearest = None
        self._gba_w = 240
        self._gba_h = 160
        self._frame = 0
        self._is_fullscreen = False

    def init(self, sdl_window, gba_width: int, gba_height: int) -> None:
        import wgpu

        from retrokix.render._wgpu_surface import build_canvas_context

        self._sdl_window = sdl_window
        self._gba_w = gba_width
        self._gba_h = gba_height

        # Try discrete GPU first; fall back to integrated / fallback adapter
        # if device creation fails. Some NVIDIA + Vulkan setups report
        # "Parent device is lost" on first request — the integrated
        # adapter usually works in that case.
        last_err: Exception | None = None
        for kwargs in (
            {"power_preference": "high-performance"},
            {"power_preference": "low-power"},
            {"force_fallback_adapter": True},
        ):
            try:
                self._adapter = wgpu.gpu.request_adapter_sync(**kwargs)
                self._device = self._adapter.request_device_sync()
                last_err = None
                break
            except Exception as exc:
                last_err = exc
                self._adapter = None
                self._device = None
        if self._device is None:
            raise RuntimeError(
                f"wgpu: could not create a device across all adapter strategies; "
                f"last error: {last_err}"
            )
        self._ctx, self._ctx_format = build_canvas_context(self._device, sdl_window)

        self._sampler_nearest = self._device.create_sampler(
            mag_filter="nearest",
            min_filter="nearest",
        )
        self._sampler_linear = self._device.create_sampler(
            mag_filter="linear",
            min_filter="linear",
        )

        self._texture = self._device.create_texture(
            size=(gba_width, gba_height, 1),
            format="rgba8unorm",
            usage=wgpu.TextureUsage.TEXTURE_BINDING | wgpu.TextureUsage.COPY_DST,
        )

        self._uniform_buf = self._device.create_buffer(
            size=32,
            usage=wgpu.BufferUsage.UNIFORM | wgpu.BufferUsage.COPY_DST,
        )

        self._rebuild_pipeline()

    def _current_shader_source(self) -> str:
        if self.current_shader == "user" and self._user_shader_src is not None:
            return self._user_shader_src
        from retrokix.render.base import SHADERS
        return SHADERS[self.current_shader]

    def _rebuild_pipeline(self) -> None:
        import wgpu

        vs_module = self._device.create_shader_module(code=_VERTEX_SHADER)
        fs_module = self._device.create_shader_module(code=self._current_shader_source())

        self._bind_layout = self._device.create_bind_group_layout(entries=[
            {
                "binding": 0,
                "visibility": wgpu.ShaderStage.FRAGMENT,
                "texture": {
                    "sample_type": "float",
                    "view_dimension": "2d",
                },
            },
            {
                "binding": 1,
                "visibility": wgpu.ShaderStage.FRAGMENT,
                "sampler": {"type": "filtering"},
            },
            {
                "binding": 2,
                "visibility": wgpu.ShaderStage.FRAGMENT,
                "buffer": {"type": "uniform"},
            },
        ])
        layout = self._device.create_pipeline_layout(bind_group_layouts=[self._bind_layout])

        sampler = self._sampler_nearest if self.current_shader == "nearest" else self._sampler_linear

        self._pipeline = self._device.create_render_pipeline(
            layout=layout,
            vertex={"module": vs_module, "entry_point": "vs_main"},
            primitive={"topology": "triangle-list"},
            fragment={
                "module": fs_module,
                "entry_point": "fs_main",
                "targets": [{"format": self._ctx_format}],
            },
        )

        self._bind_group = self._device.create_bind_group(
            layout=self._bind_layout,
            entries=[
                {"binding": 0, "resource": self._texture.create_view()},
                {"binding": 1, "resource": sampler},
                {"binding": 2, "resource": {"buffer": self._uniform_buf, "offset": 0, "size": 32}},
            ],
        )

    def present_frame(self, rgb_bytes: bytes) -> None:
        # Convert RGB → RGBA.
        arr = np.frombuffer(rgb_bytes, dtype=np.uint8).reshape(self._gba_h, self._gba_w, 3)
        rgba = np.dstack([arr, np.full((self._gba_h, self._gba_w), 255, dtype=np.uint8)])
        rgba_bytes = rgba.tobytes()

        self._device.queue.write_texture(
            {"texture": self._texture, "mip_level": 0, "origin": (0, 0, 0)},
            rgba_bytes,
            {"offset": 0, "bytes_per_row": self._gba_w * 4, "rows_per_image": self._gba_h},
            (self._gba_w, self._gba_h, 1),
        )

        # Pull current swapchain texture (size depends on the configured surface).
        current_texture = self._ctx.get_current_texture()
        out_w = current_texture.size[0]
        out_h = current_texture.size[1]

        # Pack uniforms: output_res(2) + source_res(2) + frame + pad → 6 floats + 2 pad bytes = 32 bytes.
        u_bytes = struct.pack(
            "<6f8x",
            float(out_w), float(out_h),
            float(self._gba_w), float(self._gba_h),
            float(self._frame), 0.0,
        )
        self._device.queue.write_buffer(self._uniform_buf, 0, u_bytes)

        encoder = self._device.create_command_encoder()
        view = current_texture.create_view()
        rp = encoder.begin_render_pass(color_attachments=[{
            "view": view,
            "resolve_target": None,
            "clear_value": (0.0, 0.0, 0.0, 1.0),
            "load_op": "clear",
            "store_op": "store",
        }])
        rp.set_pipeline(self._pipeline)
        rp.set_bind_group(0, self._bind_group)
        rp.draw(3)
        rp.end()
        self._device.queue.submit([encoder.finish()])
        self._ctx.present()
        self._frame += 1

    def set_shader(self, name: str) -> None:
        valid = list(self.available_shaders)
        if self._user_shader_src is not None:
            valid.append("user")
        if name not in valid:
            raise ValueError(f"unknown shader: {name!r}; available: {valid}")
        if name == self.current_shader:
            return
        prev = self.current_shader
        self.current_shader = name
        try:
            self._rebuild_pipeline()
        except Exception as exc:
            print(f"warning: shader {name!r} failed to compile: {exc}; falling back to {prev!r}")
            self.current_shader = prev
            self._rebuild_pipeline()

    def cycle_shader(self) -> str:
        seq = list(self.available_shaders)
        if self._user_shader_src is not None:
            seq.append("user")
        if not seq:
            return self.current_shader
        idx = seq.index(self.current_shader) if self.current_shader in seq else -1
        new_name = seq[(idx + 1) % len(seq)]
        self.set_shader(new_name)
        return self.current_shader

    def set_fullscreen(self, fullscreen: bool) -> None:
        import sdl2
        self._is_fullscreen = fullscreen
        sdl2.SDL_SetWindowFullscreen(
            self._sdl_window.window,
            sdl2.SDL_WINDOW_FULLSCREEN_DESKTOP if fullscreen else 0,
        )

    def load_user_shader(self, path) -> None:
        src = Path(path).read_text()
        self._user_shader_src = src
        if "user" not in self.available_shaders:
            self.available_shaders.append("user")
        self.set_shader("user")

    def close(self) -> None:
        self._ctx = None
        self._device = None
        self._adapter = None
        self._texture = None
        self._pipeline = None
        self._bind_group = None
        self._uniform_buf = None
