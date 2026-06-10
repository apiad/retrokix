# Shaders (GPU renderer)

For CRT scanlines, custom WGSL shaders, and a GPU-accelerated pixel
pipeline, gbax ships an optional wgpu-based renderer:

```
pip install gbax[gpu]
gbax play emerald --renderer=wgpu --shader=crt-lottes
```

The default SDL renderer (which works without `gbax[gpu]`) supports
`linear` and `nearest` filters via SDL's built-in hardware-accelerated
upscale. The wgpu renderer adds custom WGSL shaders on top.

## Bundled shaders

| Name | What it does | Renderer |
|---|---|---|
| `linear` (default) | bilinear smooth upscale | SDL + wgpu |
| `nearest` | chunky retro pixels | SDL + wgpu |
| `crt-lottes` | single-pass CRT (scanlines + RGB phosphor mask) | wgpu only |

Press **F10** in-game to cycle through the available shaders for the
current renderer.

## Custom WGSL shaders

```
gbax play emerald --renderer=wgpu --user-shader ~/my_shader.wgsl
```

Your shader must implement `fs_main` against the same bind group
layout the bundled shaders use:

- binding 0: source texture (240×160 RGBA, the GBA framebuffer)
- binding 1: sampler
- binding 2: uniforms struct (output_res, source_res, frame counter)

Copy `gbax/render/shaders/linear.wgsl` from the installed package as
a starting point — it's the simplest valid implementation.

## Runtime knobs

- `--renderer={sdl,wgpu}` (default `sdl`)
- `--shader <name>` initial shader (default `linear`)
- `--user-shader <path.wgsl>` registers a custom shader as `user`
- **F10** cycles shaders at runtime
- **F11** toggles borderless-desktop fullscreen
- **F12** screenshot to `~/.gbax/screenshots/`

## Caveats

- **Wayland hosts**: gbax auto-sets `SDL_VIDEODRIVER=wayland` when
  `--renderer=wgpu` is active. The X11/XWayland path leaks swapchain
  textures under Mesa Vulkan and OOM-kills within seconds. Override
  by setting `SDL_VIDEODRIVER` yourself if you need to.
- **NVIDIA Vulkan**: some dual-GPU setups fail device creation with
  "Parent device is lost" on the discrete adapter. gbax has an
  adapter fallback chain (`high-performance` → `low-power` →
  `force_fallback_adapter`) that usually finds a working adapter.
- **CRT-Lottes tuning**: the bundled single-pass port has rough
  defaults. Custom WGSL via `--user-shader` is the escape hatch.

## What's deferred

- Multi-pass CRT shaders (CRT-Royale-style)
- xBRZ / hqx pixel-art upscalers
- Shader hot-reload on file change
- In-game parameter UI

## See also

- [installing.md](installing.md) — the `[gpu]` extra
- [cli.md](cli.md) — full flag list for `gbax play`
