"""Interactive ROM browser — `retrokix browse`.

A Textual TUI over `RomLibrary`: search-as-you-type, arrow-keys to
navigate, Enter to download. The pure-CLI `retrokix search` and `retrokix
download` stay as-is for scripts and agents; this one is for humans
who want to poke around without remembering exact No-Intro names.

Design notes:
- Filter runs synchronously on every keystroke against the in-memory
  3,555-entry index. Plenty fast; no debounce needed.
- Downloads run in a thread worker so the UI stays responsive. The
  existing `RomLibrary.download` is blocking; we wrap it.
- We show all regional variants in the list so the user picks the
  exact one with arrow keys. That's the value over `retrokix download
  --region`.
"""

from __future__ import annotations

from dataclasses import dataclass, field
from pathlib import Path
from typing import TYPE_CHECKING, Callable

from textual.app import App, ComposeResult
from textual.binding import Binding
from textual.containers import Container, Horizontal, Vertical
from textual.reactive import reactive
from textual.screen import ModalScreen
from textual.widgets import Footer, Header, Input, ListItem, ListView, Static

if TYPE_CHECKING:
    from retrokix.library import RomEntry, RomLibrary


MAX_RESULTS = 100


# Curated GBA hits shown when the search box is empty. Each entry is a
# fuzzy query — all tokens must appear in the No-Intro filename. Order
# roughly approximates fame; for ambiguous queries we pick USA/World
# over Europe over Japan, then the shortest name (base game wins ties).
# If the top match was already added under an earlier query, we fall
# through to the next match instead of skipping the slot.
_FAMOUS_QUERIES: tuple[str, ...] = (
    # Pokémon
    "Pokemon - Emerald",
    "Pokemon - FireRed",
    "Pokemon - LeafGreen",
    "Pokemon - Ruby Version",
    "Pokemon - Sapphire Version",
    "Pokemon Mystery Dungeon - Red Rescue",
    "Pokemon Pinball - Ruby",
    # Zelda
    "Legend of Zelda - The Minish Cap",
    "Legend of Zelda - A Link to the Past",
    # Metroid
    "Metroid Fusion",
    "Metroid - Zero Mission",
    # Mario
    "Super Mario Advance 4",
    "Super Mario Advance 2",
    "Super Mario Advance 3",
    "Super Mario Advance (",
    "Mario Kart - Super Circuit",
    "Mario & Luigi - Superstar Saga",
    "Mario Pinball Land",
    "Mario Party Advance",
    "Mario Golf - Advance Tour",
    "Mario Tennis - Power Tour",
    "Yoshi Topsy-Turvy",
    # Wario / WarioWare
    "Wario Land 4",
    "WarioWare - Twisted",
    "WarioWare, Inc.",
    # Kirby
    "Kirby & The Amazing Mirror",
    "Kirby - Nightmare in Dream Land",
    # Fire Emblem / Advance Wars
    "Fire Emblem - The Sacred Stones",
    "Fire Emblem (",
    "Advance Wars 2",
    "Advance Wars (",
    # F-Zero
    "F-Zero - Maximum Velocity",
    "F-Zero - GP Legend",
    "F-Zero Climax",
    # Donkey Kong
    "Donkey Kong Country (",
    "Donkey Kong Country 2",
    "Donkey Kong Country 3",
    # Square Enix
    "Final Fantasy VI Advance",
    "Final Fantasy V Advance",
    "Final Fantasy IV Advance",
    "Final Fantasy I & II - Dawn of Souls",
    "Final Fantasy Tactics Advance",
    "Sword of Mana",
    "Kingdom Hearts - Chain of Memories",
    "Tactics Ogre",
    "Riviera - The Promised Land",
    # Castlevania
    "Castlevania - Aria of Sorrow",
    "Castlevania - Harmony of Dissonance",
    "Castlevania - Circle of the Moon",
    # Mega Man — Battle Network + Zero
    "Mega Man Battle Network 3",
    "Mega Man Battle Network 6",
    "Mega Man Battle Network 5",
    "Mega Man Battle Network 4",
    "Mega Man Battle Network 2",
    "Mega Man Battle Network (",
    "Mega Man Zero 4",
    "Mega Man Zero 3",
    "Mega Man Zero 2",
    "Mega Man Zero (",
    "Mega Man & Bass",
    # Golden Sun
    "Golden Sun - The Lost Age",
    "Golden Sun (",
    # Sonic
    "Sonic Advance 3",
    "Sonic Advance 2",
    "Sonic Advance (",
    "Sonic Battle",
    "Sonic Pinball Party",
    # Boktai
    "Boktai - The Sun Is in Your Hand",
    "Boktai 2",
    # FPS / action
    "Doom (",
    "Doom II",
    "Duke Nukem Advance",
    "Drill Dozer",
    "Astro Boy - Omega Factor",
    # Cult / classic
    "Mother 3",
    "Rhythm Tengoku",
    "Ninja Five-0",
    "Gunstar Super Heroes",
    "Klonoa - Empire of Dreams",
    "Klonoa 2",
    "Iridion 3D",
    "Pinball of the Dead",
    "Final Fight One",
    "Street Fighter Alpha 3",
    # Tony Hawk
    "Tony Hawk's Pro Skater 2",
    "Tony Hawk's Pro Skater 3",
    "Tony Hawk's Pro Skater 4",
    # Licensed blockbusters
    "Harry Potter and the Chamber of Secrets",
    "Harry Potter and the Prisoner of Azkaban",
    "Lord of the Rings - The Two Towers",
    "Lord of the Rings - The Return",
    "Spider-Man (",
    "Spider-Man 2",
    "Spider-Man 3",
    "X-Men - The Official Game",
    "Yu-Gi-Oh! - The Eternal Duelist Soul",
    # JRPG odds
    "Breath of Fire (",
    "Breath of Fire II",
    "Lufia - The Ruins of Lore",
    # Classic NES Series
    "Classic NES Series - Super Mario Bros",
    "Classic NES Series - The Legend of Zelda",
    "Classic NES Series - Metroid",
    "Classic NES Series - Donkey Kong",
    # ---------- NES classics ----------
    # Token-based AND match, sorted USA/World > Europe > Japan, shortest
    # name wins within a region. Queries below are tuned against the
    # 2024 No-Intro NES set so the canonical USA release lands first.
    # Mario
    "Super Mario Bros. (World",
    "Super Mario Bros. 2 (USA",
    "Super Mario Bros. 3 (USA",
    # Zelda
    "Legend of Zelda, The (USA)",
    "Zelda II - The Adventure of Link (USA)",
    # Metroid / Mother
    "Metroid (USA)",
    "EarthBound Beginnings",
    # Mega Man 1-6
    "Mega Man (USA)",
    "Mega Man 2 (USA)",
    "Mega Man 3 (USA)",
    "Mega Man 4 (USA)",
    "Mega Man 5 (USA)",
    "Mega Man 6 (USA)",
    # Castlevania trilogy
    "Castlevania (USA)",
    "Castlevania II - Simon's Quest (USA)",
    "Castlevania III - Dracula's Curse (USA)",
    # Konami / Contra
    "Contra (USA)",
    "Super C (USA)",
    "Gradius (USA)",
    "Life Force (USA)",
    # Square / Enix RPGs
    "Final Fantasy (USA)",
    "Dragon Warrior (USA)",
    "Dragon Warrior II",
    "Dragon Warrior III",
    "Dragon Warrior IV",
    "Crystalis (USA)",
    "Faxanadu (USA)",
    # Nintendo first-party
    "Punch-Out!! (USA)",
    "Kid Icarus (USA",
    "Excitebike (USA",
    "Duck Hunt (World)",
    "StarTropics (USA)",
    "Ice Climber (USA",
    "Balloon Fight (USA",
    "Pinball (Europe, Asia)",
    "Donkey Kong (World) (Rev",
    "Donkey Kong Jr. (World)",
    "Donkey Kong 3 (World)",
    "Tetris (USA)",
    # Tecmo / Capcom / Konami staples
    "Ninja Gaiden (USA)",
    "Ninja Gaiden II",
    "Ninja Gaiden III",
    "Bionic Commando (USA)",
    "DuckTales (USA",
    "DuckTales 2 (USA",
    "Chip 'n Dale - Rescue Rangers (USA",
    "Mighty Final Fight (USA",
    # Beat-'em-ups / brawlers
    "Double Dragon (USA",
    "Double Dragon II",
    "Double Dragon III",
    "River City Ransom (USA)",
    "Battletoads (USA)",
    "Battletoads-Double Dragon (USA)",
    # Sega/other ports + cult
    "Adventure Island (USA)",
    "Adventure Island II (USA",
    "Adventure Island 3 (USA",
    "Bubble Bobble (USA)",
    "Kirby's Adventure (USA)",
    "Blaster Master (USA)",
    "Solomon's Key (USA)",
    "Rygar (USA)",
    "Shadow of the Ninja (USA",
    "Solstice (USA",
    "Snake's Revenge (USA",
    "Metal Gear (USA)",
    # Sports / racing
    "R.C. Pro-Am (USA",
    "Skate or Die (USA",
    "Tecmo Bowl (USA",
    "Tecmo Super Bowl (USA",
    # Cult RPG/strategy
    "Maniac Mansion (USA",
    "Adventures of Lolo (USA",
    # ---------- SNES classics ----------
    # Same shape as the NES cohort — tuned against the 2024 No-Intro
    # SNES set so the canonical USA release wins each group.
    # Mario / Zelda / Metroid
    "Super Mario World (USA",
    "Super Mario World 2 - Yoshi's Island (USA)",
    "Super Mario All-Stars (USA)",
    "Super Mario All-Stars + Super Mario World (USA)",
    "Super Mario Kart (USA)",
    "Super Mario RPG - Legend of the Seven Stars (USA)",
    "Legend of Zelda, The - A Link to the Past (USA)",
    "Super Metroid (Japan, USA)",
    # Donkey Kong Country
    "Donkey Kong Country (USA",
    "Donkey Kong Country 2 - Diddy's Kong Quest (USA",
    "Donkey Kong Country 3 - Dixie Kong's Double Trouble! (USA",
    # Square / Enix JRPGs
    "Chrono Trigger (USA)",
    "Final Fantasy III (USA)",
    "Final Fantasy II (USA)",
    "Final Fantasy V (Japan)",
    "Final Fantasy - Mystic Quest (USA)",
    "Secret of Mana (USA)",
    "Seiken Densetsu 3 (Japan)",
    "EarthBound (USA)",
    "Lufia & The Fortress of Doom (USA)",
    "Lufia II - Rise of the Sinistrals (USA)",
    "Breath of Fire (USA)",
    "Breath of Fire II (USA)",
    "Illusion of Gaia (USA)",
    "Terranigma (Europe)",
    "Soul Blazer (USA)",
    "Ogre Battle - The March of the Black Queen (USA)",
    "Tactics Ogre - Let Us Cling Together (Japan)",
    # Mega Man X / Castlevania / Contra
    "Mega Man X (USA)",
    "Mega Man X2 (USA)",
    "Mega Man X3 (USA)",
    "Mega Man 7 (USA)",
    "Super Castlevania IV (USA)",
    "Castlevania - Dracula X (USA)",
    "Super C (USA)",
    "Contra III - The Alien Wars (USA)",
    "Super Probotector - Alien Rebels (Europe)",
    # Fighting / brawlers
    "Street Fighter II - The World Warrior (USA)",
    "Street Fighter II Turbo (USA)",
    "Super Street Fighter II (USA)",
    "Mortal Kombat (USA)",
    "Mortal Kombat II (USA)",
    "Mortal Kombat 3 (USA)",
    "Killer Instinct (USA",
    "Final Fight (USA)",
    "Final Fight 2 (USA)",
    "Final Fight 3 (USA)",
    "Teenage Mutant Ninja Turtles IV - Turtles in Time (USA)",
    # Action / adventure / shmup
    "Star Fox (USA)",
    "Star Fox - Super Weekend (USA)",
    "F-Zero (USA",
    "Pilotwings (USA",
    "Super Punch-Out!! (USA",
    "Kirby Super Star (USA)",
    "Kirby's Dream Course (USA",
    "Kirby's Dream Land 3 (USA",
    "Yoshi's Island (USA",
    "Yoshi's Cookie (USA",
    "Yoshi's Safari (USA",
    "ActRaiser (USA",
    "ActRaiser 2 (USA",
    "Demon's Crest (USA",
    "Gradius III (USA",
    "R-Type III - The Third Lightning (USA)",
    "Super R-Type (USA",
    "U.N. Squadron (USA",
    "Axelay (USA",
    # Sports / racing
    "NBA Jam (USA",
    "NBA Jam - Tournament Edition (USA",
    "Tetris & Dr. Mario (USA",
    "Tetris Attack (USA)",
    "Super Tennis (USA",
    "Super Mario Kart (USA",
)


