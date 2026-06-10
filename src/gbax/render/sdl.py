"""SDL window for `gbax play`.

Single event-loop client of EmulatorRuntime:
  - blits the framebuffer to a window at fixed-factor upscale
  - emits audio samples to an SDL audio device
  - keyboard → GBA buttons
  - hotkeys for save state slots 1-9, fast-forward (Tab), screenshot (F12)
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
    "TAB": "fast-forward",
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


def _make_texture(renderer_ptr, filter_quality: str):
    """Recreate the streaming texture under a given scale-quality hint.

    SDL bakes the scale-quality hint into the texture at create time, not
    the renderer, so toggling filter at runtime means destroying and
    recreating the texture. Cheap — one handle, no GPU memory pressure.
    """
    sdl2.SDL_SetHint(sdl2.SDL_HINT_RENDER_SCALE_QUALITY, filter_quality.encode())
    return sdl2.SDL_CreateTexture(
        renderer_ptr,
        sdl2.SDL_PIXELFORMAT_RGB24,
        sdl2.SDL_TEXTUREACCESS_STREAMING,
        GBA_WIDTH,
        GBA_HEIGHT,
    )


def play_loop(
    runtime: EmulatorRuntime,
    scale: int = DEFAULT_SCALE,
    keymap: Optional[dict[int, Button]] = None,
    fullscreen: bool = False,
) -> None:
    """Run the emulator in a window until the user closes it.

    F11 toggles borderless-desktop fullscreen.
    F10 toggles the upscale filter between linear and nearest.
    """
    keymap = keymap if keymap is not None else default_keymap()
    held: set[Button] = set()
    fast_forward = False
    is_fullscreen = False
    filter_quality = "linear"

    sdl2.ext.init()
    sdl2.SDL_InitSubSystem(sdl2.SDL_INIT_AUDIO)
    try:
        # Hint must be set before the renderer / texture are created.
        sdl2.SDL_SetHint(sdl2.SDL_HINT_RENDER_SCALE_QUALITY, filter_quality.encode())

        window = sdl2.ext.Window(
            f"gbax — {runtime.rom_path.name}",
            size=(GBA_WIDTH * scale, GBA_HEIGHT * scale),
            flags=sdl2.SDL_WINDOW_RESIZABLE,
        )
        window.show()
        renderer = sdl2.ext.Renderer(window, flags=sdl2.SDL_RENDERER_ACCELERATED)
        # Letterbox + aspect-preserve: SDL handles the rest of the scaling math.
        sdl2.SDL_RenderSetLogicalSize(renderer.sdlrenderer, GBA_WIDTH, GBA_HEIGHT)
        texture = _make_texture(renderer.sdlrenderer, filter_quality)

        if fullscreen:
            sdl2.SDL_SetWindowFullscreen(window.window, sdl2.SDL_WINDOW_FULLSCREEN_DESKTOP)
            is_fullscreen = True

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

                    # F10 — toggle upscale filter (linear ↔ nearest)
                    if sym == sdl2.SDLK_F10:
                        filter_quality = "nearest" if filter_quality == "linear" else "linear"
                        sdl2.SDL_DestroyTexture(texture)
                        texture = _make_texture(renderer.sdlrenderer, filter_quality)
                        print(f"filter: {filter_quality}")
                        continue

                    # F11 — toggle borderless-desktop fullscreen
                    if sym == sdl2.SDLK_F11:
                        is_fullscreen = not is_fullscreen
                        sdl2.SDL_SetWindowFullscreen(
                            window.window,
                            sdl2.SDL_WINDOW_FULLSCREEN_DESKTOP if is_fullscreen else 0,
                        )
                        continue

                    # F12 — screenshot
                    if sym == sdl2.SDLK_F12:
                        out = _screenshots_dir() / f"{runtime.rom_path.stem}-{int(time.time())}.png"
                        from PIL import Image
                        Image.fromarray(runtime.framebuffer()).save(out)
                        print(f"screenshot → {out}")
                        continue

                    # Tab — start fast-forward
                    if sym == sdl2.SDLK_TAB:
                        fast_forward = True
                        continue

                    # Button mapping
                    btn = keymap.get(sym)
                    if btn is not None:
                        held.add(btn)
                        runtime.set_buttons(held)

                elif event.type == sdl2.SDL_KEYUP:
                    sym = event.key.keysym.sym
                    if sym == sdl2.SDLK_TAB:
                        fast_forward = False
                        continue
                    btn = keymap.get(sym)
                    if btn is not None:
                        held.discard(btn)
                        runtime.set_buttons(held)

            frames_this_iteration = FAST_FORWARD_MULTIPLIER if fast_forward else 1
            runtime.step(frames=frames_this_iteration)

            fb = runtime.framebuffer()  # already a copy from the locked accessor
            fb_bytes = np.ascontiguousarray(fb).tobytes()
            sdl2.SDL_UpdateTexture(texture, None, fb_bytes, GBA_WIDTH * 3)

            renderer.clear()
            sdl2.SDL_RenderCopy(renderer.sdlrenderer, texture, None, None)
            renderer.present()

            if not fast_forward:
                elapsed = time.monotonic() - last_frame
                sleep = TARGET_FRAME_TIME - elapsed
                if sleep > 0:
                    time.sleep(sleep)
            last_frame = time.monotonic()

        sdl2.SDL_DestroyTexture(texture)
        if audio_dev:
            sdl2.SDL_CloseAudioDevice(audio_dev)
    finally:
        runtime._core.on_audio = None
        sdl2.ext.quit()
