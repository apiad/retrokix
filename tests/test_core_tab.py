"""Pure tests for retrokix.tui.core_tab formatting helpers."""
from __future__ import annotations

from retrokix.tui.core_tab import _fmt_duration, format_status
from retrokix.tui.status import Status


def test_fmt_duration_minutes_and_seconds():
    assert _fmt_duration(125) == "2m 05s"


def test_fmt_duration_promotes_to_hours():
    assert _fmt_duration(3725) == "1h 02m"


def test_format_status_shows_game_and_frame():
    text = format_status(Status(title="Emerald", console="GBA", fps=60.0, frame_count=10))
    assert "Emerald" in text
    assert "GBA" in text
    assert "Frame 10" in text


def test_format_status_without_api_omits_endpoint():
    text = format_status(Status(title="Game"))
    assert "API" not in text


def test_format_status_with_api_shows_clients():
    text = format_status(
        Status(title="Game", api_endpoint="127.0.0.1:8420", client_count=2)
    )
    assert "127.0.0.1:8420" in text
    assert "Clients 2" in text
