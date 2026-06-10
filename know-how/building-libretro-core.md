# Building the mGBA libretro core

The release wheel bundles a prebuilt `mgba_libretro.so` — `pip install gbax`
on Linux x86_64 ships a working core out of the box. This doc covers the
dev path: building the core locally with `bin/build-core` for contributors
hacking on the binding or bumping the pinned mGBA version.

## When to reach for this

- Working on `gbax.libretro` / `gbax.runtime` without `pip install`-ing a
  wheel.
- Bumping the bundled mGBA version (edit `.mgba-version`, rebuild, verify).
- Diagnosing emulator-level bugs that may be core-version-specific.

## Procedure

```bash
bin/build-core
```

That's it. The script:

1. Reads the pinned tag from `.mgba-version` (override with
   `bin/build-core --mgba-version=<tag>`).
2. Clones mGBA shallowly into `/tmp/mgba-build-<tag>` (override with
   `--build-dir=...`).
3. Runs the locked-down cmake config (Libretro core only, no Qt/SDL/Lua/
   Discord/zip/ffmpeg/elf, no LTO,
   `-DCMAKE_POLICY_VERSION_MINIMUM=3.5` for CMake 4.x).
4. Sanity-checks the output `.so`: `retro_run` symbol must be present
   (LTO trap), `ldd` must show only manylinux-baseline libraries.
5. Copies the `.so` to `src/gbax/cores/mgba_libretro.so` and the upstream
   `LICENSE` to `src/gbax/cores/LICENSE.mGBA`.
6. Stamps `MGBA_VERSION` into `src/gbax/cores/__init__.py`.

Both staged artifacts are gitignored — only the release CI publishes
them via the wheel.

The script does NOT touch `tests/cores/mgba_libretro.so`. That file is
tracked in git and only updated by deliberate commits when bumping mGBA.
To refresh it after a bump:

```bash
cp src/gbax/cores/mgba_libretro.so tests/cores/mgba_libretro.so
git add tests/cores/mgba_libretro.so
```

## Bumping mGBA

1. Update `.mgba-version` with the new tag.
2. Run `bin/build-core`.
3. Verify the test suite passes: `pytest -q`.
4. Refresh `tests/cores/mgba_libretro.so` per the snippet above.
5. Commit `.mgba-version`, `src/gbax/cores/__init__.py` (auto-stamped),
   and `tests/cores/mgba_libretro.so`.

## Pitfalls

- **LTO ⇒ empty `.so`** — if `nm -D mgba_libretro.so | grep retro_run`
  shows nothing, LTO got you. The script enforces `-DBUILD_LTO=OFF` and
  asserts the symbol after build; if it ever fires, upstream cmake has
  changed.
- **Outside-baseline libs** — the `ldd` allowlist blocks linking against
  anything the manylinux_2_28_x86_64 baseline doesn't include. If the
  check fails after an mGBA bump, a new `USE_*=OFF` flag may be needed.
- **CMake compatibility** — mGBA's `cmake_minimum_required` predates
  CMake 4's policy cleanup; the script passes
  `-DCMAKE_POLICY_VERSION_MINIMUM=3.5` to keep configure working.
- **Don't use mGBA's upstream Python bindings** (`-DBUILD_PYTHON=ON`) —
  the cffi-generated bindings reference symbols that aren't exposed when
  optional features are off, and they break under LTO. gbax wraps
  libretro directly to dodge this entirely.
