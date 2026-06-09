"""CLI smoke tests for `gbax play`."""

from __future__ import annotations

from typer.testing import CliRunner

from gbax.cli import app


runner = CliRunner()


def test_play_requires_rom_arg():
    result = runner.invoke(app, ["play"])
    assert result.exit_code != 0


def test_play_rejects_nonexistent_rom():
    result = runner.invoke(app, ["play", "/nonexistent.gba"])
    assert result.exit_code != 0


def test_keymap_covers_all_buttons():
    from gbax.input import Button
    from gbax.render.sdl import default_keymap
    km = default_keymap()
    assert set(km.values()) == set(Button)
