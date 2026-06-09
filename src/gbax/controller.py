"""High-level, blocking, pythonic facade over EmulatorRuntime.

This is the public Python API for headless gbax automation. Scenarios,
plugins (future), and ad-hoc scripts all use it. Internally it wraps an
EmulatorRuntime in STEP mode and exposes blocking primitives.

Equivalent to `gbax serve` but in-process — no HTTP round-trip.
"""

from __future__ import annotations

from pathlib import Path

import numpy as np

from gbax.runtime import EmulatorRuntime, Mode


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

    def close(self) -> None:
        self._runtime.close()

    def __enter__(self) -> "Controller":
        return self

    def __exit__(self, *exc) -> None:
        self.close()
