"""RealtimeDriver — 60fps wall-clock paced, deadline enforced."""

from __future__ import annotations

import sys
from pathlib import Path

import pytest

from retrokix.driver import MatchOutcome, RealtimeDriver
from retrokix.scenario import load_scenario_file


FIXTURES = Path(__file__).parent / "fixtures"


@pytest.fixture
def minimal_scenario_cls():
    return load_scenario_file(FIXTURES / "minimal_scenario.py", "MinimalScenario")


def test_realtime_minimal_match_completes(test_rom, mgba_core, minimal_scenario_cls):
    """A fast bot finishes a 30-frame scenario without lag misses."""
    bot_cmd = [sys.executable, str(FIXTURES / "minimal_bot.py")]
    driver = RealtimeDriver(
        rom_path=test_rom,
        scenario_cls=minimal_scenario_cls,
        core_path=mgba_core,
        lag_forfeit=60,
        slack_s=0.001,
    )
    outcome = driver.run_match(bot_cmd, "minimal")
    assert isinstance(outcome, MatchOutcome)
    assert outcome.reason == "scored"
    assert outcome.frame_count >= 30


def test_realtime_slow_bot_forfeits(test_rom, mgba_core, tmp_path):
    """A bot that sleeps longer than the deadline accumulates lag and forfeits."""
    slow_bot = tmp_path / "slow_bot.py"
    slow_bot.write_text("""\
import json, sys, time

def encode(msg):
    sys.stdout.write(json.dumps(msg) + "\\n")
    sys.stdout.flush()

sys.stdin.readline()
encode({"type": "ready", "name": "slow", "persistent": False})

while True:
    line = sys.stdin.readline()
    if not line:
        break
    msg = json.loads(line)
    if msg["type"] == "obs":
        time.sleep(0.05)
        encode({"type": "act", "buttons": []})
    elif msg["type"] == "done":
        break
""")

    sc_path = tmp_path / "long_scen.py"
    sc_path.write_text("""\
from retrokix.scenario import Scenario
class LongScen(Scenario):
    name = "long"
    rom_sha1 = "b6a631b57969143ddcb7b85553e1e1ea4448a631"
    decision_period = 1
    max_frames = 600
    def setup(self, ctl): pass
    def observe(self, ctl, frame): return {}
    def score(self, ctl, frame): return {"score": -float(frame), "frame": frame}
    def done(self, ctl, frame): return False
""")
    cls = load_scenario_file(sc_path, "LongScen")
    driver = RealtimeDriver(
        rom_path=test_rom,
        scenario_cls=cls,
        core_path=mgba_core,
        lag_forfeit=10,
        slack_s=0.001,
    )
    bot_cmd = [sys.executable, str(slow_bot)]
    outcome = driver.run_match(bot_cmd, "slow")
    assert outcome.reason == "forfeit"
    assert outcome.lag_misses >= 10
