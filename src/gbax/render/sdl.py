"""SDL window for `gbax play`.

Single event-loop client of EmulatorRuntime:
  - blits the framebuffer to a window at fixed-factor upscale
  - emits audio samples to an SDL audio device
  - keyboard → GBA buttons
  - hotkeys for save state slots 1-9, fast-forward (LShift), screenshot (F12)
  - persistence with Ctrl+S
"""

from __future__ import annotations

import time
from pathlib import Path
from typing import Optional

import numpy as np
import sdl2
import sdl2.ext

from gbax.input import Button
from gbax.libretro import GBA_HEIGHT, GBA_WIDTH
from gbax.runtime import EmulatorRuntime


DEFAULT_SCALE = 3
TARGET_FRAME_TIME = 1.0 / 60.0
FAST_FORWARD_MULTIPLIER = 8
AUDIO_SAMPLE_RATE = 32768  # libretro tells us — mGBA uses 32768 by default


def default_keymap() -> dict[int, Button]:
    """SDL keycode → GBA button. Matches the spec defaults."""
    return {
        sdl2.SDLK_x:      Button.A,
        sdl2.SDLK_z:      Button.B,
        sdl2.SDLK_a:      Button.L,
        sdl2.SDLK_s:      Button.R,
        sdl2.SDLK_RETURN: Button.START,
        sdl2.SDLK_RSHIFT: Button.SELECT,
        sdl2.SDLK_UP:     Button.UP,
        sdl2.SDLK_DOWN:   Button.DOWN,
        sdl2.SDLK_LEFT:   Button.LEFT,
        sdl2.SDLK_RIGHT:  Button.RIGHT,
    }


def _load_macro_for_slot(rom_sha1: str, slot: str):
    """Return the Macro for this ROM+slot, or None. Local import to avoid cycles."""
    from gbax.macros import load
    return load(rom_sha1, slot)


# Bare-key hotkeys reserved by the play loop. Any slot in this set is
# refused at macro-bind time so the user can't clobber a play-loop hotkey.
RESERVED_HOTKEYS: dict[str, str] = {
    "LSHIFT": "fast-forward",
    "F10": "filter toggle",
    "F11": "fullscreen toggle",
    "F12": "screenshot",
}


def _gba_mapped_slots(keymap: dict) -> dict[str, str]:
    """For each keymap entry, return canonical SDL key name → GBA button name.

    Used at bind time to refuse macro slots that would clobber a GBA button.
    """
    out: dict[str, str] = {}
    for sdl_sym, button in keymap.items():
        name = sdl2.SDL_GetKeyName(sdl_sym).decode().upper().replace(" ", "")
        out[name] = button.name
    return out


def _slot_for_keysym(sym: int, mod: int) -> str | None:
    """Return the canonical slot name for the pressed key, or None.

    Returns None when any modifier is held (so Ctrl+R doesn't trigger an
    R macro). Returns None when the key doesn't map to an allowed slot.
    """
    if mod & (sdl2.KMOD_CTRL | sdl2.KMOD_SHIFT | sdl2.KMOD_ALT | sdl2.KMOD_GUI):
        return None
    raw = sdl2.SDL_GetKeyName(sym).decode().upper().replace(" ", "")
    from gbax.macros import normalize_slot
    return normalize_slot(raw)


def _screenshots_dir() -> Path:
    out = Path.home() / ".gbax" / "screenshots"
    out.mkdir(parents=True, exist_ok=True)
    return out


