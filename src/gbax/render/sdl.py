"""SDL window for `gbax play`.

Single event-loop client of EmulatorRuntime:
  - blits the framebuffer to a window at fixed-factor upscale
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


def _screenshots_dir() -> Path:
    out = Path.home() / ".gbax" / "screenshots"
    out.mkdir(parents=True, exist_ok=True)
    return out


def play_loop(
    runtime: EmulatorRuntime,
    scale: int = DEFAULT_SCALE,
    keymap: Optional[dict[int, Button]] = None,
) -> None:
    """Run the emulator in a window until the user closes it."""
    keymap = keymap if keymap is not None else default_keymap()
    held: set[Button] = set()
    fast_forward = False

    sdl2.ext.init()
    try:
        window = sdl2.ext.Window(
            f"gbax — {runtime.rom_path.name}",
            size=(GBA_WIDTH * scale, GBA_HEIGHT * scale),
        )
        window.show()
        renderer = sdl2.ext.Renderer(window, flags=sdl2.SDL_RENDERER_ACCELERATED)
        texture = sdl2.SDL_CreateTexture(
            renderer.sdlrenderer,
            sdl2.SDL_PIXELFORMAT_RGB24,
            sdl2.SDL_TEXTUREACCESS_STREAMING,
            GBA_WIDTH,
            GBA_HEIGHT,
        )

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

                    # Ctrl+S — persist most-recently-saved slot
                    if sym == sdl2.SDLK_s and (mod & sdl2.KMOD_CTRL):
                        if runtime._slots:  # noqa: SLF001 — internal touch is OK in render layer
                            last_slot = max(runtime._slots.keys())
                            try:
                                path = runtime.persist_slot_to_disk(last_slot)
                                print(f"persisted slot {last_slot} → {path}")
                            except Exception as e:
                                print(f"persist failed: {e}")
                        else:
                            print("no slot to persist (save one first with 1-9)")
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

                    # 1..9 — save slot
                    if (sdl2.SDLK_1 <= sym <= sdl2.SDLK_9) and not (mod & sdl2.KMOD_CTRL):
                        slot = sym - sdl2.SDLK_0
                        runtime.save_state_to_slot(slot)
                        print(f"saved slot {slot}")
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
    finally:
        sdl2.ext.quit()
