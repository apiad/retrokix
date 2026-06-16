"""StepDriver — untimed training loop."""

from __future__ import annotations

import sys
from pathlib import Path

import pytest

from retrokix.driver import MatchOutcome, StepDriver


FIXTURES = Path(__file__).parent / "fixtures"


@pytest.fixture
def minimal_scenario_cls():
    from retrokix.scenario import load_scenario_file
    return load_scenario_file(FIXTURES / "minimal_scenario.py", "MinimalScenario")


def test_step_driver_runs_minimal_to_done(test_rom, mgba_core, minimal_scenario_cls):
    bot_cmd = [sys.executable, str(FIXTURES / "minimal_bot.py")]
    driver = StepDriver(
        rom_path=test_rom,
        scenario_cls=minimal_scenario_cls,
        core_path=mgba_core,
    )
    outcome = driver.run_match(player_cmd=bot_cmd, player_label="minimal")
    assert isinstance(outcome, MatchOutcome)
    assert outcome.reason == "scored"
    assert outcome.result["score"] <= -30.0
    assert outcome.frame_count >= 30
    assert outcome.player_label == "minimal"


def test_step_driver_respects_max_frames(test_rom, mgba_core, tmp_path):
    bot_cmd = [sys.executable, str(FIXTURES / "minimal_bot.py")]

    sc_path = tmp_path / "never_done.py"
    sc_path.write_text("""\
from retrokix.scenario import Scenario
class NeverDone(Scenario):
    name = "never-done"
    rom_sha1 = "b6a631b57969143ddcb7b85553e1e1ea4448a631"
    decision_period = 1
    max_frames = 10
    def setup(self, ctl): pass
    def observe(self, ctl, frame): return {}
    def score(self, ctl, frame): return {"score": float(frame), "frame": frame}
    def done(self, ctl, frame): return False
""")
    from retrokix.scenario import load_scenario_file
    cls = load_scenario_file(sc_path, "NeverDone")

    driver = StepDriver(rom_path=test_rom, scenario_cls=cls, core_path=mgba_core)
    outcome = driver.run_match(bot_cmd, "minimal")
    assert outcome.reason == "timeout"
    assert outcome.frame_count == 10
