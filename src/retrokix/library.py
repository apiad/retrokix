"""ROM library — unified across consoles (GBA, NES, …).

Each entry carries a `console` field telling us which No-Intro mirror
on archive.org hosts it. At construction time we merge every bundled
`no_intro_<console>.json` into one in-memory list; `search` returns
matches across all consoles. The CLI / browse / download paths
disambiguate by inspecting `entry.console`.

The downloaded `.zip` per entry is extracted into `~/.retrokix/roms/`
keeping its native extension (`.gba`, `.nes`, …). Local detection
follows suit — any file with a known ROM extension counts.

Adding a console = adding three things:
  1. an entry in CONSOLES below (archive item, ROM extension, bundled
     JSON filename, libretro core .so name);
  2. a `no_intro_<console>.json` (run scripts/refresh_library_metadata.py);
  3. a `libretro_cheats_<console>.json` (run scripts/refresh_cheats.py).
"""

from __future__ import annotations

import hashlib
import json
import shutil
import sys
import tempfile
import urllib.parse
import urllib.request
import zipfile
from dataclasses import dataclass
from pathlib import Path


METADATA_URL = "https://archive.org/metadata/{item}"
DOWNLOAD_URL = "https://archive.org/download/{item}/{filename}"
DEFAULT_ROMS_DIR = Path.home() / ".retrokix" / "roms"


@dataclass(frozen=True)
class ConsoleInfo:
    """All the per-console knobs in one place."""

    slug: str          # 'gba', 'nes', …
    label: str         # 'Game Boy Advance' (display)
    archive_item: str  # archive.org item that hosts the No-Intro mirror
    rom_exts: tuple[str, ...]
    bundle_json: str   # bundled file under retrokix/data/
    cheats_json: str
    core_so: str       # libretro core filename under retrokix/cores/


CONSOLES: dict[str, ConsoleInfo] = {
    "gba": ConsoleInfo(
        slug="gba",
        label="Game Boy Advance",
        archive_item="ef_gba_no-intro_2024-02-21",
        rom_exts=(".gba",),
        bundle_json="no_intro_gba.json",
        cheats_json="libretro_cheats_gba.json",
        core_so="mgba_libretro.so",
    ),
    "nes": ConsoleInfo(
        slug="nes",
        label="Nintendo Entertainment System",
        archive_item="ef_nintendo_entertainment_-system_-no-intro_2024-04-23",
        rom_exts=(".nes",),
        bundle_json="no_intro_nes.json",
        cheats_json="libretro_cheats_nes.json",
        core_so="fceumm_libretro.so",
    ),
}

#: All ROM extensions any console knows about — for local-disk discovery.
ALL_ROM_EXTS: tuple[str, ...] = tuple(
    sorted({ext for c in CONSOLES.values() for ext in c.rom_exts})
)

#: Map ROM extension → console slug; used to pick the right libretro core.
_EXT_TO_CONSOLE: dict[str, str] = {
    ext: c.slug for c in CONSOLES.values() for ext in c.rom_exts
}


def console_for_path(path: Path | str) -> str | None:
    """Return the console slug for a given ROM file, or None if the
    extension isn't one we recognise."""
    ext = Path(path).suffix.lower()
    return _EXT_TO_CONSOLE.get(ext)


if sys.version_info >= (3, 11):
    from importlib.resources import files as _resource_files
else:  # pragma: no cover — minimum supported is 3.11
    from importlib_resources import files as _resource_files  # type: ignore


@dataclass
class RomEntry:
    name: str            # filename inside the archive item (e.g. "Pokemon - Emerald Version (USA, Europe).zip")
    size: int            # bytes
    sha1: str | None     # archive's recorded SHA-1 of the .zip
    console: str = "gba" # console slug — matches CONSOLES keys

    @property
    def is_zip(self) -> bool:
        return self.name.lower().endswith(".zip")

    @property
    def title(self) -> str:
        """Filename without trailing .zip / .gba / .nes / etc — useful
        for grouping and for the cheats-by-rom lookup key."""
        n = self.name
        lower = n.lower()
        for ext in (".zip",) + ALL_ROM_EXTS:
            if lower.endswith(ext):
                return n[: -len(ext)]
        return n


