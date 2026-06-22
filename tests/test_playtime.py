"""Tests for retrokix.tui.playtime — per-ROM session + total play time."""
from __future__ import annotations

from retrokix.tui import playtime as P


def test_load_total_absent_is_zero(tmp_path):
    assert P.load_total("abc123", root=tmp_path) == 0.0


def test_add_session_persists_and_returns_total(tmp_path):
    total = P.add_session("abc123", 90.0, root=tmp_path)
    assert total == 90.0
    assert P.load_total("abc123", root=tmp_path) == 90.0


def test_add_session_accumulates(tmp_path):
    P.add_session("abc123", 90.0, root=tmp_path)
    total = P.add_session("abc123", 30.0, root=tmp_path)
    assert total == 120.0


def test_sessions_are_per_sha1(tmp_path):
    P.add_session("aaa", 10.0, root=tmp_path)
    P.add_session("bbb", 5.0, root=tmp_path)
    assert P.load_total("aaa", root=tmp_path) == 10.0
    assert P.load_total("bbb", root=tmp_path) == 5.0


def test_playtime_session_seconds_uses_injected_clock(tmp_path):
    clock = iter([100.0, 105.0])
    pt = P.PlayTime("abc", root=tmp_path, clock=lambda: next(clock))
    pt.start()  # reads 100.0
    assert pt.session_seconds == 5.0  # reads 105.0


def test_playtime_total_includes_persisted_plus_session(tmp_path):
    P.add_session("abc", 60.0, root=tmp_path)
    clock = iter([0.0, 10.0])
    pt = P.PlayTime("abc", root=tmp_path, clock=lambda: next(clock))
    pt.start()
    assert pt.total_seconds == 70.0


def test_flush_persists_session_and_resets(tmp_path):
    clock = iter([0.0, 25.0, 25.0, 25.0])
    pt = P.PlayTime("abc", root=tmp_path, clock=lambda: next(clock))
    pt.start()
    pt.flush()
    assert P.load_total("abc", root=tmp_path) == 25.0
    assert pt.session_seconds == 0.0
