"""Tests for the Route panel formatter + pane."""
from __future__ import annotations

from textual.app import App, ComposeResult

from retrokix.tui.route_widget import RoutePane, format_encounters


def test_format_encounters_lists_species_and_catch():
    enc = {
        "location": (0, 16),
        "land": [{"species": 261, "name": "Poochyena", "rate": 40, "min": 2, "max": 3}],
        "water": [],
        "fishing": [],
    }
    out = format_encounters(enc, ("Poke-Ball", 1.0))
    assert "Poochyena" in out
    assert "L2-3" in out
    assert "40%" in out
    assert "catch" in out
    assert "Poke-Ball" in out


def test_format_encounters_empty_is_no_encounters():
    enc = {"location": (0, 11), "land": [], "water": [], "fishing": []}
    assert "No wild encounters" in format_encounters(enc, ("Poke-Ball", 1.0))


class _Host(App):
    def __init__(self, pane):
        super().__init__()
        self._pane = pane

    def compose(self) -> ComposeResult:
        yield self._pane


async def test_route_pane_empty_without_runtime():
    app = _Host(RoutePane(ctx=None))
    async with app.run_test():
        assert app.query_one("#route-empty").display is True
