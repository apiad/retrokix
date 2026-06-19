"""Build the hub landing's library view: owned + top-N unowned per console.

Reuses the No-Intro bundles + fame index from `retrokix.library`. The
small grouping helpers (region scoring, title→group collapse) are
duplicated here rather than imported from `browse.py` so the hub
doesn't pull in Textual at request time.
"""

from __future__ import annotations

from dataclasses import dataclass, field
from pathlib import Path

from retrokix.library import (
    ALL_ROM_EXTS,
    CONSOLES,
    RomEntry,
    RomLibrary,
    console_for_path,
    fame_score,
    fame_stars,
    list_local_roms,
    title_key,
)


SHOWCASE_PER_CONSOLE = 24
SEARCH_LIMIT = 300


@dataclass
class HubGroup:
    """One library row for the hub grid — owned-or-not, plus the
    metadata the tile needs (title, console, fame, action target)."""

    title: str
    console: str
    fame: int
    stars: int
    owned: bool
    # Owned: one or more files on disk; primary = the one to launch.
    paths: list[Path] = field(default_factory=list)
    # Unowned: archive entry name to download (the .zip in archive.org).
    archive_name: str | None = None
    variant_count: int = 1

    @property
    def primary_path(self) -> Path | None:
        return self.paths[0] if self.paths else None


def _region_score(name_lower: str) -> int:
    if "(usa" in name_lower or "(world" in name_lower:
        return 0
    if "(europe" in name_lower:
        return 1
    return 2


def _canonical_variant(entries: list[RomEntry]) -> RomEntry:
    return sorted(
        entries, key=lambda e: (_region_score(e.name.lower()), len(e.name))
    )[0]


def _owned_groups(roms_dir: Path) -> dict[tuple[str, str], HubGroup]:
    """key = (console, title_key) → HubGroup, all owned=True."""
    groups: dict[tuple[str, str], HubGroup] = {}
    for path in list_local_roms(roms_dir):
        console = console_for_path(path) or "gba"
        title = title_key(path.name)
        key = (console, title)
        g = groups.get(key)
        if g is None:
            g = HubGroup(
                title=title,
                console=console,
                fame=fame_score(console, title),
                stars=fame_stars(console, title),
                owned=True,
                paths=[],
            )
            groups[key] = g
        g.paths.append(path)
    for g in groups.values():
        g.variant_count = len(g.paths)
    return groups


def _showcase_unowned(
    owned_keys: set[tuple[str, str]],
    *,
    limit_per_console: int,
) -> list[HubGroup]:
    """Top N unowned titles per console, ranked by fame."""
    out: list[HubGroup] = []
    for slug in CONSOLES:
        lib = RomLibrary(console=slug)
        entries = lib.entries()
        # Group entries by title_key, dedupe variants.
        by_title: dict[str, list[RomEntry]] = {}
        for e in entries:
            t = title_key(e.name)
            by_title.setdefault(t, []).append(e)
        candidates: list[HubGroup] = []
        for title, variants in by_title.items():
            if (slug, title) in owned_keys:
                continue
            primary = _canonical_variant(variants)
            candidates.append(HubGroup(
                title=title,
                console=slug,
                fame=fame_score(slug, title),
                stars=fame_stars(slug, title),
                owned=False,
                archive_name=primary.name,
                variant_count=len(variants),
            ))
        candidates.sort(key=lambda g: (-g.fame, g.title.lower()))
        out.extend(candidates[:limit_per_console])
    return out


_SEARCH_INDEX: dict[str, list[tuple[str, list[RomEntry]]]] | None = None


def _full_index() -> dict[str, list[tuple[str, list[RomEntry]]]]:
    """Cached per-console index: console_slug → [(title, [variants...]), ...].

    Built once at first access (a few hundred ms to read the bundled
    JSONs); reused across every /api/search call thereafter.
    """
    global _SEARCH_INDEX
    if _SEARCH_INDEX is None:
        cache: dict[str, list[tuple[str, list[RomEntry]]]] = {}
        for slug in CONSOLES:
            entries = RomLibrary(console=slug).entries()
            by_title: dict[str, list[RomEntry]] = {}
            for e in entries:
                by_title.setdefault(title_key(e.name), []).append(e)
            cache[slug] = list(by_title.items())
        _SEARCH_INDEX = cache
    return _SEARCH_INDEX