from retrokix.library import title_key as _title_key  # noqa: E402  re-export


def _region_score(name_lower: str) -> int:
    """Lower is more canonical. USA/World > Europe > Japan/other."""
    if "(usa" in name_lower or "(world" in name_lower:
        return 0
    if "(europe" in name_lower:
        return 1
    return 2


@dataclass
class RomGroup:
    """A title with one or more regional/version variants.

    `variants` is sorted USA/World → Europe → Japan/other, then
    shortest name (so the canonical base release ends up first).

    `fame` is Wikipedia pageviews over the last 12 months — see
    `library.fame_score`. Used to rank groups in the browse list;
    0 when the snapshot has no entry for this title.

    `stars` is the percentile bucket of `fame` within the snapshot —
    see `library.fame_stars`. 0–5 inclusive.
    """

    title: str
    variants: list["RomEntry"] = field(default_factory=list)
    fame: int = 0
    stars: int = 0

    @property
    def primary(self) -> "RomEntry":
        return self.variants[0]

    @property
    def extra_count(self) -> int:
        return len(self.variants) - 1


def _group_entries(entries: list["RomEntry"]) -> list[RomGroup]:
    """Collapse a flat entry list into per-title groups, preserving the
    relative order of first appearance. Each group's `fame` is set from
    the bundled Wikipedia pageviews snapshot keyed by (console, title);
    `stars` is the corresponding 0–5 percentile bucket."""
    from retrokix.library import fame_score, fame_stars
    by_title: dict[tuple[str, str], RomGroup] = {}
    order: list[tuple[str, str]] = []
    for e in entries:
        key = (e.console, _title_key(e.name))
        g = by_title.get(key)
        if g is None:
            g = RomGroup(
                title=key[1], variants=[],
                fame=fame_score(*key), stars=fame_stars(*key),
            )
            by_title[key] = g
            order.append(key)
        g.variants.append(e)
    # Canonicalize variant order within each group.
    for g in by_title.values():
        g.variants.sort(key=lambda e: (_region_score(e.name.lower()), len(e.name)))
    return [by_title[k] for k in order]


