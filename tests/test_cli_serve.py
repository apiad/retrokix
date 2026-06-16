"""CLI smoke tests for `retrokix serve` (the hub).

`serve` no longer takes a ROM — it boots the hub that serves the game
grid + spawns per-game children. Real-uvicorn coverage lives outside
these tests; here we just confirm the typer wiring and --help text.
"""

from __future__ import annotations

from typer.testing import CliRunner

from retrokix.cli import app


runner = CliRunner()


def test_serve_help_describes_hub():
    result = runner.invoke(app, ["serve", "--help"])
    assert result.exit_code == 0
    assert "hub" in result.output.lower()
    assert "--port" in result.output
    assert "--roms-dir" in result.output
    assert "--no-open-browser" in result.output


def test_serve_takes_no_rom_argument():
    """Old shape was `retrokix serve <rom>`. New hub takes no positional.

    We send an unknown positional and expect typer to reject it."""
    result = runner.invoke(app, ["serve", "some-rom.gba"])
    assert result.exit_code != 0


def test_version_command():
    result = runner.invoke(app, ["version"])
    assert result.exit_code == 0
    assert "retrokix" in result.output
