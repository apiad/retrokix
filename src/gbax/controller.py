"""High-level, blocking, pythonic facade over EmulatorRuntime.

This is the public Python API for headless gbax automation. Scenarios,
plugins (future), and ad-hoc scripts all use it. Internally it wraps an
EmulatorRuntime in STEP mode and exposes blocking primitives.

Equivalent to `gbax serve` but in-process — no HTTP round-trip.
"""

from __future__ import annotations

from collections.abc import Iterable
from pathlib import Path

import numpy as np

from gbax.input import Button, button_from_str
from gbax.runtime import EmulatorRuntime, Mode


def _coerce_buttons(buttons: Iterable[str | Button]) -> set[Button]:
    out: set[Button] = set()
    for b in buttons:
        if isinstance(b, Button):
            out.add(b)
        else:
            out.add(button_from_str(str(b)))
    return out


class Controller:
    def __init__(
        self,
        rom: str | Path,
        core_path: str | Path | None = None,
        save_dir: str | Path | None = None,
    ):
        from gbax.library import resolve_rom

        rom_path = resolve_rom(str(rom))
        self._runtime = EmulatorRuntime(
            rom_path,
            core_path=core_path,
            save_dir=save_dir,
            mode=Mode.STEP,
        )

    @property
    def rom_path(self) -> Path:
        return self._runtime.rom_path

    @property
    def rom_sha1(self) -> str:
        return self._runtime.rom_sha1

    @property
    def frame_count(self) -> int:
        return self._runtime.frame_count

    @property
    def framebuffer(self) -> np.ndarray:
        return self._runtime.framebuffer()

    def press(self, buttons: Iterable[str | Button], frames: int = 1) -> None:
        """Hold the given buttons for N frames, then release everything."""
        if frames < 1:
            raise ValueError(f"frames must be >= 1, got {frames}")
        held = _coerce_buttons(buttons)
        self._runtime.set_buttons(held)
        try:
            self._runtime.step(frames=frames)
        finally:
            self._runtime.set_buttons(set())

    def hold(self, buttons: Iterable[str | Button]) -> None:
        """Set the held button set without auto-release."""
        self._runtime.set_buttons(_coerce_buttons(buttons))

    def release(self) -> None:
        """Release all held buttons."""
        self._runtime.set_buttons(set())

    def wait(self, frames: int) -> None:
        """Advance N frames with the current held buttons."""
        if frames < 1:
            raise ValueError(f"frames must be >= 1, got {frames}")
        self._runtime.step(frames=frames)

    # --- memory ---

    def read_u8(self, addr: int) -> int:
        return self._runtime.read_u8(addr)

    def read_u16(self, addr: int) -> int:
        return self._runtime.read_u16(addr)

    def read_u32(self, addr: int) -> int:
        return self._runtime.read_u32(addr)

    def read_bytes(self, addr: int, length: int) -> bytes:
        return self._runtime.read_memory(addr, length)

    def write_u8(self, addr: int, value: int) -> None:
        self._runtime.write_u8(addr, value)

    def write_u16(self, addr: int, value: int) -> None:
        self._runtime.write_u16(addr, value)

    def write_u32(self, addr: int, value: int) -> None:
        self._runtime.write_u32(addr, value)

    def write_bytes(self, addr: int, data: bytes) -> None:
        self._runtime.write_memory(addr, data)

    # --- screenshot ---

    def screenshot(self, path: str | Path) -> Path:
        from PIL import Image

        out = Path(path)
        out.parent.mkdir(parents=True, exist_ok=True)
        Image.fromarray(self.framebuffer).save(out)
        return out

    # --- save states ---

    def save_state(self) -> bytes:
        return self._runtime.export_state()

    def load_state(self, blob: bytes) -> None:
        self._runtime.import_state(blob, frame_count=self.frame_count)

    def save_slot(self, slot: int) -> bytes:
        return self._runtime.save_state_to_slot(slot)

    def load_slot(self, slot: int) -> None:
        self._runtime.load_state_from_slot(slot)

    # --- cheats ---

    def enable_cheat(self, slug_or_name: str) -> None:
        self._runtime.enable_cheat(slug_or_name)

    def disable_cheat(self, slug_or_name: str) -> None:
        self._runtime.disable_cheat(slug_or_name)

    def add_custom_cheat(self, name: str, code: str) -> None:
        self._runtime.add_custom_cheat(name, code)

    # --- lifecycle ---

    def reset(self) -> None:
        self._runtime.reset()

    def close(self) -> None:
        self._runtime.close()

    def __enter__(self) -> "Controller":
        return self

    def __exit__(self, *exc) -> None:
        self.close()