def _sort_by_fame(groups: list[RomGroup]) -> list[RomGroup]:
    """DESC by fame, alphabetical title tiebreak. Groups with fame=0
    (no Wikipedia article known) sort to the bottom but still
    deterministically by title."""
    return sorted(groups, key=lambda g: (-g.fame, g.title.lower()))


def _fmt_size(b: int) -> str:
    mb = b / 1_048_576
    if mb < 1:
        return f"{b / 1024:.0f} KB"
    return f"{mb:.1f} MB"


def _trim_name(name: str, width: int) -> str:
    """Strip the .zip suffix and ellipsize if longer than width."""
    if name.lower().endswith(".zip"):
        name = name[:-4]
    if len(name) <= width:
        return name
    return name[: width - 1] + "…"


def _marker(owned: bool) -> str:
    return "[#34d399]●[/]" if owned else " "


_CONSOLE_BADGE_COLORS = {
    # GBA: muted purple/indigo; NES: warm red; SNES: amber — echoes the
    # NA SNES brand palette and stays readable on dark terminals.
    "gba": "#a78bfa",
    "nes": "#f87171",
    "snes": "#f59e0b",
}


def _console_badge(slug: str | None) -> str:
    if not slug:
        return "    "
    color = _CONSOLE_BADGE_COLORS.get(slug, "#94a3b8")
    return f"[{color}]{slug.upper()}[/]"


