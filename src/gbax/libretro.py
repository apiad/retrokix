"""Minimal libretro core wrapper.

A thin cffi binding to the libretro ABI — just enough surface for gbax:
load a core .so, load a ROM, step frames, read/write RAM, serialize state,
push button input, capture framebuffer.

We hardcode the cdef strings instead of preprocessing libretro.h with gcc
(as some Python libretro wrappers do) — it's a tiny, stable ABI.

References:
- libretro ABI: https://github.com/libretro/RetroArch/blob/master/libretro-common/include/libretro.h
"""

from __future__ import annotations

import struct
from pathlib import Path

import numpy as np
from cffi import FFI


GBA_WIDTH = 240
GBA_HEIGHT = 160


# Pixel formats (libretro enum)
_PIXEL_FORMAT_0RGB1555 = 0
_PIXEL_FORMAT_XRGB8888 = 1
_PIXEL_FORMAT_RGB565 = 2

# Environment commands we handle
_ENV_SET_PIXEL_FORMAT = 10
_ENV_GET_SYSTEM_DIRECTORY = 9
_ENV_GET_SAVE_DIRECTORY = 31
_ENV_GET_VARIABLE = 15
_ENV_GET_VARIABLE_UPDATE = 17
_ENV_GET_LOG_INTERFACE = 27
_ENV_SET_MEMORY_MAPS = 36

# retro_memdesc flags
_MEMDESC_CONST = 1 << 0

# Device / button IDs
_DEVICE_JOYPAD = 1

# Button index → libretro retro_device_id_joypad value
BUTTON_IDS = {
    "B":      0,
    "Y":      1,
    "SELECT": 2,
    "START":  3,
    "UP":     4,
    "DOWN":   5,
    "LEFT":   6,
    "RIGHT":  7,
    "A":      8,
    "X":      9,
    "L":      10,
    "R":      11,
    "L2":     12,
    "R2":     13,
    "L3":     14,
    "R3":     15,
}

# Memory regions
MEMORY_SAVE_RAM   = 0
MEMORY_RTC        = 1
MEMORY_SYSTEM_RAM = 2
MEMORY_VIDEO_RAM  = 3


_CDEF = """
typedef uint64_t retro_usec_t;
typedef uintptr_t size_t;

struct retro_game_info {
    const char* path;
    const void* data;
    size_t size;
    const char* meta;
};

struct retro_game_geometry {
    unsigned base_width;
    unsigned base_height;
    unsigned max_width;
    unsigned max_height;
    float aspect_ratio;
};

struct retro_system_timing {
    double fps;
    double sample_rate;
};

struct retro_system_info {
    const char* library_name;
    const char* library_version;
    const char* valid_extensions;
    bool need_fullpath;
    bool block_extract;
};

struct retro_system_av_info {
    struct retro_game_geometry geometry;
    struct retro_system_timing timing;
};

struct retro_variable {
    const char* key;
    const char* value;
};

struct retro_memory_descriptor {
    uint64_t flags;
    void* ptr;
    size_t offset;
    size_t start;
    size_t select;
    size_t disconnect;
    size_t len;
    const char* addrspace;
};

struct retro_memory_map {
    const struct retro_memory_descriptor* descriptors;
    unsigned num_descriptors;
};

typedef bool (*retro_environment_t)(unsigned cmd, void* data);
typedef void (*retro_video_refresh_t)(const void* data, unsigned width, unsigned height, size_t pitch);
typedef void (*retro_audio_sample_t)(int16_t left, int16_t right);
typedef size_t (*retro_audio_sample_batch_t)(const int16_t* data, size_t frames);
typedef void (*retro_input_poll_t)(void);
typedef int16_t (*retro_input_state_t)(unsigned port, unsigned device, unsigned index, unsigned id);

void retro_set_environment(retro_environment_t);
void retro_set_video_refresh(retro_video_refresh_t);
void retro_set_audio_sample(retro_audio_sample_t);
void retro_set_audio_sample_batch(retro_audio_sample_batch_t);
void retro_set_input_poll(retro_input_poll_t);
void retro_set_input_state(retro_input_state_t);

void retro_init(void);
void retro_deinit(void);
unsigned retro_api_version(void);

void retro_get_system_info(struct retro_system_info*);
void retro_get_system_av_info(struct retro_system_av_info*);
void retro_set_controller_port_device(unsigned port, unsigned device);

void retro_reset(void);
void retro_run(void);

size_t retro_serialize_size(void);
bool retro_serialize(void* data, size_t size);
bool retro_unserialize(const void* data, size_t size);

void retro_cheat_reset(void);
void retro_cheat_set(unsigned index, bool enabled, const char* code);

bool retro_load_game(const struct retro_game_info*);
void retro_unload_game(void);

unsigned retro_get_region(void);
void* retro_get_memory_data(unsigned id);
size_t retro_get_memory_size(unsigned id);
"""