def _load_bundle(console_slug: str) -> tuple[str, list[RomEntry]]:
    """Load one bundled `no_intro_<slug>.json` → (archive_item, entries)."""
    info = CONSOLES[console_slug]
    blob = _resource_files("retrokix.data").joinpath(info.bundle_json).read_text()
    data = json.loads(blob)
    entries = [
        RomEntry(
            name=e["name"],
            size=int(e["size"]),
            sha1=e.get("sha1"),
            console=console_slug,
        )
        for e in data["entries"]
    ]
    return data.get("item", info.archive_item), entries


def _load_all_bundles() -> list[RomEntry]:
    """Merge every bundled console snapshot into one entry list."""
    merged: list[RomEntry] = []
    for slug in CONSOLES:
        try:
            _item, entries = _load_bundle(slug)
        except FileNotFoundError:
            # Bundled JSON not present yet (mid-refresh) — skip silently.
            continue
        merged.extend(entries)
    return merged


class RomLibrary:
    """Wraps the bundled No-Intro snapshots across every console.

    Defaults to the bundled metadata (instant search, zero network).
    Pass `console=` to constrain searches to one console; pass
    `item=` + `refresh=True` to fall through to a custom archive.org
    item (rare — used for one-off mirrors).
    """

    def __init__(
        self,
        console: str | None = None,
        item: str | None = None,
        roms_dir: Path | None = None,
        refresh: bool = False,
    ):
        self.console = console
        self.item = item
        self.roms_dir = Path(roms_dir) if roms_dir else DEFAULT_ROMS_DIR
        self._refresh = refresh
        self._cached_entries: list[RomEntry] | None = None

    def _fetch_metadata(self) -> list[RomEntry]:
        if not self._refresh:
            entries = _load_all_bundles()
            if self.console is not None:
                entries = [e for e in entries if e.console == self.console]
            if self.item is not None:
                # `item` was set explicitly — keep entries that came from
                # that item (matches the legacy single-console API).
                entries = [
                    e for e in entries
                    if CONSOLES[e.console].archive_item == self.item
                ]
            if entries:
                return entries
        # Network fallback. Only one archive.org item per call — caller
        # must pass `item=` for non-default fetches.
        if self.item is None:
            raise RuntimeError(
                "no bundled entries match the requested filter; pass `item=` to fetch from archive.org"
            )
        url = METADATA_URL.format(item=self.item)
        with urllib.request.urlopen(url, timeout=30) as resp:
            data = json.load(resp)
        # When fetching from a custom item, console defaults to the one
        # the caller asked for (or "gba" for back-compat).
        slug = self.console or "gba"
        # Filter by known ROM extensions for the inferred console.
        rom_exts = CONSOLES[slug].rom_exts if slug in CONSOLES else ALL_ROM_EXTS
        entries: list[RomEntry] = []
        for f in data.get("files", []):
            name = f.get("name", "")
            if not (name.lower().endswith(".zip")
                    or name.lower().endswith(rom_exts)):
                continue
            entries.append(RomEntry(
                name=name,
                size=int(f.get("size", 0) or 0),
                sha1=f.get("sha1"),
                console=slug,
            ))
        return entries

    def entries(self) -> list[RomEntry]:
        if self._cached_entries is None:
            self._cached_entries = self._fetch_metadata()
        return self._cached_entries

    def search(self, query: str) -> list[RomEntry]:
        """Fuzzy match: all whitespace-separated tokens of `query` must
        appear (case-insensitive) in the entry name. Matches span
        every loaded console; callers disambiguate by inspecting
        `entry.console` on the result."""
        tokens = [t.lower() for t in query.split() if t]
        if not tokens:
            return []
        return [
            e for e in self.entries()
            if all(t in e.name.lower() for t in tokens)
        ]

    def download(self, entry: RomEntry, progress: bool = True) -> Path:
        """Download an entry, extract the ROM if zipped, save to
        roms_dir. Returns the final ROM path (e.g. `.gba`, `.nes`)."""
        self.roms_dir.mkdir(parents=True, exist_ok=True)
        info = CONSOLES.get(entry.console)
        item = info.archive_item if info else (self.item or "")
        if not item:
            raise RuntimeError(
                f"unknown console {entry.console!r} — can't locate archive.org item"
            )
        url = DOWNLOAD_URL.format(
            item=item,
            filename=urllib.parse.quote(entry.name),
        )
        with tempfile.NamedTemporaryFile(delete=False, suffix=Path(entry.name).suffix) as tmp:
            tmp_path = Path(tmp.name)
        try:
            _stream_download(url, tmp_path, total_bytes=entry.size, show_progress=progress)
            if entry.is_zip:
                rom_exts = info.rom_exts if info else ALL_ROM_EXTS
                final = _extract_first_rom(tmp_path, self.roms_dir, rom_exts)
            else:
                final = self.roms_dir / entry.name
                shutil.move(str(tmp_path), final)
            return final
        finally:
            if tmp_path.exists():
                tmp_path.unlink()


