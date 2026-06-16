"""Super Mario Advance 4 (SMB3) — World 1-1 reference scenario.

Score = in_game_score - frame_penalty. Lives at zero ends the match.

Memory addresses derived from the libretro cheat database:
- Mario Lives at 0x02002A6A (byte) — CodeBreaker "Infinite Lives" 33002A6A
- In-game score: 0x02003854..0x02003856 — CodeBreaker "Have Maximum Score"
  83003854+423F+33003856+000F. Stored as 3 little-endian bytes (BCD-ish).

The cheat DB does not expose level-completion or x-position markers for
SMB3 GBA, so this scenario rewards in-game score and penalizes time spent.
A real World 1-1 completion bonus would need additional RE work.

ROM: Super Mario Advance 4 (USA, Rev 1), sha1 82fa5a6cf09415c2e262931488841b78a524e2c3.
"""

from retrokix.scenario import Scenario
from retrokix.controller import Controller


ADDR_MARIO_LIVES = 0x02002A6A
ADDR_SCORE_LO = 0x02003854


class SMB3World1_1(Scenario):
    name = "smb3-world-1-1"
    rom_sha1 = "82fa5a6cf09415c2e262931488841b78a524e2c3"
    decision_period = 2
    max_frames = 60 * 60 * 3  # 3 minutes

    def __init__(self) -> None:
        self._game_started = False

    def setup(self, ctl: Controller) -> None:
        ctl.wait(240)
        ctl.press(["start"], frames=2)
        ctl.wait(60)
        ctl.press(["start"], frames=2)
        ctl.wait(60)
        ctl.press(["a"], frames=2)
        ctl.wait(120)
        ctl.press(["a"], frames=2)
        ctl.wait(120)

    def _score_raw(self, ctl: Controller) -> int:
        lo = ctl.read_u8(ADDR_SCORE_LO)
        mid = ctl.read_u8(ADDR_SCORE_LO + 1)
        hi = ctl.read_u8(ADDR_SCORE_LO + 2)
        return lo | (mid << 8) | (hi << 16)

    def observe(self, ctl: Controller, frame: int) -> dict:
        return {
            "lives": ctl.read_u8(ADDR_MARIO_LIVES),
            "game_score": self._score_raw(ctl),
            "frame": frame,
        }

    def score(self, ctl: Controller, frame: int) -> dict:
        lives = ctl.read_u8(ADDR_MARIO_LIVES)
        game_score = self._score_raw(ctl)
        return {
            "score": float(game_score - frame * 0.1),
            "lives": lives,
            "game_score": game_score,
            "frame": frame,
        }

    def done(self, ctl: Controller, frame: int) -> bool:
        lives = ctl.read_u8(ADDR_MARIO_LIVES)
        if not self._game_started:
            if lives > 0:
                self._game_started = True
            return False
        return lives == 0
