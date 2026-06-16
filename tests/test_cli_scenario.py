"""Tests for `retrokix scenario create / list / validate`."""

from __future__ import annotations

from pathlib import Path

from typer.testing import CliRunner

from retrokix.cli import app


runner = CliRunner()


def test_scenario_list_runs(monkeypatch, tmp_path):
    monkeypatch.setenv("HOME", str(tmp_path))
    result = runner.invoke(app, ["scenario", "list"])
    assert result.exit_code == 0


def test_scenario_validate_good_file(test_rom, tmp_path):
    fixture = Path(__file__).parent / "fixtures" / "minimal_scenario.py"
    result = runner.invoke(app, ["scenario", "validate", str(fixture)])
    assert result.exit_code == 0
    assert "MinimalScenario" in result.output


def test_scenario_validate_missing_file():
    result = runner.invoke(app, ["scenario", "validate", "/nonexistent.py"])
    assert result.exit_code != 0


def test_scenario_create_writes_template(monkeypatch, tmp_path, test_rom):
    monkeypatch.setenv("HOME", str(tmp_path))
    result = runner.invoke(app, [
        "scenario", "create", str(test_rom), "--name", "smoke"
    ])
    assert result.exit_code == 0, result.output
    out_path = Path(result.output.strip().split()[-1])
    assert out_path.exists()
    content = out_path.read_text()
    assert "class" in content
    assert "rom_sha1 = " in content
    assert "b6a631b57969143ddcb7b85553e1e1ea4448a631" in content
