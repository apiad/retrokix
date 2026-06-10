"""Tests for the gbax macros / macro CLI subcommands."""
from __future__ import annotations

from datetime import datetime, timezone

from typer.testing import CliRunner

from gbax.cli import app
from gbax.input import Button
from gbax.macros import Macro, save


SHA1 = "f3ae088181bf583e55daf962a92bb46f4f1d07b7"
runner = CliRunner()


def _seed(tmp_path):
    save(
        Macro(
            slot="F3", name="heal-pc", rom_sha1=SHA1, rom_name="Pokemon.gba",
            recorded_at=datetime(2026, 6, 10, 12, 0, 0, tzinfo=timezone.utc),
            total_frames=123,
            events=[(0, frozenset()), (5, frozenset({Button.A}))],
        ),
        macros_root=tmp_path,
    )
    save(
        Macro(
            slot="F5", name="", rom_sha1=SHA1, rom_name="Pokemon.gba",
            recorded_at=datetime(2026, 6, 10, 12, 5, 0, tzinfo=timezone.utc),
            total_frames=47,
            events=[(0, frozenset())],
        ),
        macros_root=tmp_path,
    )


def test_macros_list(monkeypatch, tmp_path):
    _seed(tmp_path)
    monkeypatch.setattr("gbax.macros.DEFAULT_MACROS_ROOT", tmp_path)
    monkeypatch.setattr("gbax.cli._resolve_rom_sha1", lambda rom: (tmp_path / "rom.gba", SHA1))
    result = runner.invoke(app, ["macros", "anything"])
    assert result.exit_code == 0
    assert "F3" in result.stdout and "heal-pc" in result.stdout and "123" in result.stdout
    assert "F5" in result.stdout and "(unnamed)" in result.stdout and "47" in result.stdout


def test_macro_delete(monkeypatch, tmp_path):
    _seed(tmp_path)
    monkeypatch.setattr("gbax.macros.DEFAULT_MACROS_ROOT", tmp_path)
    monkeypatch.setattr("gbax.cli._resolve_rom_sha1", lambda rom: (tmp_path / "rom.gba", SHA1))
    result = runner.invoke(app, ["macro", "delete", "anything", "F3"])
    assert result.exit_code == 0
    assert "deleted F3" in result.stdout
    result2 = runner.invoke(app, ["macros", "anything"])
    assert "F3" not in result2.stdout
    assert "F5" in result2.stdout


def test_macro_delete_missing(monkeypatch, tmp_path):
    monkeypatch.setattr("gbax.macros.DEFAULT_MACROS_ROOT", tmp_path)
    monkeypatch.setattr("gbax.cli._resolve_rom_sha1", lambda rom: (tmp_path / "rom.gba", SHA1))
    result = runner.invoke(app, ["macro", "delete", "anything", "F3"])
    assert result.exit_code == 1
    assert "no macro" in (result.stdout + result.stderr).lower()
