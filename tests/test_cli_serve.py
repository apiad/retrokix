"""CLI smoke tests for `gbax serve`."""

from __future__ import annotations

from typer.testing import CliRunner

from gbax.cli import app


runner = CliRunner()


def test_serve_requires_rom_arg():
    result = runner.invoke(app, ["serve"])
    assert result.exit_code != 0


def test_serve_rejects_nonexistent_rom():
    result = runner.invoke(app, ["serve", "/nonexistent.gba"])
    assert result.exit_code != 0


def test_version_command():
    result = runner.invoke(app, ["version"])
    assert result.exit_code == 0
    assert "gbax" in result.output
