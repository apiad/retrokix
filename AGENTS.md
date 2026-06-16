# retrokix — agent orientation

`retrokix` is a hacker-first multi-console emulator (GBA + NES + SNES).
Pip-installable Python CLI, native libretro bindings, FastAPI for
scripted/AI play, a hub command that serves the whole library in a
browser. Linux-only v1.

## Architecture

See `vault/Atlas/Architecture/2026-06-09-retrokix-design.md` (canonical spec).

`retrokix.libretro.LibretroCore` (`src/retrokix/libretro.py`) is the thin cffi
binding to a libretro core's `.so` (mGBA, FCEUmm, snes9x, selected by ROM
extension). Single `EmulatorRuntime` (`src/retrokix/runtime.py`) wraps that.
Clients of the runtime: SDL renderer (`render/sdl.py`) for `retrokix play`,
FastAPI server (`api/`) for headless / web play. The hub
(`src/retrokix/hub/`) is a separate small FastAPI app that spawns one
`retrokix play --no-sdl` subprocess per launched game; it doesn't host
any runtime itself. CLI dispatch in `cli.py`.

We don't depend on mGBA's upstream Python bindings — they're patchy on
modern toolchains. The libretro ABI is stable, well-documented, and lets
retrokix swap cores later (vba-next, gpsp, etc.).

## Building the libretro core

See `know-how/building-libretro-core.md`. Until the wheel bundles it, dev
machines build `mgba_libretro.so` from upstream mGBA and drop it in
`tests/cores/`.

## Conventions

- Commit straight to `main`. Conventional commits (`feat:`, `fix:`, `chore:`, `test:`).
- TDD: tests first when possible. Smoke tests against `tests/fixtures/test.gba`.
- Lint: `ruff check src/ tests/`. Format: `ruff format src/ tests/`.
- Type check: `mypy src/retrokix`.

## Know-how

Add per-procedure docs under `know-how/` as patterns emerge.
