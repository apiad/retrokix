"""High-level emulator runtime.

Wraps the libretro shim and exposes a clean, gbax-shaped API. Single source
of truth for emulator state — both the SDL renderer (for `gbax play`) and
the FastAPI server (for `gbax serve`) are clients of this class.
"""

from __future__ import annotations

import hashlib
import json
import os
import struct
import threading
import time
from enum import Enum
from pathlib import Path

import numpy as np

from gbax import pins as pins_module
from gbax.cheats import Cheat, cheats_for_rom
from gbax.input import Button
from gbax.libretro import LibretroCore


class Mode(str, Enum):
    FREE = "free"
    STEP = "step"


def _default_core_path() -> Path:
    """Find a libretro core, in priority order:

    1. ``$GBAX_CORE_PATH`` — explicit override (power users, alt cores).
    2. Bundled ``gbax/cores/mgba_libretro.so`` — what ``pip install`` ships.
    3. Dev fixture ``tests/cores/mgba_libretro.so`` — built from source via
       ``bin/build-core`` when working on the binding without ``pip install -e .``.
    """
    env = os.environ.get("GBAX_CORE_PATH")
    if env:
        return Path(env)
    from gbax.cores import bundled_core_path
    bundled = bundled_core_path()
    if bundled is not None:
        return bundled
    here = Path(__file__).resolve()
    return here.parent.parent.parent / "tests" / "cores" / "mgba_libretro.so"


