"""Tests for `gbax tournament`."""

from __future__ import annotations

import json
import sys
from pathlib import Path

from typer.testing import CliRunner

from gbax.cli import app


runner = CliRunner()
FIXTURES = Path(__file__).parent / "fixtures"


def test_tournament_requires_scenario_and_players():
    result = runner.invoke(app, ["tournament"])
    assert result.exit_code != 0


def test_tournament_runs_two_players_writes_leaderboard(
    monkeypatch, tmp_path, test_rom
):
    monkeypatch.setenv("HOME", str(tmp_path))
    bot = f"{sys.executable} {FIXTURES / 'minimal_bot.py'}"
    scenario_path = FIXTURES / "minimal_scenario.py"

    result = runner.invoke(app, [
        "tournament",
        "--rom", str(test_rom),
        "--scenario", str(scenario_path),
        "--player", bot,
        "--player", bot,
        "--output", str(tmp_path),
    ])
    assert result.exit_code == 0, result.output
    out_json = tmp_path / "results.json"
    assert out_json.exists()
    data = json.loads(out_json.read_text())
    assert len(data["matches"]) == 2
    assert all(m["reason"] in ("scored", "timeout") for m in data["matches"])
    assert "leaderboard" in data
    assert len(data["leaderboard"]) == 2
