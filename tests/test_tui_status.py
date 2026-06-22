"""Tests for retrokix.tui.status — the lock-guarded status snapshot."""
from __future__ import annotations

from retrokix.tui.status import Status, StatusSnapshot


def test_default_read_is_empty_status():
    snap = StatusSnapshot()
    s = snap.read()
    assert isinstance(s, Status)
    assert s.fps == 0.0
    assert s.client_count == 0
    assert s.api_endpoint is None


def test_publish_updates_fields():
    snap = StatusSnapshot()
    snap.publish(title="Pokémon Emerald", fps=59.7, frame_count=42)
    s = snap.read()
    assert s.title == "Pokémon Emerald"
    assert s.fps == 59.7
    assert s.frame_count == 42


def test_partial_publish_preserves_other_fields():
    snap = StatusSnapshot()
    snap.publish(title="Game", speed=2.0)
    snap.publish(fps=60.0)
    s = snap.read()
    assert s.title == "Game"
    assert s.speed == 2.0
    assert s.fps == 60.0
