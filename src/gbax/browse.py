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
        if q:
            entries = self.lib.search(q)
        else:
            entries = self.lib.entries()
        self._results = entries

        listv = self.query_one("#results", ListView)
        listv.clear()
        for e in entries[:500]:  # 500 cap keeps initial render snappy
            listv.append(RomRow(e))
        # Pre-select the first row so Enter works without an arrow press.
        if entries:
            listv.index = 0

        truncated = " (top 500 shown)" if len(entries) > 500 else ""
        total_size = sum(e.size for e in entries)
        self._set_status(
            f"{len(entries)} match{'es' if len(entries) != 1 else ''}{truncated} · "
            f"total {_fmt_size(total_size)}"
        )

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
