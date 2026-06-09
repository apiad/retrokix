"""Tests for the Scenario ABC, loader, and validator."""

from __future__ import annotations

from pathlib import Path

import pytest

from gbax.scenario import (
    Scenario,
    ScenarioValidationError,
    instantiate_scenario,
    load_scenario_file,
)


FIXTURES = Path(__file__).parent / "fixtures"


def test_abstract_scenario_cannot_instantiate():
    with pytest.raises(TypeError):
        Scenario()


def test_minimal_scenario_loads():
    cls = load_scenario_file(FIXTURES / "minimal_scenario.py", "MinimalScenario")
    sc = instantiate_scenario(cls)
    assert sc.name == "minimal"
    assert sc.decision_period == 1
    assert sc.max_frames == 60


def test_class_missing_required_field_rejected(tmp_path):
    bad = tmp_path / "bad.py"
    bad.write_text("""\
from gbax.scenario import Scenario
class BadScenario(Scenario):
    name = "bad"
    decision_period = 1
    max_frames = 60
    # rom_sha1 missing
    def setup(self, ctl): pass
    def observe(self, ctl, frame): return {}
    def score(self, ctl, frame): return {"score": 0.0}
    def done(self, ctl, frame): return False
""")
    with pytest.raises(ScenarioValidationError, match="rom_sha1"):
        cls = load_scenario_file(bad, "BadScenario")
        instantiate_scenario(cls)


def test_registry_finds_bundled_scenarios(monkeypatch, tmp_path):
    monkeypatch.setenv("HOME", str(tmp_path))
    from gbax.scenario import list_installed_scenarios

    found = list_installed_scenarios()
    assert isinstance(found, list)


def test_registry_includes_user_scenarios(monkeypatch, tmp_path):
    monkeypatch.setenv("HOME", str(tmp_path))
    user_dir = tmp_path / ".gbax" / "scenarios"
    user_dir.mkdir(parents=True)
    (user_dir / "my_scen.py").write_text("""\
from gbax.scenario import Scenario
class MyScen(Scenario):
    name = "my-scen"
    rom_sha1 = "0" * 40
    decision_period = 1
    max_frames = 60
    def setup(self, ctl): pass
    def observe(self, ctl, frame): return {}
    def score(self, ctl, frame): return {"score": 0.0}
    def done(self, ctl, frame): return False
""")
    from gbax.scenario import list_installed_scenarios, resolve_scenario

    found = list_installed_scenarios()
    assert any(entry["name"] == "my-scen" for entry in found)

    cls = resolve_scenario("my-scen")
    assert cls.name == "my-scen"


def test_resolve_unknown_scenario(monkeypatch, tmp_path):
    monkeypatch.setenv("HOME", str(tmp_path))
    from gbax.scenario import resolve_scenario

    with pytest.raises(ScenarioValidationError, match="no scenario"):
        resolve_scenario("does-not-exist")
