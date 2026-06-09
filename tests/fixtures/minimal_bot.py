"""Trivial bot used by tests: always returns ['a']."""

from gbax.player import run


def act(_obs):
    return ["a"]


if __name__ == "__main__":
    run(act, name="press-a")