class EmulatorRuntime:
    def __init__(
        self,
        rom_path: Path | str,
        core_path: Path | str | None = None,
        save_dir: Path | str | None = None,
        mode: Mode = Mode.STEP,
    ):
        self._rom_path = Path(rom_path)
        self._rom_sha1 = hashlib.sha1(self._rom_path.read_bytes()).hexdigest()
        self._core_path = Path(core_path) if core_path else _default_core_path()
        self._save_dir = Path(save_dir) if save_dir else Path.home() / ".gbax" / "saves"
        if not self._core_path.exists():
            raise FileNotFoundError(
                f"libretro core not found at {self._core_path}. "
                "Options: (1) `pip install gbax` on Linux x86_64 to get the "
                "bundled core, (2) set $GBAX_CORE_PATH to an existing .so, "
                "or (3) build from source with bin/build-core (see "
                "know-how/building-libretro-core.md)."
            )
        self._core = LibretroCore(self._core_path)
        self._core.init()
        self._core.load_rom(self._rom_path)
        self._core.reset()
        self._frame_count = 0
        self._buttons_held: set[Button] = set()
        self._mode = Mode(mode)
        self._speed_multiplier = 1.0
        # In-memory save state slots: slot_id -> (blob, frame_count).
        # Hydrated from disk on init so slots persist across restarts of the same ROM.
        self._slots: dict[int, tuple[bytes, int]] = {}
        self._hydrate_slots_from_disk()
        # Cheat layer — known catalog from libretro-database + currently-active set.
        self._cheat_catalog: list[Cheat] = cheats_for_rom(self._rom_path.name)
        self._active_cheats: dict[str, Cheat] = {}  # slug → Cheat (active = installed + enabled)
        # Per-ROM hotkey pins (F1..F9 → cheat slug), loaded from ~/.gbax/pins/<sha1>.json
        self._pins: dict[str, str] = pins_module.load(self._rom_sha1)
        # Concurrency: ticker thread (Mode.FREE) + API callers both touch the core
        # RLock so /action and /capture_state can hold the lock externally
        # for the duration of an atomic sequence while internal step() /
        # set_buttons() / read_memory() calls re-acquire freely.
        self._lock = threading.RLock()
        self._tick_thread: threading.Thread | None = None
        self._tick_stop = threading.Event()
        # Macro recording / playback state.
        self._recording: list[tuple[int, frozenset[Button]]] | None = None
        self._record_start_frame: int = 0
        self._last_recorded_held: frozenset[Button] = frozenset()
        self._playing_macro: object | None = None  # gbax.macros.Macro
        self._play_start_frame: int = 0
        self._play_event_idx: int = 0
        self._macro_held: frozenset[Button] = frozenset()

    def _hydrate_slots_from_disk(self) -> None:
        """Load every persisted slot from ~/.gbax/saves/<rom-sha1>/ into memory."""
        rom_save_dir = self._save_dir / self._rom_sha1
        if not rom_save_dir.exists():
            return
        for slot in range(1, 10):
            state_path = rom_save_dir / f"slot-{slot}.state"
            meta_path = state_path.with_suffix(".json")
            if not state_path.exists():
                continue
            blob = state_path.read_bytes()
            frame_count = 0
            if meta_path.exists():
                try:
                    frame_count = int(json.loads(meta_path.read_text())["frame_count"])
                except (ValueError, KeyError, json.JSONDecodeError):
                    pass
            self._slots[slot] = (blob, frame_count)

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
        with self._lock:
            for _ in range(frames):
                self._tick_macro_replay_locked()
                effective = self._buttons_held | self._macro_held
                self._core.set_buttons({int(b) for b in effective})
                self._core.run()
                self._frame_count += 1
            # One final replay tick so effective_buttons_held() / is_playing_macro()
            # reflect the state at the current (just-incremented) frame.
            self._tick_macro_replay_locked()

    def _tick_macro_replay_locked(self) -> None:
        """If a macro is playing, advance any events due at the current frame."""
        if self._playing_macro is None:
            return
        macro = self._playing_macro
        elapsed = self._frame_count - self._play_start_frame
        events = macro.events
        while self._play_event_idx < len(events) and events[self._play_event_idx][0] <= elapsed:
            self._macro_held = frozenset(events[self._play_event_idx][1])
            self._play_event_idx += 1
        if elapsed >= macro.total_frames:
            self._playing_macro = None
            self._macro_held = frozenset()
            self._play_event_idx = 0
            self._play_start_frame = 0

    def _record_button_change_locked(self) -> None:
        """Called from set_buttons() under the lock; records a delta if changed."""
        if self._recording is None:
            return
        held_now = frozenset(self._buttons_held)
        if held_now == self._last_recorded_held:
            return
        delta = self._frame_count - self._record_start_frame
        self._recording.append((delta, held_now))
        self._last_recorded_held = held_now

    # ---- macros ----------------------------------------------------------

    def is_recording_macro(self) -> bool:
        return self._recording is not None

    def is_playing_macro(self) -> bool:
        return self._playing_macro is not None

    def effective_buttons_held(self) -> set[Button]:
        """Player held set ∪ active macro's held set. What the core sees."""
        return set(self._buttons_held) | set(self._macro_held)

    def start_recording_macro(self) -> None:
        if self._playing_macro is not None:
            raise RuntimeError("cannot start recording while a macro is playing")
        with self._lock:
            self._recording = []
            self._record_start_frame = self._frame_count
            initial = frozenset(self._buttons_held)
            self._last_recorded_held = initial
            self._recording.append((0, initial))

    def stop_recording_macro(self):
        """Return a gbax.macros.Macro, or None if no recording was active.

        Caller fills in `slot` and `name` at bind time before persisting.
        """
        from datetime import datetime, timezone
        from gbax.macros import Macro

        if self._recording is None:
            return None
        with self._lock:
            events = self._recording
            total = self._frame_count - self._record_start_frame
            self._recording = None
            self._record_start_frame = 0
            self._last_recorded_held = frozenset()
        return Macro(
            slot="",
            name="",
            rom_sha1=self._rom_sha1,
            rom_name=self._rom_path.name,
            recorded_at=datetime.now(timezone.utc),
            total_frames=total,
            events=events,
        )

    def play_macro(self, macro) -> None:
        """Schedule the macro to start playing from the current frame."""
        if self._recording is not None:
            raise RuntimeError("cannot play a macro while recording")
        with self._lock:
            self._playing_macro = macro
            self._play_start_frame = self._frame_count
            self._play_event_idx = 0
            self._macro_held = frozenset()

    def reset(self) -> None:
        with self._lock:
            self._core.reset()
            self._frame_count = 0

    def buttons_held(self) -> set[Button]:
        return set(self._buttons_held)

    def set_buttons(self, buttons: set[Button]) -> None:
        with self._lock:
            self._buttons_held = set(buttons)
            self._core.set_buttons({int(b) for b in buttons})
            self._record_button_change_locked()

    def framebuffer(self) -> np.ndarray:
        """(H, W, 3) uint8 RGB array. Copy of the most recent framebuffer."""
        with self._lock:
            return self._core.framebuffer.copy()

    def read_memory(self, addr: int, length: int) -> bytes:
        with self._lock:
            return self._core.read_bus(addr, length)

    def write_memory(self, addr: int, data: bytes) -> None:
        with self._lock:
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

    # --- mode + speed ---

    @property
    def mode(self) -> Mode:
        return self._mode

    @mode.setter
    def mode(self, value: Mode | str) -> None:
        self._mode = Mode(value)

    @property
    def speed_multiplier(self) -> float:
        return self._speed_multiplier

    @speed_multiplier.setter
    def speed_multiplier(self, value: float) -> None:
        v = float(value)
        if v <= 0:
            raise ValueError(f"speed_multiplier must be > 0, got {v}")
        self._speed_multiplier = v

    # --- save state slots ---

    def save_state_to_slot(self, slot: int) -> bytes:
        if not 1 <= slot <= 9:
            raise ValueError(f"slot must be 1..9, got {slot}")
        with self._lock:
            blob = self._core.serialize()
            self._slots[slot] = (blob, self._frame_count)
            # Persist immediately so slots survive restarts.
            path = self._slot_path(slot)
            path.parent.mkdir(parents=True, exist_ok=True)
            path.write_bytes(blob)
            path.with_suffix(".json").write_text(json.dumps({"frame_count": self._frame_count}))
            return blob

    def load_state_from_slot(self, slot: int) -> None:
        if not 1 <= slot <= 9:
            raise ValueError(f"slot must be 1..9, got {slot}")
        if slot not in self._slots:
            raise KeyError(f"slot {slot} is empty")
        with self._lock:
            blob, frame_count = self._slots[slot]
            self._core.unserialize(blob)
            self._frame_count = frame_count

    def export_state(self) -> bytes:
        with self._lock:
            return self._core.serialize()

    def import_state(self, blob: bytes, frame_count: int = 0) -> None:
        with self._lock:
            self._core.unserialize(blob)
            self._frame_count = frame_count

    def _slot_path(self, slot: int) -> Path:
        return self._save_dir / self._rom_sha1 / f"slot-{slot}.state"

    def persist_slot_to_disk(self, slot: int) -> Path:
        if slot not in self._slots:
            raise KeyError(f"slot {slot} is empty")
        blob, frame_count = self._slots[slot]
        path = self._slot_path(slot)
        path.parent.mkdir(parents=True, exist_ok=True)
        path.write_bytes(blob)
        path.with_suffix(".json").write_text(json.dumps({"frame_count": frame_count}))
        return path

    def load_persistent_slot(self, slot: int) -> None:
        path = self._slot_path(slot)
        if not path.exists():
            raise FileNotFoundError(f"no persistent slot {slot} at {path}")
        blob = path.read_bytes()
        meta = json.loads(path.with_suffix(".json").read_text())
        self._slots[slot] = (blob, meta["frame_count"])
        self.load_state_from_slot(slot)

    # --- cheats ---

    def list_cheats(self) -> list[Cheat]:
        """All cheats catalogued for the running ROM (libretro-database)."""
        return list(self._cheat_catalog)

    def active_cheats(self) -> list[Cheat]:
        """Currently-active (installed + enabled) cheats."""
        return list(self._active_cheats.values())

    def _find_cheat(self, slug_or_name: str) -> Cheat | None:
        key = slug_or_name.lower()
        for c in self._cheat_catalog:
            if c.slug() == key or c.name.lower() == key:
                return c
        return None

    def enable_cheat(self, slug_or_name: str) -> Cheat:
        """Activate a known cheat by slug or name. Returns the Cheat that was enabled."""
        cheat = self._find_cheat(slug_or_name)
        if cheat is None:
            raise KeyError(f"no cheat named {slug_or_name!r} for this ROM")
        with self._lock:
            self._active_cheats[cheat.slug()] = cheat
            self._reinstall_cheats_locked()
        return cheat

    def disable_cheat(self, slug_or_name: str) -> Cheat:
        cheat = self._find_cheat(slug_or_name)
        if cheat is None:
            raise KeyError(f"no cheat named {slug_or_name!r} for this ROM")
        with self._lock:
            self._active_cheats.pop(cheat.slug(), None)
            self._reinstall_cheats_locked()
        return cheat

    def toggle_cheat(self, slug_or_name: str) -> tuple[Cheat, bool]:
        """Return (cheat, enabled_after)."""
        cheat = self._find_cheat(slug_or_name)
        if cheat is None:
            raise KeyError(f"no cheat named {slug_or_name!r} for this ROM")
        slug = cheat.slug()
        with self._lock:
            if slug in self._active_cheats:
                self._active_cheats.pop(slug)
                enabled = False
            else:
                self._active_cheats[slug] = cheat
                enabled = True
            self._reinstall_cheats_locked()
        return cheat, enabled

    def add_custom_cheat(self, name: str, code: str) -> Cheat:
        """Inject an ad-hoc cheat code not in the catalog (unsafe; crashing is your problem)."""
        cheat = Cheat(name=name, code=code)
        with self._lock:
            self._active_cheats[cheat.slug()] = cheat
            self._reinstall_cheats_locked()
        return cheat

    def clear_cheats(self) -> None:
        with self._lock:
            self._active_cheats.clear()
            self._core.cheat_reset()

    def cheat_pins(self) -> dict[str, str]:
        """Return the loaded F-key → cheat-slug map for this ROM (shallow copy)."""
        return dict(self._pins)

    def set_cheat_pin(self, key: str, slug: str) -> None:
        """Persist a pin and update the in-memory map."""
        pins_module.set_pin(self._rom_sha1, key, slug)
        self._pins[key] = slug

    def unset_cheat_pin(self, key: str) -> None:
        pins_module.unset_pin(self._rom_sha1, key)
        self._pins.pop(key, None)

    def _reinstall_cheats_locked(self) -> None:
        """Reset and reinstall every active cheat. Lock-held."""
        self._core.cheat_reset()
        for idx, cheat in enumerate(self._active_cheats.values()):
            self._core.cheat_set(idx, True, cheat.code)

    # --- free-run ticker ---

    def start_free_run_ticker(self) -> None:
        if self._tick_thread is not None and self._tick_thread.is_alive():
            return
        self._tick_stop.clear()
        self._tick_thread = threading.Thread(target=self._tick_loop, daemon=True)
        self._tick_thread.start()

    def stop_free_run_ticker(self) -> None:
        if self._tick_thread is None:
            return
        self._tick_stop.set()
        self._tick_thread.join(timeout=2.0)
        self._tick_thread = None

    def _tick_loop(self) -> None:
        while not self._tick_stop.is_set():
            target_fps = 60.0 * self._speed_multiplier
            frame_time = 1.0 / target_fps
            t0 = time.monotonic()
            with self._lock:
                self._core.run()
                self._frame_count += 1
            elapsed = time.monotonic() - t0
            sleep = frame_time - elapsed
            if sleep > 0:
                time.sleep(sleep)

    def close(self) -> None:
        self.stop_free_run_ticker()
        self._core.deinit()

    def __enter__(self) -> "EmulatorRuntime":
        return self

    def __exit__(self, *exc) -> None:
        self.close()
