# Installing retrokix

```
pip install retrokix
```

On Linux x86_64, that's the whole install. The wheel ships a prebuilt
`mgba_libretro.so` inside it. `retrokix play emerald` works on a fresh box
with no cmake, no apt-get, no `$RETROKIX_CORE_PATH` to set.

This page covers what the wheel actually contains, how to point at a
different core, and what to do if your platform isn't on the supported
list.

## What ships in the wheel

```
retrokix-X.Y.Z-py3-none-manylinux_2_28_x86_64.whl
├── retrokix/                            (the Python package)
│   ├── cli.py, runtime.py, …
│   ├── data/                        (No-Intro ROM index, cheats DB, reference scenarios)
│   └── cores/
│       ├── __init__.py              (exposes MGBA_VERSION)
│       ├── mgba_libretro.so         (~3 MB, the libretro core)
│       └── LICENSE.mGBA             (MPL-2.0, upstream verbatim)
```

The bundled `mgba_libretro.so` is built from
[mgba-emu/mgba](https://github.com/mgba-emu/mgba) at the tag pinned in
[`.mgba-version`](https://github.com/apiad/retrokix/blob/main/.mgba-version) — currently `0.10.5`. You can check
which mGBA your installed retrokix is using:

```python
>>> from retrokix.cores import MGBA_VERSION
>>> MGBA_VERSION
'0.10.5'
```

The binary is compiled inside a `manylinux_2_28_x86_64` container —
which means it links only against glibc 2.28 or newer. Concretely:
**Ubuntu 20.04+, Debian 11+, Fedora 30+, RHEL/CentOS 8+, Arch, recent
NixOS** — anything shipping a modern glibc since late 2018. Older
distros fall through to the sdist path (see below).

## Lookup order at runtime

When `retrokix` needs to load the emulator core, it checks in this order:

1. **`$RETROKIX_CORE_PATH`** — explicit override. Always wins.
2. **Bundled core** — `retrokix/cores/mgba_libretro.so` inside the installed
   package. This is what `pip install retrokix` ships.
3. **Dev fallback** — `tests/cores/mgba_libretro.so` relative to the
   source checkout. Only relevant when running from a `pip install -e .`
   editable install without a bundled wheel.

So if you want to swap in a custom build — debug symbols, a different
mGBA version, or an entirely different libretro core like `vba-next` —
point the env var at it:

```bash
export RETROKIX_CORE_PATH=/path/to/your/mgba_libretro.so
retrokix play emerald                # uses your build
unset RETROKIX_CORE_PATH
retrokix play emerald                # back to the bundled one
```

If the chosen `.so` is missing or unreadable, `retrokix` fails fast at
emulator startup with the path it tried and instructions to recover.

## Supported platforms

| Platform              | What `pip install retrokix` resolves to     | Status                 |
| --------------------- | --------------------------------------- | ---------------------- |
| Linux x86_64, glibc ≥ 2.28 | `…-manylinux_2_28_x86_64.whl`     | Supported              |
| Linux x86_64, older glibc  | sdist (`.tar.gz`)                 | Use `$RETROKIX_CORE_PATH`  |
| Linux aarch64              | sdist                             | PR-welcome             |
| macOS (any)                | sdist                             | PR-welcome             |
| Windows (any)              | sdist                             | PR-welcome             |

The sdist installs cleanly on every platform pip supports, but it ships
no `mgba_libretro.so`. Running `retrokix play` without `$RETROKIX_CORE_PATH`
will exit with:

```
FileNotFoundError: libretro core not found at <path>.
Options: (1) `pip install retrokix` on Linux x86_64 to get the bundled core,
(2) set $RETROKIX_CORE_PATH to an existing .so, or (3) build from source
with bin/build-core (see know-how/building-libretro-core.md).
```

For aarch64 / macOS / Windows, point `$RETROKIX_CORE_PATH` at a `.so` (or
`.dylib` / `.dll`) you've built yourself. The libretro ABI is the
same — `retrokix` doesn't care how the core was produced.

## Verifying your install

```bash
$ retrokix --help                                          # CLI works
$ python -c "from retrokix.cores import bundled_core_path; print(bundled_core_path())"
/.../site-packages/retrokix/cores/mgba_libretro.so          # bundle is present
$ python -c "from retrokix.cores import MGBA_VERSION; print(MGBA_VERSION)"
0.10.5                                                  # pinned mGBA tag
```

If the second command prints `None`, the bundle isn't present — you're
either on the sdist path (non-Linux-x86_64) or in an editable install
without a built core.

## Bumping the bundled mGBA version

A new mGBA release lands → bump the bundled core in three steps.
[`know-how/building-libretro-core.md`](https://github.com/apiad/retrokix/blob/main/know-how/building-libretro-core.md)
has the full procedure; the short version:

1. Edit `.mgba-version` with the new tag.
2. `bin/build-core` — produces a fresh `.so` and stamps `MGBA_VERSION`.
3. `cp src/retrokix/cores/mgba_libretro.so tests/cores/mgba_libretro.so` —
   refresh the tracked test fixture.
4. `pytest -q` — confirms the test ROM still steps cleanly under the
   new mGBA.
5. Commit `.mgba-version`, `src/retrokix/cores/__init__.py`,
   `tests/cores/mgba_libretro.so`. Tag a new retrokix release; CI rebuilds
   the wheel inside `manylinux_2_28_x86_64` and publishes to PyPI.

## License & compliance

The bundled `mgba_libretro.so` is Mozilla Public License 2.0, same as
retrokix itself. The wheel ships the upstream mGBA license at
`retrokix/cores/LICENSE.mGBA` to satisfy MPL §3.2 (the "inform recipients"
clause). MPL is file-scoped — using a bundled MPL binary doesn't pull
retrokix's own code under any additional copyleft obligations.