def play_loop(
    runtime: EmulatorRuntime,
    scale: int = DEFAULT_SCALE,
    keymap: Optional[dict[int, Button]] = None,
    fullscreen: bool = False,
    watch_state: bool = False,
    plugin_path: "Path | None" = None,
    renderer_kind: str = "sdl",
    initial_shader: str = "linear",
    user_shader_path: "Path | None" = None,
    listen: bool = False,
    listen_host: str = "127.0.0.1",
    listen_port: int = 8420,
) -> None:
    """Run the emulator in a window until the user closes it.

    F11 toggles borderless-desktop fullscreen.
    F10 toggles the upscale filter between linear and nearest.
    """
    import os

    # wgpu's Mesa-Vulkan path leaks per-frame swapchain textures when SDL
    # is in X11 mode on a Wayland host (XWayland). Forcing SDL to talk to
    # the native Wayland compositor fixes it. Users can override by
    # setting SDL_VIDEODRIVER themselves.
    if (
        renderer_kind == "wgpu"
        and "SDL_VIDEODRIVER" not in os.environ
        and os.environ.get("WAYLAND_DISPLAY")
    ):
        os.environ["SDL_VIDEODRIVER"] = "wayland"

    keymap = keymap if keymap is not None else default_keymap()
    held: set[Button] = set()
    fast_forward = False
    is_fullscreen = False
    filter_quality = "linear"

    # Load the plugin first so its scene_resolvers are available when the
    # watch panel's StateReader is built.
    loaded_plugin = None
    plugin_ctx = None
    plugin_last_state: dict[str, int | str] = {}
    plugin_scene_resolvers: list = []
    if plugin_path is not None:
        from gbax.plugin import PluginContext, load_plugin
        from gbax.state.storage import compiled_path_for_rom
        from gbax.state.watch import StateReader

        loaded_plugin = load_plugin(plugin_path)
        plugin_scene_resolvers = list(loaded_plugin.scene_resolvers)
        plugin_reader = StateReader(
            compiled_path_for_rom(runtime.rom_sha1), runtime,
            plugin_scene_resolvers=plugin_scene_resolvers,
        )
        plugin_compiled: dict = {}
        compiled = compiled_path_for_rom(runtime.rom_sha1)
        if compiled.exists():
            import json as _json
            plugin_compiled = _json.loads(compiled.read_text()).get("tags", {})
        plugin_ctx = PluginContext(runtime, plugin_reader, plugin_compiled)
        plugin_ctx.refresh_state()
        plugin_last_state = dict(plugin_ctx.state)
        for fn in loaded_plugin.setup_handlers:
            try:
                fn(plugin_ctx)
            except Exception:
                import traceback
                traceback.print_exc()

    watch_panel = None
    state_reader = None
    panel_render_fn = None
    if watch_state:
        from gbax.state.storage import compiled_path_for_rom
        from gbax.state.watch import StateReader

        compiled = compiled_path_for_rom(runtime.rom_sha1)
        state_reader = StateReader(
            compiled, runtime,
            plugin_scene_resolvers=plugin_scene_resolvers,
        )
        if not state_reader.has_tags:
            print(f"--watch-state: no compiled state at {compiled}; panel disabled.")
            state_reader = None
        else:
            from rich.console import Console
            from rich.live import Live
            from rich.table import Table

            def _render() -> Table:
                t = Table(show_header=False, expand=False, box=None, padding=(0, 2))
                values = state_reader.read_all()
                for tag in sorted(values):
                    t.add_row(f"{tag}:", str(values[tag]))
                return t

            panel_render_fn = _render
            watch_panel = Live(_render(), console=Console(), refresh_per_second=10, transient=False)
            watch_panel.__enter__()

    http_server_thread = None
    if listen:
        import inspect
        import threading

        import uvicorn
        from fastapi import APIRouter, HTTPException

        from gbax.api.server import create_app

        app = create_app(runtime)

        plugin_summaries: list[dict] = []
        if loaded_plugin is not None and plugin_ctx is not None and plugin_path is not None:
            plugin_name = plugin_path.stem
            plugin_router = APIRouter(prefix=f"/plugins/{plugin_name}", tags=[plugin_name])
            for path_, methods_, handler_ in loaded_plugin.http_routes:
                # Strip ctx from the FastAPI-visible signature so FastAPI's
                # path/query param inspection only sees the user's extra params.
                sig = inspect.signature(handler_)
                params = list(sig.parameters.values())
                if params and params[0].name == "ctx":
                    fastapi_params = params[1:]
                else:
                    fastapi_params = params
                fastapi_sig = sig.replace(parameters=fastapi_params)

                def _make_endpoint(h):
                    def endpoint(*args, **kwargs):
                        try:
                            with runtime._lock:
                                return h(plugin_ctx, *args, **kwargs)
                        except Exception as exc:
                            raise HTTPException(
                                status_code=500,
                                detail=f"{type(exc).__name__}: {exc}",
                            ) from exc
                    return endpoint

                ep = _make_endpoint(handler_)
                ep.__signature__ = fastapi_sig
                ep.__name__ = handler_.__name__
                plugin_router.add_api_route(path_, ep, methods=methods_)
            app.include_router(plugin_router)
            plugin_summaries.append({
                "name": plugin_name,
                "path": str(plugin_path),
                "routes": [
                    {"path": f"/plugins/{plugin_name}{path_}", "methods": methods_}
                    for path_, methods_, _ in loaded_plugin.http_routes
                ],
            })

        @app.get("/plugins")
        def _list_plugins():
            return {"plugins": plugin_summaries}

        config = uvicorn.Config(
            app,
            host=listen_host,
            port=listen_port,
            log_level="warning",
            access_log=False,
        )
        http_server = uvicorn.Server(config)

        def _run_http():
            http_server.run()

        http_server_thread = threading.Thread(target=_run_http, daemon=True)
        http_server_thread.start()
        print(f"gbax HTTP API listening on http://{listen_host}:{listen_port}")
        for p_summary in plugin_summaries:
            for r in p_summary["routes"]:
                print(f"  plugin route: {','.join(r['methods'])} {r['path']}")

    sdl2.ext.init()
    sdl2.SDL_InitSubSystem(sdl2.SDL_INIT_AUDIO)
    try:
        from gbax.render.sdl_renderer import SDLRenderer

        window = sdl2.ext.Window(
            f"gbax — {runtime.rom_path.name}",
            size=(GBA_WIDTH * scale, GBA_HEIGHT * scale),
            flags=sdl2.SDL_WINDOW_RESIZABLE,
        )
        window.show()

        if renderer_kind == "wgpu":
            from gbax.render.wgpu_renderer import WGPURenderer
            renderer = WGPURenderer()
        elif renderer_kind == "sdl":
            renderer = SDLRenderer()
        else:
            raise SystemExit(f"unknown --renderer: {renderer_kind!r}; choices: sdl, wgpu")
        # Only honor the user's initial_shader if it's available; otherwise default to linear.
        if initial_shader in renderer.available_shaders:
            renderer.current_shader = initial_shader
        else:
            renderer.current_shader = "linear"
        renderer.init(window, GBA_WIDTH, GBA_HEIGHT)
        if user_shader_path is not None:
            if hasattr(renderer, "load_user_shader"):
                renderer.load_user_shader(user_shader_path)
            else:
                print("warning: --user-shader only supported for --renderer=wgpu")
        if fullscreen:
            renderer.set_fullscreen(True)
            is_fullscreen = True
        # Surface the active shader for the F10 log line.
        filter_quality = renderer.current_shader

        # Open a stereo S16 audio device matching the core's sample rate.
        wanted = sdl2.SDL_AudioSpec(
            AUDIO_SAMPLE_RATE,
            sdl2.AUDIO_S16SYS,
            2,        # channels
            2048,     # samples per buffer
        )
        obtained = sdl2.SDL_AudioSpec(0, 0, 0, 0)
        audio_dev = sdl2.SDL_OpenAudioDevice(None, 0, wanted, obtained, 0)
        if audio_dev == 0:
            print(f"warning: SDL_OpenAudioDevice failed ({sdl2.SDL_GetError().decode()}); audio off")
        else:
            sdl2.SDL_PauseAudioDevice(audio_dev, 0)  # 0 = unpause/play

            def _on_audio(buf: bytes) -> None:
                sdl2.SDL_QueueAudio(audio_dev, buf, len(buf))

            # Hook the libretro core's audio callback. `runtime._core` is gbax-internal.
            runtime._core.on_audio = _on_audio

        running = True
        event = sdl2.SDL_Event()
        last_frame = time.monotonic()

        while running:
            while sdl2.SDL_PollEvent(event) != 0:
                if event.type == sdl2.SDL_QUIT:
                    running = False
                    break

                if event.type == sdl2.SDL_KEYDOWN:
                    sym = event.key.keysym.sym
                    mod = event.key.keysym.mod

                    # Ctrl+F — capture labeled state snapshot
                    if sym == sdl2.SDLK_f and (mod & sdl2.KMOD_CTRL):
                        try:
                            label_input = input(
                                "capturing state — type labels (key=value, comma-separated): "
                            ).strip()
                        except EOFError:
                            label_input = ""
                        if not label_input:
                            print("no labels provided; discarded.")
                            continue
                        from gbax.state.storage import parse_labels
                        try:
                            labels = parse_labels(label_input)
                        except ValueError as exc:
                            print(f"label parse error: {exc}; discarded.")
                            continue
                        if not labels:
                            print("no labels provided; discarded.")
                            continue
                        from datetime import datetime, timezone
                        from gbax.state.capture import save_capture, sparse_capture
                        print("recording 30 frames…")
                        sparse = sparse_capture(runtime, n_frames=30)
                        fb = runtime.framebuffer()
                        ts = datetime.now(timezone.utc)
                        path = save_capture(
                            runtime.rom_sha1, sparse, labels, ts,
                            framebuffer=fb,
                        )
                        print(f"captured. ({len(sparse)} stable bytes + framebuffer) → {path}")
                        continue

                    # Ctrl+R — toggle macro recording
                    if sym == sdl2.SDLK_r and (mod & sdl2.KMOD_CTRL):
                        if runtime.is_recording_macro():
                            macro = runtime.stop_recording_macro()
                            if macro is None or macro.total_frames == 0:
                                print("record stopped (empty recording, discarded)")
                                continue
                            print(f"record stopped ({macro.total_frames} frames).")
                            try:
                                slot_input = input(
                                    "bind to which key? [A-Z, 0-9, F1-F9, SPACE, "
                                    "RETURN, BACKSPACE; or Enter to discard]: "
                                ).strip()
                            except EOFError:
                                slot_input = ""
                            if not slot_input:
                                print("discarded.")
                                continue
                            from gbax.macros import normalize_slot
                            norm = normalize_slot(slot_input)
                            if norm is None:
                                print(
                                    f"invalid slot {slot_input!r}; "
                                    "must be A-Z, 0-9, F1-F9, SPACE, RETURN, "
                                    "or BACKSPACE. discarded."
                                )
                                continue
                            gba_slots = _gba_mapped_slots(keymap)
                            if norm in gba_slots:
                                print(
                                    f"error: {norm} is mapped to GBA "
                                    f"{gba_slots[norm]}; pick another. discarded."
                                )
                                continue
                            if norm in RESERVED_HOTKEYS:
                                print(
                                    f"error: {norm} is reserved for "
                                    f"{RESERVED_HOTKEYS[norm]}; pick another. discarded."
                                )
                                continue
                            try:
                                name_input = input("name (optional): ").strip()
                            except EOFError:
                                name_input = ""
                            macro.slot = norm
                            macro.name = name_input
                            from gbax.macros import save as _save_macro
                            _save_macro(macro)
                            print(f"bound {norm} → {name_input or '(unnamed)'}")
                        else:
                            runtime.start_recording_macro()
                            print("recording... (Ctrl+R to stop)")
                        continue

                    # Ctrl+1..9 — save slot (modifier required so it's not fumbled)
                    if (sdl2.SDLK_1 <= sym <= sdl2.SDLK_9) and (mod & sdl2.KMOD_CTRL):
                        slot = sym - sdl2.SDLK_0
                        runtime.save_state_to_slot(slot)
                        print(f"saved slot {slot}")
                        continue

                    # Shift+1..9 — load slot
                    if (sdl2.SDLK_1 <= sym <= sdl2.SDLK_9) and (mod & sdl2.KMOD_SHIFT):
                        slot = sym - sdl2.SDLK_0
                        try:
                            runtime.load_state_from_slot(slot)
                            print(f"loaded slot {slot}")
                        except KeyError:
                            print(f"slot {slot} is empty")
                        continue

                    # Bare key (no modifier) — fire a macro if one is bound to
                    # this key. Falls through to F1..F9 cheat handling and the
                    # GBA button mapping below when no macro matches.
                    macro_slot = _slot_for_keysym(sym, mod)
                    if macro_slot is not None:
                        macro = _load_macro_for_slot(runtime.rom_sha1, macro_slot)
                        if macro is not None:
                            try:
                                runtime.play_macro(macro)
                                label = macro.name or "(unnamed)"
                                print(
                                    f"playing {macro_slot} → {label} "
                                    f"({macro.total_frames} frames)"
                                )
                            except RuntimeError as exc:
                                print(f"{macro_slot}: {exc}")
                            continue

                    # F1..F9 — cheat-pin behavior (toggle pinned cheat, or Nth active).
                    if sdl2.SDLK_F1 <= sym <= sdl2.SDLK_F9:
                        idx = sym - sdl2.SDLK_F1
                        key = f"F{idx + 1}"
                        pinned = runtime.cheat_pins().get(key)
                        if pinned:
                            try:
                                cheat, now_on = runtime.toggle_cheat(pinned)
                                print(f"cheat {'ON ' if now_on else 'OFF'}: {cheat.name}")
                            except KeyError as exc:
                                print(f"{key} pin error: {exc}")
                        else:
                            active = runtime.active_cheats()
                            if idx < len(active):
                                cheat, now_on = runtime.toggle_cheat(active[idx].slug())
                                print(f"cheat {'ON ' if now_on else 'OFF'}: {cheat.name}")
                            else:
                                print(f"{key} is unpinned (try: gbax pin <rom> {key} <slug>)")
                        continue

                    # F10 — cycle upscale shader
                    if sym == sdl2.SDLK_F10:
                        filter_quality = renderer.cycle_shader()
                        print(f"shader: {filter_quality}")
                        continue

                    # F11 — toggle borderless-desktop fullscreen
                    if sym == sdl2.SDLK_F11:
                        is_fullscreen = not is_fullscreen
                        renderer.set_fullscreen(is_fullscreen)
                        continue

                    # F12 — screenshot
                    if sym == sdl2.SDLK_F12:
                        out = _screenshots_dir() / f"{runtime.rom_path.stem}-{int(time.time())}.png"
                        from PIL import Image
                        Image.fromarray(runtime.framebuffer()).save(out)
                        print(f"screenshot → {out}")
                        continue

                    # LShift — start fast-forward
                    if sym == sdl2.SDLK_LSHIFT:
                        fast_forward = True
                        continue

                    # Button mapping
                    btn = keymap.get(sym)
                    if btn is not None:
                        held.add(btn)
                        runtime.set_buttons(held)

                    # Plugin on_key dispatch (bare key, no modifier).
                    if (
                        loaded_plugin is not None
                        and not (mod & (sdl2.KMOD_CTRL | sdl2.KMOD_SHIFT | sdl2.KMOD_ALT | sdl2.KMOD_GUI))
                    ):
                        slot = _slot_for_keysym(sym, mod)
                        if slot is not None and slot in loaded_plugin.key_handlers:
                            for fn in loaded_plugin.key_handlers[slot]:
                                try:
                                    fn(plugin_ctx)
                                except Exception:
                                    import traceback
                                    traceback.print_exc()

                elif event.type == sdl2.SDL_KEYUP:
                    sym = event.key.keysym.sym
                    if sym == sdl2.SDLK_LSHIFT:
                        fast_forward = False
                        continue
                    btn = keymap.get(sym)
                    if btn is not None:
                        held.discard(btn)
                        runtime.set_buttons(held)

            frames_this_iteration = FAST_FORWARD_MULTIPLIER if fast_forward else 1
            runtime.step(frames=frames_this_iteration)

            if loaded_plugin is not None and plugin_ctx is not None:
                plugin_ctx.refresh_state()
                new_state = plugin_ctx.state
                for tag, new_val in new_state.items():
                    old_val = plugin_last_state.get(tag, None)
                    if old_val != new_val and tag in loaded_plugin.state_change_handlers:
                        for fn, to_filter in loaded_plugin.state_change_handlers[tag]:
                            if to_filter is not None and new_val != to_filter:
                                continue
                            try:
                                fn(plugin_ctx, old_val, new_val)
                            except Exception:
                                import traceback
                                traceback.print_exc()
                plugin_last_state = dict(new_state)
                for fn, every in loaded_plugin.frame_handlers:
                    if every <= 1 or (runtime.frame_count % every) == 0:
                        try:
                            fn(plugin_ctx)
                        except Exception:
                            import traceback
                            traceback.print_exc()

            if watch_panel is not None and panel_render_fn is not None:
                watch_panel.update(panel_render_fn())

            fb = runtime.framebuffer()  # already a copy from the locked accessor
            fb_bytes = np.ascontiguousarray(fb).tobytes()
            renderer.present_frame(fb_bytes)

            if not fast_forward:
                elapsed = time.monotonic() - last_frame
                sleep = TARGET_FRAME_TIME - elapsed
                if sleep > 0:
                    time.sleep(sleep)
            last_frame = time.monotonic()

        renderer.close()
        if audio_dev:
            sdl2.SDL_CloseAudioDevice(audio_dev)
    finally:
        if http_server_thread is not None:
            http_server.should_exit = True
        if loaded_plugin is not None and plugin_ctx is not None:
            for fn in loaded_plugin.teardown_handlers:
                try:
                    fn(plugin_ctx)
                except Exception:
                    import traceback
                    traceback.print_exc()
        if watch_panel is not None:
            watch_panel.__exit__(None, None, None)
        runtime._core.on_audio = None
        sdl2.ext.quit()
