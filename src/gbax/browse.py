"""Interactive ROM browser — `gbax browse`.

A Textual TUI over `RomLibrary`: search-as-you-type, arrow-keys to
navigate, Enter to download. The pure-CLI `gbax search` and `gbax
download` stay as-is for scripts and agents; this one is for humans
who want to poke around without remembering exact No-Intro names.

Design notes:
- Filter runs synchronously on every keystroke against the in-memory
  3,555-entry index. Plenty fast; no debounce needed.
- Downloads run in a thread worker so the UI stays responsive. The
  existing `RomLibrary.download` is blocking; we wrap it.
- We show all regional variants in the list so the user picks the
  exact one with arrow keys. That's the value over `gbax download
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
    from gbax.library import RomEntry, RomLibrary


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
)


def _title_key(name: str) -> str:
    """Group key for No-Intro names — everything before the first '('.

    e.g. 'Pokemon - Emerald Version (USA, Europe).zip' →
         'Pokemon - Emerald Version'

    This collapses regional/language/version variants of the same
    title into one group. If a name has no parenthetical, we strip
    the .zip/.gba suffix and use what remains.
    """
    paren = name.find("(")
    if paren > 0:
        return name[:paren].rstrip()
    if name.lower().endswith((".zip", ".gba")):
        return name.rsplit(".", 1)[0].rstrip()
    return name.rstrip()


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
    """

    title: str
    variants: list["RomEntry"] = field(default_factory=list)

    @property
    def primary(self) -> "RomEntry":
        return self.variants[0]

    @property
    def extra_count(self) -> int:
        return len(self.variants) - 1


def _group_entries(entries: list["RomEntry"]) -> list[RomGroup]:
    """Collapse a flat entry list into per-title groups, preserving the
    relative order of first appearance."""
    by_title: dict[str, RomGroup] = {}
    order: list[str] = []
    for e in entries:
        key = _title_key(e.name)
        g = by_title.get(key)
        if g is None:
            g = RomGroup(title=key, variants=[])
            by_title[key] = g
            order.append(key)
        g.variants.append(e)
    # Canonicalize variant order within each group.
    for g in by_title.values():
        g.variants.sort(key=lambda e: (_region_score(e.name.lower()), len(e.name)))
    return [by_title[k] for k in order]


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
    """Textual app — gbax browse."""

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

    def _refresh_local(self) -> None:
        """Re-scan the on-disk ROM folder. Stems (filename minus suffix)
        are the matching key against archive entry names."""
        from gbax.library import list_local_roms

        try:
            paths = list_local_roms(self.lib.roms_dir)
        except (FileNotFoundError, OSError):
            paths = []
        self._local_stems = {p.stem for p in paths}

    @staticmethod
    def _entry_stem(name: str) -> str:
        """Strip the archive extension (.zip / .gba) for ownership matching."""
        for suffix in (".zip", ".gba"):
            if name.lower().endswith(suffix):
                return name[: -len(suffix)]
        return name

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
        self.title = "gbax browse"
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
            groups = _group_entries(self.lib.search(q))
        else:
            groups = self._famous_groups()
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
        if self._downloading:
            return
        # A modal (e.g. the variant picker) is on top — let it handle Enter.
        if isinstance(self.screen, ModalScreen):
            return
        listv = self.query_one("#results", ListView)
        idx = listv.index
        if idx is None or idx < 0 or idx >= len(self._results):
            self._set_status("nothing selected")
            return
        group = self._results[idx]
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
        name = _trim_name(entry.name, 50)
        self._set_status(f"downloading {name} ({_fmt_size(entry.size)})…")
        self.run_worker(
            lambda: self.lib.download(entry, progress=False),
            thread=True,
            exclusive=True,
            name="rom-download",
            description=f"download {entry.name}",
        )

    def on_worker_state_changed(self, event) -> None:
        from textual.worker import WorkerState

        if event.worker.name != "rom-download":
            return
        state = event.state
        if state == WorkerState.SUCCESS:
            self._downloading = False
            path: Path = event.worker.result
            self._set_status(f"saved → {path}")
            # Refresh the owned-marker — the new ROM now exists on disk.
            self._refresh_local()
            self._refresh()
        elif state == WorkerState.ERROR:
            self._downloading = False
            err = event.worker.error
            self._set_status(f"error: {err}")


def run(lib: "RomLibrary", initial_query: str = "") -> int:
    """Launch the TUI. Returns the process exit code."""
    app = BrowseApp(lib=lib, initial_query=initial_query)
    app.run()
    return 0
