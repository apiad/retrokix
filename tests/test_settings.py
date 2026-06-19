"""Tests for retrokix.settings — per-ROM persisted preferences."""

from __future__ import annotations

from pathlib import Path

from retrokix import settings


def test_load_returns_defaults_when_missing(tmp_path: Path) -> None:
    s = settings.load("deadbeef", root=tmp_path)
    assert s == settings.RomSettings()
    assert s.speed_multiplier == 1.0
    assert s.fullscreen is False
    assert s.window_scale == 3
    assert s.last_slot is None


def test_save_then_load_roundtrips(tmp_path: Path) -> None:
    src = settings.RomSettings(
        speed_multiplier=2.0, fullscreen=True, window_scale=4, last_slot=3,
    )
    settings.save("rom1", src, root=tmp_path)
    got = settings.load("rom1", root=tmp_path)
    assert got == src


def test_update_merges_partial_changes(tmp_path: Path) -> None:
    settings.save(
        "rom2",
        settings.RomSettings(speed_multiplier=1.5, fullscreen=True, window_scale=4),
        root=tmp_path,
    )
    new = settings.update("rom2", root=tmp_path, last_slot=7)
    assert new.last_slot == 7
    # Untouched fields preserved.
    assert new.speed_multiplier == 1.5
    assert new.fullscreen is True
    assert new.window_scale == 4


def test_update_ignores_unknown_keys(tmp_path: Path) -> None:
    """Forward-compat: a future field doesn't break older code."""
    new = settings.update("rom3", root=tmp_path, future_field="ignored", speed_multiplier=2.0)
    assert new.speed_multiplier == 2.0
    assert not hasattr(new, "future_field")


def test_update_noop_when_no_changes(tmp_path: Path) -> None:
    """Calling update with the current value shouldn't rewrite the file."""
    settings.save("rom4", settings.RomSettings(window_scale=5), root=tmp_path)
    # mtime resolution would need a sleep to verify no-write; instead
    # we just confirm the return value matches what's on disk and the
    # call doesn't raise.
    got = settings.update("rom4", root=tmp_path, window_scale=5)
    assert got.window_scale == 5


def test_from_dict_filters_unknown_keys() -> None:
    s = settings.RomSettings.from_dict({"speed_multiplier": 3.0, "garbage": 99})
    assert s.speed_multiplier == 3.0
    assert not hasattr(s, "garbage")


def test_load_corrupt_json_returns_defaults(tmp_path: Path) -> None:
    p = settings._path_for("corrupt", root=tmp_path)
    p.parent.mkdir(parents=True, exist_ok=True)
    p.write_text("{not valid json")
    s = settings.load("corrupt", root=tmp_path)
    assert s == settings.RomSettings()


def test_load_non_object_json_returns_defaults(tmp_path: Path) -> None:
    p = settings._path_for("array", root=tmp_path)
    p.parent.mkdir(parents=True, exist_ok=True)
    p.write_text("[1, 2, 3]")
    s = settings.load("array", root=tmp_path)
    assert s == settings.RomSettings()


def test_save_is_atomic_via_tmp_then_rename(tmp_path: Path, monkeypatch) -> None:
    """A crash during write must not leave a partial JSON at the target.

    Simulated by forcing os.replace to fail after the tmp file is
    written; the target should remain at its previous content (here,
    nonexistent).
    """
    import os
    target = settings._path_for("atomic", root=tmp_path)

    def fail_replace(src, dst):
        raise OSError("disk full")

    monkeypatch.setattr(os, "replace", fail_replace)
    try:
        settings.save("atomic", settings.RomSettings(speed_multiplier=4.0), root=tmp_path)
    except OSError:
        pass
    assert not target.exists()
    # And the tmp file should have been cleaned up.
    leftover = list(target.parent.glob(".atomic.*.tmp"))
    assert leftover == []