def _stream_download(url: str, dest: Path, total_bytes: int = 0, show_progress: bool = True, retries: int = 3) -> None:
    req = urllib.request.Request(url, headers={"User-Agent": "retrokix/0.0.1"})
    last_exc = None
    for attempt in range(retries):
        try:
            with urllib.request.urlopen(req, timeout=60) as resp, open(dest, "wb") as out:
                chunk_size = 1 << 16
                downloaded = 0
                last_pct = -1
                while True:
                    chunk = resp.read(chunk_size)
                    if not chunk:
                        break
                    out.write(chunk)
                    downloaded += len(chunk)
                    if show_progress and total_bytes:
                        pct = int(downloaded * 100 / total_bytes)
                        if pct != last_pct and pct % 5 == 0:
                            mb = downloaded / 1_048_576
                            total_mb = total_bytes / 1_048_576
                            print(f"\r  downloading… {pct:3d}%  ({mb:.1f}/{total_mb:.1f} MB)", end="", flush=True)
                            last_pct = pct
                if show_progress:
                    print()
                return
        except urllib.error.HTTPError as exc:
            last_exc = exc
            if attempt < retries - 1:
                if show_progress:
                    print(f"\n  HTTP {exc.code} — retrying ({attempt + 2}/{retries})…")
                continue
            raise
    if last_exc:
        raise last_exc


def _extract_first_rom(zip_path: Path, dest_dir: Path, rom_exts: tuple[str, ...]) -> Path:
    """Extract the first member of `zip_path` whose extension is in
    `rom_exts`. Returns the path of the file written to `dest_dir`."""
    with zipfile.ZipFile(zip_path, "r") as z:
        members = [n for n in z.namelist() if n.lower().endswith(rom_exts)]
        if not members:
            raise RuntimeError(
                f"no member with extension in {rom_exts!r} found inside {zip_path}"
            )
        member = members[0]
        out = dest_dir / Path(member).name
        with z.open(member) as src, open(out, "wb") as dst:
            shutil.copyfileobj(src, dst)
    return out


def sha1(path: Path) -> str:
    h = hashlib.sha1()
    with open(path, "rb") as f:
        for chunk in iter(lambda: f.read(1 << 20), b""):
            h.update(chunk)
    return h.hexdigest()


def list_local_roms(roms_dir: Path | None = None) -> list[Path]:
    """Every ROM-shaped file in roms_dir, across all known consoles."""
    d = Path(roms_dir) if roms_dir else DEFAULT_ROMS_DIR
    if not d.exists():
        return []
    return sorted(
        p for p in d.iterdir()
        if p.is_file() and p.suffix.lower() in ALL_ROM_EXTS
    )


def resolve_rom(query_or_path: str, roms_dir: Path | None = None) -> Path:
    """Accept either a literal filesystem path or a fuzzy query against
    the local library. Multiple matches raise — be specific."""
    p = Path(query_or_path)
    if p.exists():
        return p
    tokens = [t.lower() for t in query_or_path.split() if t]
    if not tokens:
        raise FileNotFoundError(f"empty query and no file at {query_or_path!r}")
    matches = [
        local for local in list_local_roms(roms_dir)
        if all(t in local.name.lower() for t in tokens)
    ]
    if not matches:
        raise FileNotFoundError(
            f"no local ROM matches {query_or_path!r}; try `retrokix download {query_or_path!r}` first"
        )
    if len(matches) > 1:
        names = "\n  ".join(m.name for m in matches)
        raise RuntimeError(
            f"ambiguous match for {query_or_path!r}; got:\n  {names}"
        )
    return matches[0]


