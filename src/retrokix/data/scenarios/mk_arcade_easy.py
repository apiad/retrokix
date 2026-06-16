"""Mortal Kombat Advance — 1-player arcade ladder reference scenario.

Score = p1_hp - p2_hp + (round_won ? 1000 : 0). Higher is better.
Match ends when one fighter's HP hits zero or frames run out.

Memory addresses derived from the libretro cheat database — CodeBreaker
"1-Hit Death" codes 32000020 (P1) and 32000088 (P2) reveal the HP locations
in EWRAM. Max HP is 0x28 (40) per round.

ROM: Mortal Kombat Advance (USA), sha1 461b6400eade2eeeeb1faabb3724d8b27c84361d.
"""

from retrokix.scenario import Scenario
from retrokix.controller import Controller


ADDR_P1_HP = 0x02000020
ADDR_P2_HP = 0x02000088
MAX_HP = 0x28


class MKArcadeEasy(Scenario):
    name = "mk-arcade-easy"
    rom_sha1 = "461b6400eade2eeeeb1faabb3724d8b27c84361d"
    decision_period = 1
    max_frames = 60 * 60 * 2  # 2 minutes

    def __init__(self) -> None:
        self._fight_started = False

    def setup(self, ctl: Controller) -> None:
        ctl.wait(180)
        ctl.press(["start"], frames=2)
        ctl.wait(60)
        ctl.press(["a"], frames=2)
        ctl.wait(60)
        ctl.press(["a"], frames=2)
        ctl.wait(120)

    def observe(self, ctl: Controller, frame: int) -> dict:
        return {
            "p1_hp": ctl.read_u8(ADDR_P1_HP),
            "p2_hp": ctl.read_u8(ADDR_P2_HP),
            "frame": frame,
        }

    def score(self, ctl: Controller, frame: int) -> dict:
        p1 = ctl.read_u8(ADDR_P1_HP)
        p2 = ctl.read_u8(ADDR_P2_HP)
        round_won = p2 == 0 and p1 > 0
        return {
            "score": float(p1 - p2 + (1000 if round_won else 0)),
            "p1_hp": p1,
            "p2_hp": p2,
            "round_won": round_won,
            "frame": frame,
        }

    def done(self, ctl: Controller, frame: int) -> bool:
        p1 = ctl.read_u8(ADDR_P1_HP)
        p2 = ctl.read_u8(ADDR_P2_HP)
        if not self._fight_started:
            if p1 > 0 and p2 > 0:
                self._fight_started = True
            return False
        return p1 == 0 or p2 == 0
