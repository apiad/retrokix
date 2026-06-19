"""Per-ROM cover/screenshot/title art, sourced from libretro-thumbnails.

libretro-thumbnails (https://github.com/libretro-thumbnails/) is a
crowd-maintained set of one repo per system, each carrying three
subfolders: Named_Boxarts/, Named_Snaps/, Named_Titles/. File names
match the No-Intro filename (minus extension) with filesystem-unsafe
characters substituted to underscores.

We cache fetched art under ~/.retrokix/art/<console>/<sanitized>/
keyed by the sanitized ROM title (no extension). Cache is best-effort:
missing-from-upstream titles are remembered with a sentinel zero-byte
file so we don't re-hit GitHub for known misses.
"""
from __future__ import annotations

import threading
import urllib.error
import urllib.parse
import urllib.request
from pathlib import Path

from retrokix.library import CONSOLES, console_for_path


DEFAULT_ART_ROOT = Path.home() / ".retrokix" / "art"
UA = "retrokix-art/0.1 (+https://github.com/apiad/retrokix)"
TIMEOUT = 10.0
KINDS: tuple[str, ...] = ("snap", "boxart", "title")
_KIND_TO_DIR = {
    "snap": "Named_Snaps",
    "boxart": "Named_Boxarts",
    "title": "Named_Titles",
}


def _sanitize_title(title: str) -> str:
    """Apply libretro-thumbnails' filename substitutions.

    Per the libretro-thumbnails README, these characters are replaced
    with `_` because not all target filesystems accept them:
    &  *  /  :  `  <  >  ?  \\  |  "
    """
    out = []
    for c in title:
        if c in '&*/:`<>?\\|"':
            out.append("_")
        else:
            out.append(c)
    return "".join(out)


def _rom_title(rom_path: Path) -> str:
    """Strip the ROM extension to get the title libretro-thumbnails uses."""
    return rom_path.stem


def art_dir_for_rom(rom_path: Path, *, root: Path | None = None) -> Path | None:
    """Directory where this ROM's art lives (snap.png, boxart.png, title.png).

    Returns None if we don't recognise the ROM's console.
    """
    console = console_for_path(rom_path)
    if console is None:
        return None
    base = Path(root) if root else DEFAULT_ART_ROOT
    return base / console / _sanitize_title(_rom_title(rom_path))


def art_paths_for_rom(
    rom_path: Path, *, root: Path | None = None
) -> dict[str, Path] | None:
    """{kind: cached_path} for every supported art kind, regardless of
    whether the cache currently holds bytes or a known-missing sentinel.

    Returns None if we don't recognise the ROM's console.
    """
    d = art_dir_for_rom(rom_path, root=root)
    if d is None:
        return None
    return {k: d / f"{k}.png" for k in KINDS}


def _build_url(console: str, title: str, kind: str) -> str:
    repo = CONSOLES[console].libretro_thumbnails_repo
    subdir = _KIND_TO_DIR[kind]
    fname = urllib.parse.quote(_sanitize_title(title) + ".png")
    return (
        f"https://raw.githubusercontent.com/libretro-thumbnails/"
        f"{repo}/master/{subdir}/{fname}"
    )


def _fetch(url: str) -> bytes | None:
    """Return PNG bytes on 200, None on 404, raise on other errors."""
    req = urllib.request.Request(url, headers={"User-Agent": UA})
    try:
        with urllib.request.urlopen(req, timeout=TIMEOUT) as r:
            return r.read()
    except urllib.error.HTTPError as e:
        if e.code == 404:
            return None
        raise


def fetch_art_for_rom(
    rom_path: Path,
    *,
    root: Path | None = None,
    force: bool = False,
    kinds: tuple[str, ...] = KINDS,
) -> dict[str, str]:
    """Fetch missing art for a ROM. Returns {kind: status} where status is
    one of: 'hit' (just fetched), 'cached' (already present), 'missing'
    (404 upstream, sentinel written), 'unknown_console', 'error'.

    Best-effort: a fetch error for one kind doesn't abort the others;
    likewise, errors don't propagate to callers since cover art is
    decoration.
    """
    out: dict[str, str] = {}
    console = console_for_path(rom_path)
    if console is None or console not in CONSOLES:
        return {k: "unknown_console" for k in kinds}

    art_dir = art_dir_for_rom(rom_path, root=root)
    assert art_dir is not None  # console_for_path returned, so this can't be None
    art_dir.mkdir(parents=True, exist_ok=True)
    title = _rom_title(rom_path)

    for kind in kinds:
        target = art_dir / f"{kind}.png"
        if target.exists() and not force:
            out[kind] = "cached"
            continue
        url = _build_url(console, title, kind)
        try:
            data = _fetch(url)
        except Exception:
            out[kind] = "error"
            continue
        if data is None:
            # Sentinel: zero-byte file marks "upstream said 404"
            target.write_bytes(b"")
            out[kind] = "missing"
        else:
            target.write_bytes(data)
            out[kind] = "hit"
    return out


def fetch_art_for_rom_background(rom_path: Path) -> None:
    """Fire-and-forget background fetch. Used by the ROM downloader so a
    successful ROM download is never blocked or failed by an art fetch
    issue. Exceptions are swallowed.
    """
    def _run() -> None:
        try:
            fetch_art_for_rom(rom_path)
        except Exception:
            pass

    t = threading.Thread(target=_run, name=f"art-fetch-{rom_path.stem}", daemon=True)
    t.start()


def art_path_if_present(
    rom_path: Path, kind: str, *, root: Path | None = None
) -> Path | None:
    """Return the cached art path for (rom, kind) only if the cache holds
    non-empty bytes (not the sentinel, not absent). Used by the hub to
    decide whether to render an <img> at all.
    """
    if kind not in _KIND_TO_DIR:
        return None
    paths = art_paths_for_rom(rom_path, root=root)
    if paths is None:
        return None
    p = paths.get(kind)
    if p is None or not p.exists() or p.stat().st_size == 0:
        return None
    return p


def best_art_for_rom(rom_path: Path, *, root: Path | None = None) -> Path | None:
    """Pick the first available art for a ROM, preferring snap → boxart →
    title. Returns None if nothing is cached.
    """
    for kind in ("snap", "boxart", "title"):
        p = art_path_if_present(rom_path, kind, root=root)
        if p is not None:
            return p
    return None