def _stars_cell(n: int) -> str:
    """Five-character star rating — gold for filled, slate-dim for empty."""
    n = max(0, min(5, n))
    return f"[#facc15]{'★' * n}[/][#475569]{'★' * (5 - n)}[/]"


def _pretty_name(name: str) -> str:
    """Strip the .zip suffix and dim the (region/language) tail so the
    title carries the visual weight."""
    if name.lower().endswith(".zip"):
        name = name[:-4]
    paren = name.find("(")
    if paren > 0:
        head = name[:paren].rstrip()
        tail = name[paren:]
        return f"{head} [dim]{tail}[/dim]"
    return name


class GroupRow(ListItem):
    """One row in the main list — represents a RomGroup.

    Three columns laid out by CSS so they fill the terminal width:
    fixed-width owned marker · name (1fr, expands) · size (auto, right).
    Size belongs to the canonical variant since downloading the group
    only downloads one variant.
    """

    def __init__(self, group: RomGroup, owned: bool = False) -> None:
        self.group = group
        self.owned = owned
        super().__init__()

    def compose(self) -> ComposeResult:
        extra = (
            f" [dim](+{self.group.extra_count})[/dim]"
            if self.group.extra_count
            else ""
        )
        with Horizontal(classes="row"):
            yield Static(_marker(self.owned), classes="row-marker")
            yield Static(
                _console_badge(self.group.primary.console),
                classes="row-console",
            )
            yield Static(_stars_cell(self.group.stars), classes="row-stars")
            yield Static(f"{self.group.title}{extra}", classes="row-name")
            yield Static(
                f"[dim]{_fmt_size(self.group.primary.size)}[/dim]",
                classes="row-size",
            )


