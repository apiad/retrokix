"""Tests for the gbax state CLI subcommands."""
from __future__ import annotations

import json
from datetime import datetime, timezone

from typer.testing import CliRunner

from gbax.cli import app
from gbax.state.capture import save_capture
from gbax.state.compile import compile_for_rom


SHA1 = "abc"
runner = CliRunner()


def _seed(tmp_path):
    save_capture(SHA1,
                 {("ewram", 0x100): 45},
                 {"hp": 45},
                 datetime(2026, 6, 10, 1, 0, 0, tzinfo=timezone.utc),
                 root=tmp_path)
    save_capture(SHA1,
                 {("ewram", 0x100): 23},
                 {"hp": 23},
                 datetime(2026, 6, 10, 1, 0, 1, tzinfo=timezone.utc),
                 root=tmp_path)


def _patch(monkeypatch, tmp_path):
    monkeypatch.setattr("gbax.state.storage.DEFAULT_STATE_ROOT", tmp_path)
    monkeypatch.setattr("gbax.cli._resolve_rom_sha1", lambda rom: (tmp_path / "rom.gba", SHA1))


def test_state_compile_writes_json(monkeypatch, tmp_path):
    _patch(monkeypatch, tmp_path)
    _seed(tmp_path)
    result = runner.invoke(app, ["state", "compile", "anything"])
    assert result.exit_code == 0, result.output
    out = tmp_path / SHA1 / "compiled.json"
    assert out.exists()
    payload = json.loads(out.read_text())
    assert "hp" in payload["tags"]


def test_state_list_shows_tags_and_captures(monkeypatch, tmp_path):
    _patch(monkeypatch, tmp_path)
    _seed(tmp_path)
    compile_for_rom(SHA1, root=tmp_path)
    result = runner.invoke(app, ["state", "list", "anything"])
    assert result.exit_code == 0
    assert "hp" in result.output
    assert "captures: 2" in result.output


def test_state_list_no_compiled_says_so(monkeypatch, tmp_path):
    _patch(monkeypatch, tmp_path)
    _seed(tmp_path)
    result = runner.invoke(app, ["state", "list", "anything"])
    assert result.exit_code == 0
    assert "not compiled" in result.output.lower()


def test_state_ambiguous_lists_ambiguous_tags(monkeypatch, tmp_path):
    _patch(monkeypatch, tmp_path)
    save_capture(SHA1, {("ewram", 0x100): 45, ("ewram", 0x800): 45},
                 {"hp": 45},
                 datetime(2026, 6, 10, 1, 0, 0, tzinfo=timezone.utc),
                 root=tmp_path)
    save_capture(SHA1, {("ewram", 0x100): 23, ("ewram", 0x800): 23},
                 {"hp": 23},
                 datetime(2026, 6, 10, 1, 0, 1, tzinfo=timezone.utc),
                 root=tmp_path)
    compile_for_rom(SHA1, root=tmp_path)
    result = runner.invoke(app, ["state", "ambiguous", "anything"])
    assert result.exit_code == 0
    assert "hp" in result.output
