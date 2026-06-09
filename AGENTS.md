# gbax — agent orientation

`gbax` is a hacker-first GBA emulator. Pip-installable Python CLI, native
libmgba bindings, FastAPI for scripted/AI play. Linux-only v1.

## Architecture

See `vault/Atlas/Architecture/2026-06-09-gbax-design.md` (canonical spec).

`gbax.libretro.LibretroCore` (`src/gbax/libretro.py`) is the thin cffi
binding to a libretro core's `.so` — currently mGBA's. Single
`EmulatorRuntime` (`src/gbax/runtime.py`) wraps that. Two clients of the
runtime: SDL renderer (`render/sdl.py`) for `gbax play`, FastAPI server
(`api/`) for `gbax serve`. CLI dispatch in `cli.py`.

We don't depend on mGBA's upstream Python bindings — they're patchy on
modern toolchains. The libretro ABI is stable, well-documented, and lets
gbax swap cores later (vba-next, gpsp, etc.).

## Building the libretro core

See `know-how/building-libretro-core.md`. Until the wheel bundles it, dev
machines build `mgba_libretro.so` from upstream mGBA and drop it in
`tests/cores/`.

## Conventions

- Commit straight to `main`. Conventional commits (`feat:`, `fix:`, `chore:`, `test:`).
- TDD: tests first when possible. Smoke tests against `tests/fixtures/test.gba`.
- Lint: `ruff check src/ tests/`. Format: `ruff format src/ tests/`.
- Type check: `mypy src/gbax`.

## Know-how

Add per-procedure docs under `know-how/` as patterns emerge.
