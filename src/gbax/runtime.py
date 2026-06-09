"""High-level emulator runtime.

Wraps the libretro shim and exposes a clean, gbax-shaped API. Single source
of truth for emulator state — both the SDL renderer (for `gbax play`) and
the FastAPI server (for `gbax serve`) are clients of this class.
"""

from __future__ import annotations

import hashlib
import os
import struct
from pathlib import Path

import numpy as np

from gbax.libretro import GBA_HEIGHT, GBA_WIDTH, LibretroCore


def _default_core_path() -> Path:
    """Find a libretro core, in priority order: env var → known dev path."""
    env = os.environ.get("GBAX_CORE_PATH")
    if env:
        return Path(env)
    # Fall back to the dev fixture so `gbax play` works out of the box during
    # development. Wheel installs will ship a core into ~/.gbax/cores/.
    here = Path(__file__).resolve()
    repo_test_core = here.parent.parent.parent / "tests" / "cores" / "mgba_libretro.so"
    return repo_test_core


class EmulatorRuntime:
    def __init__(self, rom_path: Path | str, core_path: Path | str | None = None):
        self._rom_path = Path(rom_path)
        self._rom_sha1 = hashlib.sha1(self._rom_path.read_bytes()).hexdigest()
        self._core_path = Path(core_path) if core_path else _default_core_path()
        if not self._core_path.exists():
            raise FileNotFoundError(
                f"libretro core not found at {self._core_path}; "
                "build it (see know-how/building-libretro-core.md) "
                "or set GBAX_CORE_PATH"
            )
        self._core = LibretroCore(self._core_path)
        self._core.init()
        self._core.load_rom(self._rom_path)
        self._core.reset()
        self._frame_count = 0

    @property
    def rom_path(self) -> Path:
        return self._rom_path

    @property
    def rom_sha1(self) -> str:
        return self._rom_sha1

    @property
    def frame_count(self) -> int:
        return self._frame_count

    def step(self, frames: int = 1) -> None:
        if frames < 1:
            raise ValueError(f"frames must be >= 1, got {frames}")
        for _ in range(frames):
            self._core.run()
            self._frame_count += 1

    def reset(self) -> None:
        self._core.reset()
        self._frame_count = 0

    def framebuffer(self) -> np.ndarray:
        """(H, W, 3) uint8 RGB array. Updated by the most recent step()."""
        return self._core.framebuffer

    def read_memory(self, addr: int, length: int) -> bytes:
        return self._core.read_bus(addr, length)

    def write_memory(self, addr: int, data: bytes) -> None:
        self._core.write_bus(addr, data)

    def read_u8(self, addr: int) -> int:
        return self.read_memory(addr, 1)[0]

    def read_u16(self, addr: int) -> int:
        return struct.unpack("<H", self.read_memory(addr, 2))[0]

    def read_u32(self, addr: int) -> int:
        return struct.unpack("<I", self.read_memory(addr, 4))[0]

    def write_u8(self, addr: int, value: int) -> None:
        self.write_memory(addr, struct.pack("<B", value & 0xFF))

    def write_u16(self, addr: int, value: int) -> None:
        self.write_memory(addr, struct.pack("<H", value & 0xFFFF))

    def write_u32(self, addr: int, value: int) -> None:
        self.write_memory(addr, struct.pack("<I", value & 0xFFFFFFFF))

    def close(self) -> None:
        self._core.deinit()

    def __enter__(self) -> "EmulatorRuntime":
        return self

    def __exit__(self, *exc) -> None:
        self.close()
