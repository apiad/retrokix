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

    def close(self) -> None:
        self._runtime.close()

    def __enter__(self) -> "Controller":
        return self

    def __exit__(self, *exc) -> None:
        self.close()
