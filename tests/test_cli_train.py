"""Tests for `gbax train`."""

from __future__ import annotations

import json
import sys
from pathlib import Path

from typer.testing import CliRunner

from gbax.cli import app


runner = CliRunner()
FIXTURES = Path(__file__).parent / "fixtures"


def test_train_requires_scenario():
    result = runner.invoke(app, ["train"])
    assert result.exit_code != 0


def test_train_runs_minimal_to_completion(monkeypatch, tmp_path, test_rom):
    monkeypatch.setenv("HOME", str(tmp_path))
    bot_path = FIXTURES / "minimal_bot.py"
    scenario_path = FIXTURES / "minimal_scenario.py"

    result = runner.invoke(app, [
        "train",
        "--rom", str(test_rom),
        "--scenario", str(scenario_path),
        "--player", f"{sys.executable} {bot_path}",
        "--output", str(tmp_path),
    ])
    assert result.exit_code == 0, result.output
    out_json = tmp_path / "result.json"
    assert out_json.exists()
    data = json.loads(out_json.read_text())
    assert data["reason"] == "scored"
    assert data["result"]["score"] <= -30.0