class VariantRow(ListItem):
    """One row inside the variant picker — a single RomEntry."""

    def __init__(self, entry: "RomEntry", owned: bool = False) -> None:
        self.entry = entry
        self.owned = owned
        super().__init__()

    def compose(self) -> ComposeResult:
        with Horizontal(classes="row"):
            yield Static(_marker(self.owned), classes="row-marker")
            yield Static(_console_badge(self.entry.console), classes="row-console")
            yield Static(_pretty_name(self.entry.name), classes="row-name")
            yield Static(
                f"[dim]{_fmt_size(self.entry.size)}[/dim]",
                classes="row-size",
            )


class VariantPicker(ModalScreen[Path | None]):
    """Modal that shows a group's variants and dismisses with the picked
    entry (or None on cancel). The picked entry is downloaded by the
    parent app after the modal closes."""

    CSS = """
    VariantPicker {
        align: center middle;
    }
    #picker-box {
        width: 90%;
        max-width: 110;
        height: auto;
        max-height: 80%;
        background: $boost;
        border: round $accent;
        padding: 1 2;
    }
    #picker-title {
        height: auto;
        padding: 0 0 1 0;
        color: $text;
        text-style: bold;
    }
    #picker-list {
        height: auto;
        max-height: 24;
    }
    #picker-hint {
        height: 1;
        padding: 1 0 0 0;
        color: $text-muted;
    }
    """

    BINDINGS = [
        Binding("enter", "pick", "Download", priority=True),
        Binding("escape", "cancel", "Back"),
        Binding("down", "list_cursor('down')", "Down", show=False, priority=True),
        Binding("up", "list_cursor('up')", "Up", show=False, priority=True),
    ]

    def __init__(
        self,
        group: RomGroup,
        local_stems: set[str],
        on_picked: Callable[["RomEntry"], None],
    ) -> None:
        super().__init__()
        self.group = group
        self.local_stems = local_stems
        self._on_picked = on_picked

    def compose(self) -> ComposeResult:
        rows = []
        for v in self.group.variants:
            owned = BrowseApp._entry_stem(v.name) in self.local_stems
            rows.append(VariantRow(v, owned=owned))
        yield Container(
            Static(
                f"Variants — [b]{self.group.title}[/b]  ({len(self.group.variants)} total)",
                id="picker-title",
            ),
            ListView(*rows, id="picker-list"),
            Static("enter download · esc back", id="picker-hint"),
            id="picker-box",
        )

    def on_mount(self) -> None:
        listv = self.query_one("#picker-list", ListView)
        if self.group.variants:
            listv.index = 0
        listv.focus()

    def action_list_cursor(self, direction: str) -> None:
        listv = self.query_one("#picker-list", ListView)
        if direction == "down":
            listv.action_cursor_down()
        else:
            listv.action_cursor_up()

    def action_pick(self) -> None:
        listv = self.query_one("#picker-list", ListView)
        idx = listv.index if listv.index is not None else 0
        if not (0 <= idx < len(self.group.variants)):
            return
        chosen = self.group.variants[idx]
        self._on_picked(chosen)
        self.dismiss(None)

    def on_list_view_selected(self, event: ListView.Selected) -> None:
        """Enter pressed on a focused variant row → pick it."""
        if event.list_view.id == "picker-list":
            self.action_pick()

    def action_cancel(self) -> None:
        self.dismiss(None)


