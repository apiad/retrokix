"""CoreTab — the always-present native retrokix tab.

Generic, every-game status: an ASCII banner, current game, play time, and
(when ``--listen``) the API endpoint and connected-client count. Also hosts
the log pane that replaces play-time ``print`` output (Textual owns the
terminal, so stray prints would corrupt the display).

``format_status`` is a pure function over a :class:`Status` snapshot so it can
be unit-tested without Textual.
"""

from __future__ import annotations

from textual.app import ComposeResult
from textual.containers import VerticalScroll
from textual.widgets import RichLog, Static

from retrokix.tui.status import Status

BANNER = r"""
 ┳━┓┏━╸╺┳╸┏━┓┏━┓╻ ╻╻╻ ╻
 ┣┳┛┣╸  ┃ ┣┳┛┃ ┃┣┻┓┃┏╋┛
 ╹┗╸┗━╸ ╹ ╹┗╸┗━┛╹ ╹╹╹ ╹
"""


def _fmt_duration(seconds: float) -> str:
    total = int(seconds)
    h, rem = divmod(total, 3600)
    m, s = divmod(rem, 60)
    if h:
        return f"{h}h {m:02d}m"
    return f"{m}m {s:02d}s"


def format_status(s: Status) -> str:
    """Render a status snapshot as Rich markup for the core tab."""
    title = s.title or "—"
    console = f" [{s.console}]" if s.console else ""
    sha = f"  [dim]{s.sha1[:8]}[/dim]" if s.sha1 else ""
    lines = [
        f"[b]{title}[/b]{console}{sha}",
        f"FPS [b]{s.fps:.0f}[/b]    Speed {s.speed:g}×    Frame {s.frame_count}",
        f"Session [b]{_fmt_duration(s.session_seconds)}[/b]"
        f"    Total {_fmt_duration(s.total_seconds)}",
    ]
    if s.api_endpoint:
        lines.append(f"[green]API[/green] http://{s.api_endpoint}    Clients {s.client_count}")
    return "\n".join(lines)


class CoreTab(Static):
    """The native retrokix tab: banner + live status + log pane."""

    DEFAULT_CSS = """
    CoreTab { height: 1fr; }
    CoreTab #core-banner { color: $accent; }
    CoreTab #core-status { padding: 1 0; }
    CoreTab #core-log { height: 1fr; border: round $panel; }
    """

    def compose(self) -> ComposeResult:
        yield Static(BANNER, id="core-banner")
        yield Static(id="core-status")
        with VerticalScroll():
            yield RichLog(id="core-log", markup=True, max_lines=2000)

    def refresh_status(self, status: Status) -> None:
        self.query_one("#core-status", Static).update(format_status(status))

    def log_line(self, message: str) -> None:
        self.query_one("#core-log", RichLog).write(message)
