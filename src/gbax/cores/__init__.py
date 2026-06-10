"""Bundled libretro cores shipped with the gbax wheel.

The Linux x86_64 wheel includes a prebuilt `mgba_libretro.so` in this
package. `bundled_core_path()` returns its path if present, else None —
callers (the runtime, tests) fall back to `$GBAX_CORE_PATH` or the
dev-only fixture at `tests/cores/`.

`MGBA_VERSION` is the upstream mGBA tag the bundled binary was built
from. The `bin/build-core` script rewrites this string at build time;
the sentinel below is what an unbundled tree (dev clone, sdist install)
reports.
"""
from __future__ import annotations

from importlib.resources import files as _files_impl
from pathlib import Path

MGBA_VERSION = "unbundled"


def _files(package: str):
    """Indirection so tests can monkeypatch resource lookup."""
    return _files_impl(package)


def bundled_core_path() -> Path | None:
    """Return path to the bundled mgba_libretro.so if present, else None."""
    candidate = Path(str(_files("gbax.cores") / "mgba_libretro.so"))
    return candidate if candidate.exists() else None
