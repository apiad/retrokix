# Building the mGBA libretro core

gbax drives mGBA via its libretro core (`mgba_libretro.so`). The wheel will
eventually bundle a prebuilt core; for now, dev work builds from upstream
source.

## When to reach for this

- Setting up gbax for the first time on a Linux box where the bundled core
  isn't available.
- Updating to a newer mGBA.
- Diagnosing emulator-level bugs that may be core-version-specific.

## Procedure

```bash
WORK=/tmp/mgba-build
mkdir -p $WORK && cd $WORK
git clone --depth=1 https://github.com/mgba-emu/mgba.git
cd mgba && mkdir build && cd build

# Inside the gbax venv so cmake from pip is on PATH
source /path/to/gbax/.venv/bin/activate

cmake .. \
  -DBUILD_QT=OFF \
  -DBUILD_SDL=OFF \
  -DBUILD_LIBRETRO=ON \
  -DBUILD_SHARED=OFF \
  -DBUILD_STATIC=OFF \
  -DUSE_LUA=OFF \
  -DUSE_FREETYPE=OFF \
  -DUSE_DISCORD_RPC=OFF \
  -DBUILD_LTO=OFF \
  -DCMAKE_BUILD_TYPE=Release

make mgba_libretro -j$(nproc)

# Output: ./mgba_libretro.so
```

Copy or symlink into the gbax repo for tests:

```bash
cp mgba_libretro.so /path/to/gbax/tests/cores/
```

## Why these specific flags

- **`BUILD_LIBRETRO=ON`** — produces the standalone libretro core (the only
  artifact gbax needs).
- **`BUILD_SHARED=OFF`, `BUILD_STATIC=OFF`** — skips `libmgba.so` /
  `libmgba.a`; the libretro core is self-contained.
- **`BUILD_QT=OFF`, `BUILD_SDL=OFF`** — skip the upstream frontends; gbax
  ships its own SDL frontend and never uses Qt.
- **`USE_LUA=OFF`, `USE_FREETYPE=OFF`, `USE_DISCORD_RPC=OFF`** — disable
  optional dependencies that aren't needed for emulation and that pull in
  freetype, lua, and discord-rpc transitively. The libretro core works
  without them.
- **`BUILD_LTO=OFF`** — mGBA defaults LTO on for Release builds. Combined
  with Arch's system CFLAGS (which also enable LTO), this can produce a
  `.so` that contains only LTO IR bytecode (no real symbols) and won't
  dlopen. Hard-disabling it forces a real ELF shared library.

## Pitfalls observed

- **LTO ⇒ empty `.so`** — if `nm -D mgba_libretro.so | grep retro_` shows
  no symbols, LTO got you. Re-cmake with `-DBUILD_LTO=OFF`.
- **Trying to use mgba's upstream Python bindings (`-DBUILD_PYTHON=ON`)** —
  the cffi-generated binding references symbols that aren't exposed when
  any of the optional features are off, and respects LTO badly. We
  intentionally don't use that path; gbax wraps libretro instead.
