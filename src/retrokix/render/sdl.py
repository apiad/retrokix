"""SDL window for `retrokix play`.

Single event-loop client of EmulatorRuntime:
  - blits the framebuffer to a window at fixed-factor upscale
  - emits audio samples to an SDL audio device
  - keyboard → GBA buttons
  - hotkeys for save state slots 1-9, fast-forward (LShift), screenshot (F12)
  - persistence with Ctrl+S
"""

from __future__ import annotations

import queue
import time
from pathlib import Path
from typing import TYPE_CHECKING, Callable, Optional

import numpy as np
import sdl2
import sdl2.ext

from retrokix.input import Button
from retrokix.runtime import EmulatorRuntime

if TYPE_CHECKING:
    import threading

    from retrokix.tui.status import StatusSnapshot


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
    from retrokix.macros import load
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
    from retrokix.macros import normalize_slot
    return normalize_slot(raw)


def _screenshots_dir() -> Path:
    out = Path.home() / ".retrokix" / "screenshots"
    out.mkdir(parents=True, exist_ok=True)
    return out


def _ask_one(prompt, title: str, field: str, terminal_prompt: str) -> str:
    """Collect one text value via the TUI modal bridge (``prompt``) or, when
    ``prompt`` is None, via terminal ``input()``. Returns "" on cancel/EOF."""
    if prompt is not None:
        res = prompt(title, [field])
        return str(res.get(field, "")).strip() if res else ""
    try:
        return input(terminal_prompt).strip()
    except EOFError:
        return ""


def _capture_with_labels(runtime, prompt) -> None:
    """Ctrl+F flow: record the time-sensitive frames + framebuffer first, then
    collect labels (modal or terminal) and save the capture."""
    from datetime import datetime, timezone

    from retrokix.state.capture import save_capture, sparse_capture
    from retrokix.state.storage import parse_labels

    print("recording 30 frames…")
    sparse = sparse_capture(runtime, n_frames=30)
    fb = runtime.framebuffer()
    label_input = _ask_one(
        prompt,
        "Capture labels (key=value, comma-separated)",
        "labels",
        "capturing state — type labels (key=value, comma-separated): ",
    )
    if not label_input:
        print("no labels provided; discarded.")
        return
    try:
        labels = parse_labels(label_input)
    except ValueError as exc:
        print(f"label parse error: {exc}; discarded.")
        return
    if not labels:
        print("no labels provided; discarded.")
        return
    ts = datetime.now(timezone.utc)
    path = save_capture(runtime.rom_sha1, sparse, labels, ts, framebuffer=fb)
    print(f"captured. ({len(sparse)} stable bytes + framebuffer) → {path}")


