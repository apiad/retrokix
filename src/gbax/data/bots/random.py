"""Random-button baseline. Picks one of A/B/up/down/left/right each decision."""

import random as _r

from gbax.player import run


_BUTTONS = ["a", "b", "up", "down", "left", "right"]


def act(_obs):
    return [_r.choice(_BUTTONS)]


if __name__ == "__main__":
    run(act, name="random")