def warm_search_index() -> None:
    """Force index build (call at hub startup so the first /api/search
    request doesn't pay the JSON-parse cost)."""
    _full_index()


def search_library(
    query: str,
    roms_dir: Path,
    *,
    limit: int = SEARCH_LIMIT,
) -> list[HubGroup]:
    """Match `query` across every owned + bundled title.

    Tokens are space-separated and ALL must appear (case-insensitive)
    in the title key. Owned matches surface first, then unowned —
    each sub-block fame-sorted DESC.
    """
    tokens = [t.lower() for t in query.split() if t]
    if not tokens:
        return []
    owned = _owned_groups(roms_dir)

    owned_matches: list[HubGroup] = []
    for key, g in owned.items():
        if all(t in g.title.lower() for t in tokens):
            owned_matches.append(g)
    owned_keys = set(owned.keys())

    unowned_matches: list[HubGroup] = []
    for slug, by_title in _full_index().items():
        for title, variants in by_title:
            if (slug, title) in owned_keys:
                continue
            if not all(t in title.lower() for t in tokens):
                continue
            primary = _canonical_variant(variants)
            unowned_matches.append(HubGroup(
                title=title,
                console=slug,
                fame=fame_score(slug, title),
                stars=fame_stars(slug, title),
                owned=False,
                archive_name=primary.name,
                variant_count=len(variants),
            ))

    owned_matches.sort(key=lambda g: (-g.fame, g.title.lower()))
    unowned_matches.sort(key=lambda g: (-g.fame, g.title.lower()))
    return (owned_matches + unowned_matches)[:limit]


def build_library_view(
    roms_dir: Path,
    *,
    showcase_per_console: int = SHOWCASE_PER_CONSOLE,
) -> list[HubGroup]:
    """Owned + top-N unowned per console. Owned always above unowned
    within each console section; both sub-blocks are fame-sorted DESC."""
    owned = _owned_groups(roms_dir)
    owned_list = sorted(
        owned.values(), key=lambda g: (-g.fame, g.title.lower())
    )
    unowned = _showcase_unowned(
        set(owned.keys()),
        limit_per_console=showcase_per_console,
    )

    # Merge: owned first per console (already fame-sorted), unowned next.
    # The hub's renderer groups by console downstream.
    return owned_list + unowned


@dataclass
class ConsoleStat:
    """One row of the landing-page stats panel."""
    slug: str
    label: str
    catalog: int   # # distinct title-keys in bundled metadata
    owned: int     # # owned title-keys on disk
    famous: int    # # title-keys with ≥1 Wikipedia view (Fame stars > 0)


def console_stats(roms_dir: Path) -> list[ConsoleStat]:
    """Per-console counters for the landing-page stats panel.

    `catalog`/`famous` come from the bundled No-Intro + fame indexes
    (constant across processes); `owned` walks `roms_dir`.
    """
    owned_by_console: dict[str, set[str]] = {}
    for path in list_local_roms(roms_dir):
        console = console_for_path(path) or "gba"
        owned_by_console.setdefault(console, set()).add(title_key(path.name))

    out: list[ConsoleStat] = []
    for slug, info in CONSOLES.items():
        by_title = _full_index().get(slug, [])
        catalog = len(by_title)
        famous = sum(1 for title, _ in by_title if fame_score(slug, title) > 0)
        owned = len(owned_by_console.get(slug, set()))
        out.append(ConsoleStat(
            slug=slug,
            label=info.label,
            catalog=catalog,
            owned=owned,
            famous=famous,
        ))
    return out


__all__ = [
    "ConsoleStat",
    "HubGroup",
    "build_library_view",
    "console_stats",
    "search_library",
    "warm_search_index",
    "SHOWCASE_PER_CONSOLE",
    "SEARCH_LIMIT",
    "ALL_ROM_EXTS",
]