def _bind_macro(macro, keymap, prompt) -> None:
    """Ctrl+R stop flow: collect slot (+ optional name) and save the macro,
    refusing GBA-mapped and reserved slots. Modal asks both fields at once;
    the terminal path asks slot first, validates, then name."""
    from retrokix.macros import normalize_slot
    from retrokix.macros import save as _save_macro

    if prompt is not None:
        res = prompt("Bind macro — slot + optional name", ["slot", "name"])
        if not res:
            print("discarded.")
            return
        slot_input = str(res.get("slot", "")).strip()
        name_input: str | None = str(res.get("name", "")).strip()
    else:
        slot_input = _ask_one(
            None,
            "",
            "slot",
            "bind to which key? [A-Z, 0-9, F1-F9, SPACE, RETURN, BACKSPACE; or Enter to discard]: ",
        )
        name_input = None  # terminal path asks name after the slot validates

    if not slot_input:
        print("discarded.")
        return
    norm = normalize_slot(slot_input)
    if norm is None:
        print(
            f"invalid slot {slot_input!r}; must be A-Z, 0-9, F1-F9, SPACE, "
            "RETURN, or BACKSPACE. discarded."
        )
        return
    gba_slots = _gba_mapped_slots(keymap)
    if norm in gba_slots:
        print(f"error: {norm} is mapped to GBA {gba_slots[norm]}; pick another. discarded.")
        return
    if norm in RESERVED_HOTKEYS:
        print(f"error: {norm} is reserved for {RESERVED_HOTKEYS[norm]}; pick another. discarded.")
        return

    if name_input is None:
        try:
            name_input = input("name (optional): ").strip()
        except EOFError:
            name_input = ""
    macro.slot = norm
    macro.name = name_input
    _save_macro(macro)
    print(f"bound {norm} → {name_input or '(unnamed)'}")


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
    couch_room: str | None = None,
    status_snapshot: "StatusSnapshot | None" = None,
    stop_event: "threading.Event | None" = None,
    prompt: "Callable[[str, list[str]], dict | None] | None" = None,
) -> None:
    """Run the emulator in a window until the user closes it.

    F11 toggles borderless-desktop fullscreen.
    F10 toggles the upscale filter between linear and nearest.

    When ``status_snapshot`` is given (a ``retrokix.tui.status.StatusSnapshot``),
    publish a per-frame status struct for the companion TUI to poll, and persist
    play time on teardown. ``stop_event`` (a ``threading.Event``) lets the TUI
    request shutdown. ``prompt`` is how the Ctrl+F / Ctrl+R flows collect text:
    when given (``prompt(title, fields) -> dict | None``, e.g. the TUI modal
    bridge) it's used instead of terminal ``input()``; ``None`` keeps the
    terminal prompts (the non-TUI path).
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
    _last_ff = False  # previous tick's fast-forward state (for audio clear-on-release)
    is_fullscreen = False
    filter_quality = "linear"

    # Load the plugin first so its scene_resolvers are available when the
    # watch panel's StateReader is built.
    loaded_plugin = None
    plugin_ctx = None
    plugin_last_state: dict[str, int | str] = {}
    plugin_scene_resolvers: list = []
    if plugin_path is not None:
        from retrokix.plugin import PluginContext, load_plugin
        from retrokix.state.storage import compiled_path_for_rom
        from retrokix.state.watch import StateReader

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

    # Couch — if this plugin declared either emits or receive-handlers,
    # spin up a broker (or attach to an existing one) and connect a
    # CouchHandle. Receive events are queued onto a thread-safe queue
    # and drained on the SDL main thread once per play-loop tick so
    # plugin handlers can touch the runtime safely.
    couch_handle = None
    couch_broker = None
    couch_inbox: "queue.Queue[tuple[str, object, dict]]" = queue.Queue()
    if (
        loaded_plugin is not None
        and plugin_ctx is not None
        and (loaded_plugin.couch_emits or loaded_plugin.couch_event_handlers)
    ):
        from retrokix.couch import (
            DEFAULT_SOCK as _COUCH_DEFAULT_SOCK,
            CouchHandle,
            ensure_local_broker,
        )
        from retrokix.couch.identity import load_or_generate as _load_couch_identity
        from retrokix.couch.naming import DEFAULT_ROOM as _DEFAULT_ROOM

        try:
            couch_broker = ensure_local_broker(_COUCH_DEFAULT_SOCK)
        except OSError as exc:
            print(f"couch: broker bind failed: {exc} — plugin couch disabled")
            couch_broker = None
        if couch_broker is not None or _COUCH_DEFAULT_SOCK.exists():
            identity = _load_couch_identity()
            try:
                couch_handle = CouchHandle(
                    peer_id=identity.id,
                    name=identity.name,
                    emits=list(loaded_plugin.couch_emits),
                    receives=list(loaded_plugin.couch_event_handlers.keys()),
                    room=couch_room or _DEFAULT_ROOM,
                )
                couch_handle.connect_unix(str(_COUCH_DEFAULT_SOCK))
            except (FileNotFoundError, ConnectionRefusedError, TimeoutError, OSError) as exc:
                print(f"couch: connect failed: {exc} — plugin couch disabled")
                couch_handle = None
        if couch_handle is not None:
            print(
                f"couch: connected as {couch_handle.peer_id[:8]}…  "
                f"name={couch_handle.name}  room={couch_handle.room}  "
                f"({len(couch_handle.peers())} peer(s))"
            )

            # Wire each declared receive into a queue feeder. Plugin
            # handlers are invoked by the play loop on its own thread.
            def _make_feeder(_event_type: str):
                def _enqueue(_handle, evt):
                    couch_inbox.put((_event_type, evt.sender, evt.payload))
                return _enqueue

            for event_type in loaded_plugin.couch_event_handlers:
                couch_handle.on(event_type, _make_feeder(event_type))

            plugin_ctx.couch = couch_handle

    watch_panel = None
    state_reader = None
    panel_render_fn = None
    if watch_state:
        from retrokix.state.storage import compiled_path_for_rom
        from retrokix.state.watch import StateReader

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
    # `app` is the FastAPI app when --listen is on, None otherwise. Read
    # downstream by the audio callback to decide whether to publish
    # frames over the WebSocket bus; must exist in both branches.
    app = None
    if listen:
        import inspect
        import threading

        import uvicorn
        from fastapi import APIRouter, HTTPException

        from retrokix.api.server import create_app

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
        print(f"retrokix HTTP API listening on http://{listen_host}:{listen_port}")
        for p_summary in plugin_summaries:
            for r in p_summary["routes"]:
                print(f"  plugin route: {','.join(r['methods'])} {r['path']}")

    session = None  # play-time tracker; created once the loop starts, flushed in finally
    sdl2.ext.init()
    sdl2.SDL_InitSubSystem(sdl2.SDL_INIT_AUDIO)
    sdl2.SDL_InitSubSystem(sdl2.SDL_INIT_GAMECONTROLLER)
    try:
        from retrokix.render.sdl_renderer import SDLRenderer

        # Pick window + renderer dims from the actual core geometry. The
        # runtime pre-sizes its framebuffer from system_av_info() so
        # `width`/`height` are correct before the first retro_run for
        # any console (GBA 240x160, NES 256x240, SNES 256x224, …).
        fb_w = runtime.width
        fb_h = runtime.height
        window = sdl2.ext.Window(
            f"retrokix — {runtime.rom_path.name}",
            size=(fb_w * scale, fb_h * scale),
            flags=sdl2.SDL_WINDOW_RESIZABLE,
        )
        window.show()

        if renderer_kind == "wgpu":
            from retrokix.render.wgpu_renderer import WGPURenderer
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
        renderer.init(window, fb_w, fb_h)
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

            # `fast_forward` lives in this closure; `_app_for_audio` is
            # the FastAPI app when --listen is on, None otherwise. The
            # callback mutes audio entirely during fast-forward (either
            # source) — playing 8× the samples in real time would be
            # chipmunk garbage. It also fans the PCM out to /stream/audio/ws
            # subscribers via the AudioBus.
            _app_for_audio = app
            def _on_audio(buf: bytes) -> None:
                remote_ff = (
                    _app_for_audio.state.fast_forward
                    if _app_for_audio is not None else False
                )
                if fast_forward or remote_ff:
                    return
                sdl2.SDL_QueueAudio(audio_dev, buf, len(buf))
                if _app_for_audio is not None:
                    _app_for_audio.state.audio_bus.publish(buf)

            # Hook the libretro core's audio callback. `runtime._core` is retrokix-internal.
            runtime._core.on_audio = _on_audio

        # Gamepads — open everything attached at startup; hot-plug events
        # below add/remove pads live. Set-union into the same `held` set
        # that keyboard + agent use, so all input sources combine cleanly.
        from retrokix.render.gamepad import PadManager

        def _set_fast_forward(on: bool) -> None:
            nonlocal fast_forward
            fast_forward = on

        def _pad_plugin_slot(slot: str, down: bool) -> None:
            if loaded_plugin is None or plugin_ctx is None or not down:
                return
            handlers = loaded_plugin.key_handlers.get(slot, ())
            for fn in handlers:
                try:
                    fn(plugin_ctx)
                except Exception:
                    import traceback
                    traceback.print_exc()

        pad_manager = PadManager(
            on_fast_forward=_set_fast_forward,
            on_plugin_slot=_pad_plugin_slot,
        )
        opened = pad_manager.open_attached()
        for name in opened:
            print(f"gamepad: {name}")

        running = True
        event = sdl2.SDL_Event()
        last_frame = time.monotonic()

        # Companion-TUI status: a play-time session + a rolling fps window,
        # republished each frame into the snapshot the TUI polls.
        if status_snapshot is not None:
            from retrokix.tui.playtime import PlayTime

            session = PlayTime(runtime.rom_sha1)
            session.start()
        _fps_win = [time.monotonic(), 0, 0.0]  # [window_start, frames, fps]

        while running and (stop_event is None or not stop_event.is_set()):
            while sdl2.SDL_PollEvent(event) != 0:
                if event.type == sdl2.SDL_QUIT:
                    running = False
                    break

                if event.type == sdl2.SDL_CONTROLLERDEVICEADDED:
                    name = pad_manager.handle_device_added(event.cdevice.which)
                    if name is not None:
                        print(f"gamepad attached: {name}")
                    continue
                if event.type == sdl2.SDL_CONTROLLERDEVICEREMOVED:
                    name = pad_manager.handle_device_removed(event.cdevice.which, held)
                    if name is not None:
                        print(f"gamepad removed: {name}")
                        runtime.set_buttons(held)
                    continue
                if event.type == sdl2.SDL_CONTROLLERBUTTONDOWN:
                    pad_manager.handle_button(
                        event.cbutton.which, event.cbutton.button, True, held,
                    )
                    runtime.set_buttons(held)
                    continue
                if event.type == sdl2.SDL_CONTROLLERBUTTONUP:
                    pad_manager.handle_button(
                        event.cbutton.which, event.cbutton.button, False, held,
                    )
                    runtime.set_buttons(held)
                    continue
                if event.type == sdl2.SDL_CONTROLLERAXISMOTION:
                    pad_manager.handle_axis(
                        event.caxis.which, event.caxis.axis, event.caxis.value, held,
                    )
                    runtime.set_buttons(held)
                    continue

                if event.type == sdl2.SDL_KEYDOWN:
                    sym = event.key.keysym.sym
                    mod = event.key.keysym.mod

                    # Ctrl+F — capture labeled state snapshot
                    if sym == sdl2.SDLK_f and (mod & sdl2.KMOD_CTRL):
                        _capture_with_labels(runtime, prompt)
                        continue

                    # Ctrl+R — toggle macro recording
                    if sym == sdl2.SDLK_r and (mod & sdl2.KMOD_CTRL):
                        if runtime.is_recording_macro():
                            macro = runtime.stop_recording_macro()
                            if macro is None or macro.total_frames == 0:
                                print("record stopped (empty recording, discarded)")
                                continue
                            print(f"record stopped ({macro.total_frames} frames).")
                            _bind_macro(macro, keymap, prompt)
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

                    # Ctrl+S — write a new running save (never overwrites).
                    if sym == sdl2.SDLK_s and (mod & sdl2.KMOD_CTRL):
                        path = runtime.save_state_running()
                        print(f"saved → {path.name}")
                        continue

                    # Ctrl+L — load the newest running save for this ROM.
                    if sym == sdl2.SDLK_l and (mod & sdl2.KMOD_CTRL):
                        latest = runtime.latest_running_save()
                        if latest is None:
                            print("no running saves yet — Ctrl+S to make one")
                        else:
                            runtime.load_state_from_file(latest)
                            print(f"loaded ← {latest.name}")
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
                                print(f"{key} is unpinned (try: retrokix pin <rom> {key} <slug>)")
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
                        runtime._persist_setting(fullscreen=is_fullscreen)
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

            # Browser TURBO (sent via /stream/ws fast_forward message)
            # composes set-union with the local L-Shift just like inputs.
            _remote_ff = bool(app.state.fast_forward) if app is not None else False
            _ff = fast_forward or _remote_ff
            if not _ff and audio_dev:
                # Tail end of a fast-forward burst — drop any audio that
                # piled up while muted so the next normal samples play in
                # real time, not behind a half-second of silence buffer.
                if _last_ff:
                    sdl2.SDL_ClearQueuedAudio(audio_dev)
            _last_ff = _ff
            frames_this_iteration = FAST_FORWARD_MULTIPLIER if _ff else 1
            runtime.step(frames=frames_this_iteration)

            if loaded_plugin is not None and plugin_ctx is not None:
                # Drain incoming couch events on the SDL thread so plugin
                # handlers can safely write to the runtime.
                while not couch_inbox.empty():
                    try:
                        event_type, sender_id, payload = couch_inbox.get_nowait()
                    except Exception:
                        break
                    handlers = loaded_plugin.couch_event_handlers.get(event_type, ())
                    if not handlers:
                        continue
                    peer = (
                        couch_handle.peer(sender_id) if couch_handle is not None else None
                    )
                    if peer is None:
                        # Fall back to a placeholder so handlers can still log.
                        from retrokix.couch import PeerInfo as _PeerInfo
                        peer = _PeerInfo(id=sender_id, name=sender_id)
                    for fn in handlers:
                        try:
                            fn(plugin_ctx, peer, payload)
                        except Exception:
                            import traceback
                            traceback.print_exc()

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

            if status_snapshot is not None:
                _fps_win[1] += 1
                _now = time.monotonic()
                if _now - _fps_win[0] >= 0.5:
                    _fps_win[2] = _fps_win[1] / (_now - _fps_win[0])
                    _fps_win[0] = _now
                    _fps_win[1] = 0
                status_snapshot.publish(
                    title=runtime.rom_path.name,
                    console=str(getattr(runtime, "console", "") or ""),
                    sha1=runtime.rom_sha1,
                    fps=_fps_win[2],
                    speed=float(FAST_FORWARD_MULTIPLIER) if _ff else 1.0,
                    frame_count=runtime.frame_count,
                    session_seconds=session.session_seconds if session else 0.0,
                    total_seconds=session.total_seconds if session else 0.0,
                    api_endpoint=(f"{listen_host}:{listen_port}" if listen else None),
                    client_count=(
                        int(getattr(app.state, "ws_clients", 0)) if app is not None else 0
                    ),
                )

        renderer.close()
        if audio_dev:
            sdl2.SDL_CloseAudioDevice(audio_dev)
    finally:
        if session is not None:
            session.flush()
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
        try:
            pad_manager.close_all()
        except NameError:
            pass  # never reached open_attached() — e.g. early init failure
        if couch_handle is not None:
            try:
                couch_handle.close()
            except Exception:
                pass
        if couch_broker is not None:
            try:
                couch_broker.close()
            except Exception:
                pass
        sdl2.ext.quit()
