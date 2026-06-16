"""Subprocess player protocol — wire format + helpers + run() entry point.

The protocol is newline-delimited JSON over stdin/stdout:

  retrokix → player   HELLO  {"type":"hello", "scenario":..., "decision_period":..., "schema_version":1}
  player → retrokix   READY  {"type":"ready", "name":"...", "persistent":false}

  retrokix → player   OBS    {"type":"obs", "frame":N, "data":{...}}
  player → retrokix   ACT    {"type":"act", "buttons":["a","right"]}
  (loop)

  retrokix → player   DONE   {"type":"done", "result":{...}, "reason":"scored"|"timeout"|"forfeit"|"crashed"}

stderr is forwarded by the driver to the user's terminal for debugging.
"""

from __future__ import annotations

import json
import sys
from collections.abc import Callable, Iterator
from typing import IO


SCHEMA_VERSION = 1

HELLO = "hello"
READY = "ready"
OBS = "obs"
ACT = "act"
DONE = "done"


def encode_message(payload: dict) -> bytes:
    """JSON-encode a payload, ensuring a trailing newline."""
    return (json.dumps(payload, separators=(",", ":")) + "\n").encode("utf-8")


def iter_messages(stream: IO[bytes]) -> Iterator[dict]:
    """Yield one decoded message per non-blank line from `stream`."""
    for raw in stream:
        line = raw.strip()
        if not line:
            continue
        try:
            yield json.loads(line.decode("utf-8"))
        except json.JSONDecodeError as exc:
            raise ValueError(f"invalid JSON message: {exc}") from exc


def run(
    act: Callable[[dict], list[str]],
    *,
    name: str = "anonymous",
    persistent: bool = False,
    stdin: IO[bytes] | None = None,
    stdout: IO[bytes] | None = None,
) -> None:
    """Simple synchronous player loop.

    `act(observation_data) -> list[str]` is called for every OBS message.
    The return value is sent back as an ACT message.

    persistent=True keeps the loop alive after DONE, waiting for the next
    HELLO. Tournament drivers ignore this flag and always SIGTERM at DONE.
    """
    stdin = stdin if stdin is not None else sys.stdin.buffer
    stdout = stdout if stdout is not None else sys.stdout.buffer

    while True:
        try:
            hello = next(iter_messages(stdin))
        except StopIteration:
            return
        if hello.get("type") != HELLO:
            raise RuntimeError(f"expected HELLO first, got {hello!r}")

        stdout.write(encode_message({
            "type": READY,
            "name": name,
            "persistent": bool(persistent),
        }))
        stdout.flush()

        for msg in iter_messages(stdin):
            t = msg.get("type")
            if t == OBS:
                buttons = act(msg.get("data", {}))
                stdout.write(encode_message({"type": ACT, "buttons": list(buttons)}))
                stdout.flush()
            elif t == DONE:
                break
            else:
                raise RuntimeError(f"unexpected message in decision loop: {msg!r}")

        if not persistent:
            return
