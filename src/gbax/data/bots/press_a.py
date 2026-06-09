"""Baseline that holds A. Useful as a sanity check / "everyone should beat this"."""

from gbax.player import run


def act(_obs):
    return ["a"]


if __name__ == "__main__":
    run(act, name="press-a")
