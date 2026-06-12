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

from pathlib import Path
from typing import TYPE_CHECKING

from textual.app import App, ComposeResult
from textual.binding import Binding
from textual.containers import Vertical
from textual.reactive import reactive
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


class RomRow(ListItem):
    """One row in the results list — holds a reference to its RomEntry."""

    def __init__(self, entry: "RomEntry") -> None:
        self.entry = entry
        super().__init__(Static(self._label()))

    def _label(self) -> str:
        name = _trim_name(self.entry.name, 70)
        size = _fmt_size(self.entry.size)
        return f"{name:<70}  [dim]{size:>8}[/dim]"


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
    }
    ListView > ListItem.--highlight {
        background: $accent 30%;
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
        Binding("enter", "download_selected", "Download", priority=True),
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
        self._results: list["RomEntry"] = []
        self._downloading = False
        self._famous_cache: list["RomEntry"] | None = None

    def _famous_entries(self) -> list["RomEntry"]:
        """Resolve the curated famous-games queries to concrete entries.
        Cached after first call — the No-Intro index is frozen."""
        if self._famous_cache is not None:
            return self._famous_cache

        all_entries = self.lib.entries()

        def region_score(name_lower: str) -> int:
            if "(usa" in name_lower or "(world" in name_lower:
                return 0
            if "(europe" in name_lower:
                return 1
            return 2

        seen: set[str] = set()
        out: list["RomEntry"] = []
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
            # Prefer USA/World, then shortest name (base game wins ties).
            matches.sort(key=lambda e: (region_score(e.name.lower()), len(e.name)))
            # If the top match was already claimed by an earlier query,
            # try the next-best match rather than skipping the slot.
            for candidate in matches:
                if candidate.name not in seen:
                    seen.add(candidate.name)
                    out.append(candidate)
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

    def _refresh(self) -> None:
        q = self.query_text.strip()
        is_default = not q
        if q:
            entries = self.lib.search(q)
        else:
            entries = self._famous_entries()
        self._results = entries[:MAX_RESULTS]

        listv = self.query_one("#results", ListView)
        listv.clear()
        for e in self._results:
            listv.append(RomRow(e))
        # Pre-select the first row so Enter works without an arrow press.
        if self._results:
            listv.index = 0

        shown = len(self._results)
        total_size = sum(e.size for e in self._results)
        if is_default:
            full_count = len(self.lib.entries())
            label = f"{shown} famous picks · type to search {full_count:,} ROMs"
        else:
            full_count = len(entries)
            matched_word = "match" if full_count == 1 else "matches"
            truncated = (
                f" (top {MAX_RESULTS} shown)" if full_count > MAX_RESULTS else ""
            )
            label = (
                f"{full_count} {matched_word}{truncated} · "
                f"total {_fmt_size(total_size)}"
            )
        self._set_status(label)

    def _set_status(self, text: str) -> None:
        self.query_one("#status", Static).update(text)

    def action_list_cursor(self, direction: str) -> None:
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
        listv = self.query_one("#results", ListView)
        idx = listv.index
        if idx is None or idx < 0 or idx >= len(self._results):
            self._set_status("nothing selected")
            return
        entry = self._results[idx]
        self._download(entry)

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
        elif state == WorkerState.ERROR:
            self._downloading = False
            err = event.worker.error
            self._set_status(f"error: {err}")


def run(lib: "RomLibrary", initial_query: str = "") -> int:
    """Launch the TUI. Returns the process exit code."""
    app = BrowseApp(lib=lib, initial_query=initial_query)
    app.run()
    return 0
