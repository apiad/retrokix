"""RetrokixTUI — the native Textual shell hosting the core tab + plugin tabs.

Runs on the main thread while the emulator + SDL loop runs on a worker thread
(see ``retrokix.render.sdl.play_loop``). The two communicate only through a
:class:`StatusSnapshot`, which the app polls on a timer to refresh the core
tab. Each loaded plugin contributes zero or more tabs via ``@p.tab(...)``; a
plugin tab whose factory raises is logged and skipped — it never takes down the
shell or the game.
"""

from __future__ import annotations

from dataclasses import dataclass
from typing import Callable

from textual.app import App, ComposeResult
from textual.css.query import NoMatches
from textual.widgets import Footer, TabbedContent, TabPane

from retrokix.tui.core_tab import CoreTab
from retrokix.tui.status import StatusSnapshot


@dataclass
class TabContext:
    """Handed to each plugin tab factory. Static tabs ignore ``runtime``."""

    title: str = ""
    console: str = ""
    sha1: str = ""
    rom_path: str = ""
    runtime: object | None = None


class RetrokixTUI(App):
    """Tabbed companion UI for a running game."""

    CSS = """
    TabbedContent { height: 1fr; }
    """
    BINDINGS = [("q", "quit", "Quit")]

    def __init__(
        self,
        snapshot: StatusSnapshot,
        tab_specs: list[tuple[str, Callable]] | None = None,
        tab_context: TabContext | None = None,
        poll_hz: float = 8.0,
    ) -> None:
        super().__init__()
        self._snapshot = snapshot
        self._tab_specs = tab_specs or []
        self._tab_context = tab_context or TabContext()
        self._poll_interval = 1.0 / poll_hz
        self._tab_errors: list[tuple[str, Exception]] = []

    def compose(self) -> ComposeResult:
        with TabbedContent():
            with TabPane("retrokix", id="tab-core"):
                yield CoreTab()
            for i, (title, factory) in enumerate(self._tab_specs):
                try:
                    widget = factory(self._tab_context)
                except Exception as exc:  # isolate a broken plugin tab
                    self._tab_errors.append((title, exc))
                    continue
                with TabPane(title, id=f"tab-plugin-{i}"):
                    yield widget
        yield Footer()

    def on_mount(self) -> None:
        core = self.query_one(CoreTab)
        for title, exc in self._tab_errors:
            core.log_line(f"[red]plugin tab {title!r} failed:[/red] {exc}")
        core.refresh_status(self._snapshot.read())
        self.set_interval(self._poll_interval, self._poll)

    def _poll(self) -> None:
        # A timer tick can land during shutdown, after the widgets are removed;
        # querying then raises NoMatches. Skip those ticks rather than crash.
        try:
            self.query_one(CoreTab).refresh_status(self._snapshot.read())
        except NoMatches:
            pass
