"""Bundled libretro cores shipped with the retrokix wheel.

The Linux x86_64 wheel includes a prebuilt `mgba_libretro.so` in this
package. `bundled_core_path()` returns its path if present, else None —
callers (the runtime, tests) fall back to `$RETROKIX_CORE_PATH` or the
dev-only fixture at `tests/cores/`.

`MGBA_VERSION` / `FCEUMM_VERSION` are the upstream versions the bundled
binaries were built from. The `bin/build-core` and `bin/build-fceumm-core`
scripts rewrite these strings at build time; the sentinels below are
what an unbundled tree (dev clone, sdist install) reports.
"""
from __future__ import annotations

from importlib.resources import files as _files_impl
from pathlib import Path

MGBA_VERSION = "0.10.5"
FCEUMM_VERSION = "c0c52ad0eb36cdbfc66e9bdb72efc83103e85e22"


def _files(package: str):
    """Indirection so tests can monkeypatch resource lookup."""
    return _files_impl(package)


def bundled_core_path(filename: str = "mgba_libretro.so") -> Path | None:
    """Return path to a bundled libretro .so by filename, or None.

    Default `filename` is mGBA for back-compat with the GBA-only era.
    New consoles pass the filename explicitly (the library's CONSOLES
    table records each one's `core_so`)."""
    candidate = Path(str(_files("retrokix.cores") / filename))
    return candidate if candidate.exists() else None