class BrowseApp(App):
    """Textual app — retrokix browse."""

    CSS = """
    Screen {
        background: $surface;
    }

    #search-row {
        height: 3;
        padding: 0 1;
        background: $boost;
    }

    Input {
        border: round $primary;
    }
    Input:focus {
        border: round $accent;
    }

    ListView {
        background: $surface;
        height: 1fr;
    }
    ListView > ListItem {
        padding: 0 2;
        height: 1;
    }
    ListView > ListItem.--highlight {
        background: $accent 30%;
    }

    .row {
        height: 1;
        width: 1fr;
    }
    .row-marker {
        width: 2;
        height: 1;
    }
    .row-console {
        width: 5;
        min-width: 5;
        height: 1;
        padding: 0 1 0 0;
    }
    .row-stars {
        width: 6;
        min-width: 6;
        height: 1;
        padding: 0 1 0 0;
    }
    .row-name {
        width: 1fr;
        height: 1;
        text-overflow: ellipsis;
    }
    .row-size {
        width: auto;
        min-width: 8;
        height: 1;
        padding: 0 0 0 2;
        text-align: right;
    }

    #status {
        dock: bottom;
        height: 1;
        padding: 0 2;
        background: $boost;
        color: $text-muted;
    }
    """

    BINDINGS = [
        Binding("ctrl+q", "quit", "Quit", priority=True),
        Binding("ctrl+c", "quit", "Quit", priority=True, show=False),
        # 'enter' is intentionally NOT bound at the App level — we wire
        # it via Input.Submitted / ListView.Selected event handlers so
        # the variant-picker modal's own 'enter' binding wins when it's
        # on top of the screen stack.
        Binding("escape", "clear_or_quit", "Clear/Quit"),
        # Forward up/down/page-up/page-down to the list even when
        # the search Input has focus — that's the whole point.
        Binding("down", "list_cursor('down')", "Down", show=False),
        Binding("up", "list_cursor('up')", "Up", show=False),
        Binding("pagedown", "list_cursor('page_down')", "Page Down", show=False),
        Binding("pageup", "list_cursor('page_up')", "Page Up", show=False),
    ]

    query_text: reactive[str] = reactive("")

    def __init__(self, lib: "RomLibrary", initial_query: str = "") -> None:
        super().__init__()
        self.lib = lib
        self._initial_query = initial_query
        self._results: list[RomGroup] = []
        self._downloading = False
        self._famous_cache: list[RomGroup] | None = None
        self._local_stems: set[str] = set()
        self._local_paths: dict[str, Path] = {}
        self._dl_name: str = ""
        self._dl_total: int = 1

    def _refresh_local(self) -> None:
        """Re-scan the on-disk ROM folder. Stems (filename minus suffix)
        are the matching key against archive entry names."""
        from retrokix.library import list_local_roms

        try:
            paths = list_local_roms(self.lib.roms_dir)
        except (FileNotFoundError, OSError):
            paths = []
        self._local_stems = {p.stem for p in paths}
        self._local_paths = {p.stem: p for p in paths}

    def _group_local_path(self, group: RomGroup) -> Path | None:
        """Return the on-disk path of any owned variant of this group,
        preferring the canonical primary variant first."""
        for v in group.variants:
            stem = self._entry_stem(v.name)
            if stem in self._local_paths:
                return self._local_paths[stem]
        return None

    @staticmethod
    def _entry_stem(name: str) -> str:
        """Strip the archive extension (.zip / per-console ROM) for
        ownership matching. Same suffix set as `library.ALL_ROM_EXTS`."""
        from retrokix.library import ALL_ROM_EXTS
        lower = name.lower()
        for suffix in (".zip",) + ALL_ROM_EXTS:
            if lower.endswith(suffix):
                return name[: -len(suffix)]
        return name

    def _default_top_groups(self) -> list[RomGroup]:
        """Default (empty-query) view: top groups ranked by Wikipedia
        fame across all loaded consoles. Falls back to the curated
        `_FAMOUS_QUERIES` cohort when the fame snapshot is missing or
        too thin to populate MAX_RESULTS — partial smoke-test snapshots
        otherwise put 95 alphabetical leftovers behind 5 famous picks."""
        if self._famous_cache is not None:
            return self._famous_cache
        from retrokix.library import _load_fame
        fame = _load_fame()
        ranked_count = sum(
            1 for c in fame.values() for info in c.values()
            if info.get("views_12mo", 0) > 0
        )
        if ranked_count >= MAX_RESULTS:
            self._famous_cache = _sort_by_fame(_group_entries(self.lib.entries()))[:MAX_RESULTS]
        else:
            self._famous_cache = self._famous_groups()
        return self._famous_cache

    def _famous_groups(self) -> list[RomGroup]:
        """Resolve the curated famous-games queries to grouped variants.

        For each query, find its best-matching title and add the whole
        group (all regional/version variants) to the famous list.
        Cached after first call — the No-Intro index is frozen.
        """
        if self._famous_cache is not None:
            return self._famous_cache

        all_entries = self.lib.entries()
        # Map title → all entries with that title.
        groups_by_title = _group_entries(all_entries)
        title_to_group = {g.title: g for g in groups_by_title}

        seen_titles: set[str] = set()
        out: list[RomGroup] = []
        for q in _FAMOUS_QUERIES:
            tokens = [t for t in q.lower().split() if t]
            if not tokens:
                continue
            matches = [
                e for e in all_entries
                if all(t in e.name.lower() for t in tokens)
            ]
            if not matches:
                continue
            matches.sort(key=lambda e: (_region_score(e.name.lower()), len(e.name)))
            # Take the title of the canonical match; fall through to
            # alternatives if it was already used.
            for candidate in matches:
                title = _title_key(candidate.name)
                if title not in seen_titles and title in title_to_group:
                    seen_titles.add(title)
                    out.append(title_to_group[title])
                    break
            if len(out) >= MAX_RESULTS:
                break

        self._famous_cache = out
        return out

    def compose(self) -> ComposeResult:
        yield Header()
        with Vertical(id="search-row"):
            yield Input(
                placeholder="search ROMs — type any tokens, e.g. 'zelda minish'",
                id="q",
            )
        yield ListView(id="results")
        yield Static("", id="status")
        yield Footer()

    def on_mount(self) -> None:
        self.title = "retrokix browse"
        self._refresh_local()
        inp = self.query_one("#q", Input)
        inp.value = self._initial_query
        inp.focus()
        # Input.on_changed doesn't fire from .value = … so seed manually.
        self.query_text = self._initial_query
        self._refresh()

    def watch_query_text(self, _old: str, _new: str) -> None:
        self._refresh()

    def on_input_changed(self, event: Input.Changed) -> None:
        if event.input.id == "q":
            self.query_text = event.value

    def on_input_submitted(self, event: Input.Submitted) -> None:
        """Enter pressed in the search input → behave as 'download
        highlighted'. Input absorbs the keypress; this is how we hear
        about it without a priority binding."""
        if event.input.id == "q":
            self.action_download_selected()

    def on_list_view_selected(self, event: ListView.Selected) -> None:
        """Enter pressed on a focused list row → same."""
        if event.list_view.id == "results":
            self.action_download_selected()

    def _group_is_owned(self, group: RomGroup) -> bool:
        return any(
            self._entry_stem(v.name) in self._local_stems for v in group.variants
        )

    def _refresh(self) -> None:
        q = self.query_text.strip()
        is_default = not q
        if q:
            groups = _sort_by_fame(_group_entries(self.lib.search(q)))
        else:
            groups = self._default_top_groups()
        self._results = groups[:MAX_RESULTS]

        listv = self.query_one("#results", ListView)
        listv.clear()
        for g in self._results:
            listv.append(GroupRow(g, owned=self._group_is_owned(g)))
        # Pre-select the first row so Enter works without an arrow press.
        if self._results:
            listv.index = 0

        shown = len(self._results)
        if is_default:
            full_count = len(self.lib.entries())
            label = f"{shown} famous picks · type to search {full_count:,} ROMs"
        else:
            full_count = len(groups)
            matched_word = "title" if full_count == 1 else "titles"
            truncated = (
                f" (top {MAX_RESULTS} shown)" if full_count > MAX_RESULTS else ""
            )
            variant_total = sum(len(g.variants) for g in self._results)
            label = (
                f"{full_count} {matched_word}{truncated} · "
                f"{variant_total} variants total"
            )
        self._set_status(label)

    def _set_status(self, text: str) -> None:
        self.query_one("#status", Static).update(text)

    def action_list_cursor(self, direction: str) -> None:
        # Don't fight the modal's own arrow bindings.
        if isinstance(self.screen, ModalScreen):
            return
        listv = self.query_one("#results", ListView)
        if direction == "down":
            listv.action_cursor_down()
        elif direction == "up":
            listv.action_cursor_up()
        elif direction == "page_down":
            for _ in range(10):
                listv.action_cursor_down()
        elif direction == "page_up":
            for _ in range(10):
                listv.action_cursor_up()

    def action_clear_or_quit(self) -> None:
        inp = self.query_one("#q", Input)
        if inp.value:
            inp.value = ""
            self.query_text = ""
            inp.focus()
        else:
            self.exit()

    def action_download_selected(self) -> None:
        """Enter on a row: if any variant is already on disk, exit the
        TUI with that path so the wrapper CLI can `retrokix play` it.
        Otherwise start a download with a live progress bar and exit
        with the new path on success."""
        if self._downloading:
            return
        if isinstance(self.screen, ModalScreen):
            return
        listv = self.query_one("#results", ListView)
        idx = listv.index
        if idx is None or idx < 0 or idx >= len(self._results):
            self._set_status("nothing selected")
            return
        group = self._results[idx]
        owned = self._group_local_path(group)
        if owned is not None:
            # Brief visual confirmation so the user sees *something* happen
            # before the TUI tears down and the SDL window pops up. Without
            # this, an owned-ROM Enter looks identical to a no-op.
            self._set_status(
                f"[#34d399]●[/]  launching {_trim_name(owned.name, 60)}…"
            )
            self.set_timer(0.35, lambda: self.exit(owned))
            return
        if len(group.variants) == 1:
            self._download(group.primary)
        else:
            self.push_screen(
                VariantPicker(
                    group=group,
                    local_stems=self._local_stems,
                    on_picked=self._download,
                )
            )

    def _download(self, entry: "RomEntry") -> None:
        self._downloading = True
        self._dl_name = _trim_name(entry.name, 40)
        self._dl_total = max(entry.size, 1)
        self._set_status(self._format_progress(0))

        # The HTTP stream fires `progress_cb` per 64 KB chunk — many
        # hundreds of times per second on a fast link. Throttle to whole
        # percent ticks so we don't flood `call_from_thread`.
        last_pct = [-1]
        def cb(downloaded: int, _total: int) -> None:
            pct = int(downloaded * 100 / self._dl_total) if self._dl_total else 100
            if pct == last_pct[0]:
                return
            last_pct[0] = pct
            self.call_from_thread(self._on_progress, downloaded)

        self.run_worker(
            lambda: self.lib.download(entry, progress=False, progress_cb=cb),
            thread=True,
            exclusive=True,
            name="rom-download",
            description=f"download {entry.name}",
        )

    def _format_progress(self, downloaded: int) -> str:
        """Render a textual progress bar inline in the status line —
        more reliable than a ProgressBar widget (which has composite
        layout quirks under dock:bottom + height:1)."""
        total = max(self._dl_total, 1)
        pct = min(100, int(downloaded * 100 / total))
        width = 24
        filled = width * pct // 100
        bar = "█" * filled + "░" * (width - filled)
        mb_done = downloaded / 1_048_576
        mb_total = total / 1_048_576
        return (
            f"downloading {self._dl_name}  "
            f"[#a78bfa]{bar}[/]  {pct:>3d}%  "
            f"[dim]{mb_done:>5.1f}/{mb_total:.1f} MB[/]"
        )

    def _on_progress(self, downloaded: int) -> None:
        if self._downloading:
            self._set_status(self._format_progress(downloaded))

    def on_worker_state_changed(self, event) -> None:
        from textual.worker import WorkerState

        if event.worker.name != "rom-download":
            return
        state = event.state
        if state == WorkerState.SUCCESS:
            self._downloading = False
            path: Path = event.worker.result
            # Hand the path back to the wrapper CLI — it'll exec `play`.
            self.exit(path)
        elif state == WorkerState.ERROR:
            self._downloading = False
            err = event.worker.error
            self._set_status(f"error: {err}")


def run(lib: "RomLibrary", initial_query: str = "") -> "Path | None":
    """Launch the TUI. Returns the picked ROM path (if Enter was pressed
    on a row), or None if the user quit without picking. The wrapper CLI
    is expected to `retrokix play <path>` on the returned value."""
    app = BrowseApp(lib=lib, initial_query=initial_query)
    app.run()
    result = app.return_value
    if isinstance(result, Path):
        return result
    return None