class LibretroCore:
    """Thin libretro wrapper over a single core .so.

    Owns:
    - the dlopened core
    - the cffi callbacks (kept alive by reference)
    - the most-recent framebuffer (captured on retro_video_refresh)
    - the currently-held button mask
    """

    def __init__(self, core_path: str | Path):
        self._ffi = FFI()
        self._ffi.cdef(_CDEF)
        self._lib = self._ffi.dlopen(str(core_path))

        self._pixel_format = _PIXEL_FORMAT_0RGB1555  # libretro default
        self._buttons_pressed: set[int] = set()
        self._framebuffer: np.ndarray = np.zeros((GBA_HEIGHT, GBA_WIDTH, 3), dtype=np.uint8)
        self._system_dir = self._ffi.new("char[]", b".")
        self._save_dir = self._ffi.new("char[]", b".")
        # Memory map populated by SET_MEMORY_MAPS callback. List of dicts:
        # {'start': uint32, 'len': uint32, 'select': uint32, 'flags': int, 'ptr': cdata}
        self._mem_descriptors: list[dict] = []
        # Audio sink — set by callers wanting samples. Receives bytes of
        # interleaved 16-bit stereo PCM at retro_system_av_info().timing.sample_rate.
        self.on_audio: object | None = None  # callable(bytes) -> None | None

        # Keep callback refs alive — cffi callbacks die if their Python wrappers are GC'd
        self._cb_env    = self._ffi.callback("retro_environment_t", self._on_environment)
        self._cb_video  = self._ffi.callback("retro_video_refresh_t", self._on_video_refresh)
        self._cb_audio  = self._ffi.callback("retro_audio_sample_t", self._on_audio_sample)
        self._cb_audioB = self._ffi.callback("retro_audio_sample_batch_t", self._on_audio_sample_batch)
        self._cb_poll   = self._ffi.callback("retro_input_poll_t", self._on_input_poll)
        self._cb_state  = self._ffi.callback("retro_input_state_t", self._on_input_state)

        self._lib.retro_set_environment(self._cb_env)
        self._lib.retro_set_video_refresh(self._cb_video)
        self._lib.retro_set_audio_sample(self._cb_audio)
        self._lib.retro_set_audio_sample_batch(self._cb_audioB)
        self._lib.retro_set_input_poll(self._cb_poll)
        self._lib.retro_set_input_state(self._cb_state)

        self._initialized = False
        self._loaded = False

    def init(self) -> None:
        if self._initialized:
            return
        self._lib.retro_init()
        self._initialized = True

    def deinit(self) -> None:
        if self._loaded:
            self._lib.retro_unload_game()
            self._loaded = False
        if self._initialized:
            self._lib.retro_deinit()
            self._initialized = False

    def load_rom(self, rom_path: str | Path) -> None:
        info = self._ffi.new("struct retro_game_info *")
        rom_bytes = Path(rom_path).read_bytes()
        path_c = self._ffi.new("char[]", str(rom_path).encode("utf-8"))
        data_c = self._ffi.new("char[]", rom_bytes)
        info.path = path_c
        info.data = data_c
        info.size = len(rom_bytes)
        info.meta = self._ffi.NULL
        ok = self._lib.retro_load_game(info)
        if not ok:
            raise RuntimeError(f"retro_load_game failed for {rom_path}")
        # Keep these alive until unload
        self._rom_path_c = path_c
        self._rom_data_c = data_c
        self._loaded = True

    def reset(self) -> None:
        self._lib.retro_reset()

    def run(self) -> None:
        self._lib.retro_run()

    @property
    def framebuffer(self) -> np.ndarray:
        """(H, W, 3) uint8 RGB array. Updated each retro_run on frames the core emits."""
        return self._framebuffer

    def get_memory(self, region: int = MEMORY_SYSTEM_RAM) -> memoryview:
        size = self._lib.retro_get_memory_size(region)
        if size == 0:
            return memoryview(b"")
        ptr = self._lib.retro_get_memory_data(region)
        if ptr == self._ffi.NULL:
            return memoryview(b"")
        return self._ffi.buffer(ptr, size)

    def read_memory(self, region: int, offset: int, length: int) -> bytes:
        buf = self.get_memory(region)
        return bytes(buf[offset:offset + length])

    def write_memory(self, region: int, offset: int, data: bytes) -> None:
        buf = self.get_memory(region)
        buf[offset:offset + len(data)] = data

    def serialize(self) -> bytes:
        size = self._lib.retro_serialize_size()
        out = self._ffi.new(f"char[{size}]")
        ok = self._lib.retro_serialize(out, size)
        if not ok:
            raise RuntimeError("retro_serialize failed")
        return bytes(self._ffi.buffer(out, size))

    def unserialize(self, blob: bytes) -> None:
        buf = self._ffi.new(f"char[{len(blob)}]", blob)
        ok = self._lib.retro_unserialize(buf, len(blob))
        if not ok:
            raise RuntimeError("retro_unserialize failed")

    def set_buttons(self, button_ids: set[int]) -> None:
        """Set the held buttons (libretro retro_device_id_joypad values)."""
        self._buttons_pressed = set(button_ids)

    # --- libretro callbacks ---

    def _on_environment(self, cmd: int, data) -> bool:
        cmd = cmd & 0xFFFF  # strip experimental/private flags
        if cmd == _ENV_SET_PIXEL_FORMAT:
            self._pixel_format = self._ffi.cast("int *", data)[0]
            return True
        if cmd == _ENV_GET_SYSTEM_DIRECTORY:
            self._ffi.cast("const char **", data)[0] = self._system_dir
            return True
        if cmd == _ENV_GET_SAVE_DIRECTORY:
            self._ffi.cast("const char **", data)[0] = self._save_dir
            return True
        if cmd == _ENV_SET_MEMORY_MAPS:
            mmap = self._ffi.cast("struct retro_memory_map *", data)
            self._mem_descriptors = []
            for i in range(mmap.num_descriptors):
                d = mmap.descriptors[i]
                self._mem_descriptors.append({
                    "start": int(d.start),
                    "len": int(d.len),
                    "select": int(d.select),
                    "flags": int(d.flags),
                    "ptr": d.ptr,
                })
            return True
        return False

    def _resolve_address(self, addr: int) -> tuple[object, int, int] | None:
        """Map a bus address to (descriptor_ptr, offset_within_block, available_length).

        Returns None if no descriptor covers this address.
        """
        for d in self._mem_descriptors:
            if d["len"] == 0 or d["ptr"] == self._ffi.NULL:
                continue
            start = d["start"]
            select = d["select"] or 0xFFFFFFFF
            # An address matches a descriptor when (addr & select) == (start & select).
            if (addr & select) != (start & select):
                continue
            offset = (addr - start) & ~select & 0xFFFFFFFF  # masked range
            # Within the descriptor's range. For most GBA blocks, select=0xFF000000
            # and (addr - start) gives the offset directly when start has the same high bits.
            offset = (addr - start)
            if 0 <= offset < d["len"]:
                return (d["ptr"], offset, d["len"] - offset)
        return None

    def read_bus(self, addr: int, length: int) -> bytes:
        """Read from a GBA bus address. Walks descriptors set up by mGBA's SET_MEMORY_MAPS."""
        loc = self._resolve_address(addr)
        if loc is None:
            raise ValueError(f"no memory descriptor covers 0x{addr:08X}")
        ptr, offset, available = loc
        if length > available:
            raise ValueError(f"read of {length} at 0x{addr:08X} crosses block boundary (have {available})")
        buf = self._ffi.buffer(self._ffi.cast("unsigned char *", ptr) + offset, length)
        return bytes(buf)

    def write_bus(self, addr: int, data: bytes) -> None:
        loc = self._resolve_address(addr)
        if loc is None:
            raise ValueError(f"no memory descriptor covers 0x{addr:08X}")
        ptr, offset, available = loc
        # Walk the descriptor table again to check CONST flag
        for d in self._mem_descriptors:
            if d["ptr"] == ptr and (d["flags"] & _MEMDESC_CONST):
                raise PermissionError(f"address 0x{addr:08X} is in a CONST region")
        if len(data) > available:
            raise ValueError(f"write of {len(data)} at 0x{addr:08X} crosses block boundary")
        buf = self._ffi.buffer(self._ffi.cast("unsigned char *", ptr) + offset, len(data))
        buf[:len(data)] = data

    def _on_video_refresh(self, data, width: int, height: int, pitch: int) -> None:
        if data == self._ffi.NULL or width == 0 or height == 0:
            return
        # Pitch is bytes per row, not necessarily width*bpp — slice by pitch.
        raw = self._ffi.buffer(self._ffi.cast("unsigned char *", data), height * pitch)
        if self._pixel_format == _PIXEL_FORMAT_RGB565:
            stride_px = pitch // 2
            arr = np.frombuffer(raw, dtype=np.uint16).reshape((height, stride_px))[:, :width]
            r = ((arr >> 11) & 0x1F).astype(np.uint8)
            g = ((arr >> 5) & 0x3F).astype(np.uint8)
            b = (arr & 0x1F).astype(np.uint8)
            fb = np.empty((height, width, 3), dtype=np.uint8)
            fb[..., 0] = (r.astype(np.uint16) * 255 // 31).astype(np.uint8)
            fb[..., 1] = (g.astype(np.uint16) * 255 // 63).astype(np.uint8)
            fb[..., 2] = (b.astype(np.uint16) * 255 // 31).astype(np.uint8)
        elif self._pixel_format == _PIXEL_FORMAT_0RGB1555:
            stride_px = pitch // 2
            arr = np.frombuffer(raw, dtype=np.uint16).reshape((height, stride_px))[:, :width]
            r = ((arr >> 10) & 0x1F).astype(np.uint8)
            g = ((arr >> 5) & 0x1F).astype(np.uint8)
            b = (arr & 0x1F).astype(np.uint8)
            fb = np.empty((height, width, 3), dtype=np.uint8)
            fb[..., 0] = (r.astype(np.uint16) * 255 // 31).astype(np.uint8)
            fb[..., 1] = (g.astype(np.uint16) * 255 // 31).astype(np.uint8)
            fb[..., 2] = (b.astype(np.uint16) * 255 // 31).astype(np.uint8)
        elif self._pixel_format == _PIXEL_FORMAT_XRGB8888:
            stride_px = pitch // 4
            arr = np.frombuffer(raw, dtype=np.uint32).reshape((height, stride_px))[:, :width]
            fb = np.empty((height, width, 3), dtype=np.uint8)
            fb[..., 0] = (arr >> 16) & 0xFF
            fb[..., 1] = (arr >> 8) & 0xFF
            fb[..., 2] = arr & 0xFF
        else:
            return
        self._framebuffer = fb

    def _on_audio_sample(self, left: int, right: int) -> None:
        if self.on_audio is not None:
            self.on_audio(struct.pack("<hh", left, right))

    def _on_audio_sample_batch(self, data, frames: int) -> int:
        if self.on_audio is not None and frames > 0:
            self.on_audio(bytes(self._ffi.buffer(data, frames * 4)))
        return frames

    def _on_input_poll(self) -> None:
        pass

    def _on_input_state(self, port: int, device: int, index: int, id_: int) -> int:
        if port != 0 or index != 0 or device != _DEVICE_JOYPAD:
            return 0
        return 1 if id_ in self._buttons_pressed else 0
