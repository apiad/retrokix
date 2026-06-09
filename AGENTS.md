# gbax — agent orientation

`gbax` is a hacker-first GBA emulator. Pip-installable Python CLI, native
libmgba bindings, FastAPI for scripted/AI play. Linux-only v1.

## Architecture

See `vault/Atlas/Architecture/2026-06-09-gbax-design.md` (canonical spec).

Single `EmulatorRuntime` (`src/gbax/runtime.py`) wraps libmgba. Two clients:
SDL renderer (`render/sdl.py`) for `gbax play`, FastAPI server (`api/`) for
`gbax serve`. CLI dispatch in `cli.py`.

## Conventions

- Commit straight to `main`. Conventional commits (`feat:`, `fix:`, `chore:`, `test:`).
- TDD: tests first when possible. Smoke tests against `tests/fixtures/test.gba`.
- Lint: `ruff check src/ tests/`. Format: `ruff format src/ tests/`.
- Type check: `mypy src/gbax`.

## Know-how

Add per-procedure docs under `know-how/` as patterns emerge.
