"""Minimal scenario used by the test suite. No real ROM memory dependency:
score is just -frame_count, done is frame >= 30."""

from gbax.scenario import Scenario


class MinimalScenario(Scenario):
    name = "minimal"
    rom_sha1 = "b6a631b57969143ddcb7b85553e1e1ea4448a631"
    decision_period = 1
    max_frames = 60

    def setup(self, ctl) -> None:
        return None

    def observe(self, ctl, frame: int) -> dict:
        return {"frame": frame}

    def score(self, ctl, frame: int) -> dict:
        return {"score": float(-frame), "frame": frame}

    def done(self, ctl, frame: int) -> bool:
        return frame >= 30