# --- title grouping ---

def title_key(name: str) -> str:
    """Group key for No-Intro names — everything before the first '('.

    e.g. 'Pokemon - Emerald Version (USA, Europe).zip' →
         'Pokemon - Emerald Version'

    Collapses regional/language/version variants into one group. If a
    name has no parenthetical we strip the archive/ROM extension and
    use what remains. Shared between `retrokix browse`, the fame
    refresher, and any other tool that needs a stable title key."""
    paren = name.find("(")
    if paren > 0:
        return name[:paren].rstrip()
    lower = name.lower()
    for ext in (".zip",) + ALL_ROM_EXTS:
        if lower.endswith(ext):
            return name[: -len(ext)].rstrip()
    return name.rstrip()


# --- fame index ---

_FAME_CACHE: dict[str, dict[str, dict]] | None = None


def _load_fame() -> dict[str, dict[str, dict]]:
    """Load bundled Wikipedia-pageviews fame index. Returns {} if absent
    (dev tree without the snapshot, or a console with no entries yet).
    Cached after first call."""
    global _FAME_CACHE
    if _FAME_CACHE is not None:
        return _FAME_CACHE
    try:
        blob = _resource_files("retrokix.data").joinpath("wikipedia_fame.json").read_text()
        _FAME_CACHE = json.loads(blob)
    except FileNotFoundError:
        _FAME_CACHE = {}
    return _FAME_CACHE


def fame_score(console: str, title: str) -> int:
    """Wikipedia pageviews over the last 12 months for (console, title).
    Returns 0 when the snapshot has no entry — sorts to the bottom."""
    info = _load_fame().get(console, {}).get(title)
    return int(info.get("views_12mo", 0)) if info else 0


# Quantile boundaries for the star rating:
# 5★ = top 2% of ranked titles, 4★ = top 10%, 3★ = top 25%, 2★ = top
# 50%, 1★ = anything ranked above zero, 0★ = unranked. Cuts adapt to
# whatever's in the loaded snapshot.
_STAR_QUANTILES: tuple[float, ...] = (0.02, 0.10, 0.25, 0.50)
_FAME_THRESHOLDS: list[int] | None = None


def _fame_thresholds() -> list[int]:
    """Return view-count cuts indexed by star tier (5★ first, then 4★…)."""
    global _FAME_THRESHOLDS
    if _FAME_THRESHOLDS is not None:
        return _FAME_THRESHOLDS
    fame = _load_fame()
    views = sorted(
        (int(i["views_12mo"]) for c in fame.values() for i in c.values()
         if i.get("views_12mo", 0) > 0),
        reverse=True,
    )
    if not views:
        _FAME_THRESHOLDS = [0, 0, 0, 0, 1]
        return _FAME_THRESHOLDS
    cuts = []
    for p in _STAR_QUANTILES:
        idx = max(0, min(len(views) - 1, int(len(views) * p) - 1))
        cuts.append(views[idx])
    cuts.append(1)  # 1★ floor: any positive views
    _FAME_THRESHOLDS = cuts
    return _FAME_THRESHOLDS


def fame_stars(console: str, title: str) -> int:
    """0–5 stars based on where (console, title) sits in the snapshot's
    fame distribution. 0 = unranked (no Wikipedia data) or fame=0;
    5 = top 2% of ranked titles."""
    score = fame_score(console, title)
    if score <= 0:
        return 0
    for stars, cut in zip((5, 4, 3, 2, 1), _fame_thresholds()):
        if score >= cut:
            return stars
    return 0


# --- back-compat shims ---

#: Legacy single-console default. Kept so older scripts importing
#: `DEFAULT_ARCHIVE_ITEM` still work.
DEFAULT_ARCHIVE_ITEM = CONSOLES["gba"].archive_item


def _load_bundled_metadata() -> tuple[str, list[RomEntry]]:
    """Back-compat shim: the original single-console loader. Returns
    just the GBA bundle. New code should call `_load_bundle(slug)` or
    `_load_all_bundles()`."""
    return _load_bundle("gba")
