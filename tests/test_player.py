"""Tests for the player-side protocol helpers."""

from __future__ import annotations

import io
import json

import pytest

from gbax.player import (
    HELLO,
    OBS,
    READY,
    ACT,
    DONE,
    SCHEMA_VERSION,
    encode_message,
    iter_messages,
)


def test_encode_round_trip_newline_terminated():
    raw = encode_message({"type": HELLO, "scenario": "x", "decision_period": 1, "schema_version": 1})
    assert raw.endswith(b"\n")
    assert json.loads(raw) == {
        "type": HELLO, "scenario": "x", "decision_period": 1, "schema_version": 1,
    }


def test_iter_messages_splits_on_newlines():
    buf = io.BytesIO(b'{"type":"obs","frame":0,"data":{}}\n{"type":"obs","frame":1,"data":{}}\n')
    messages = list(iter_messages(buf))
    assert [m["frame"] for m in messages] == [0, 1]


def test_iter_messages_skips_blank_lines():
    buf = io.BytesIO(b'{"type":"ready","name":"a"}\n\n{"type":"act","buttons":[]}\n')
    messages = list(iter_messages(buf))
    assert [m["type"] for m in messages] == [READY, ACT]


def test_iter_messages_invalid_json_raises():
    buf = io.BytesIO(b"not json\n")
    with pytest.raises(ValueError):
        list(iter_messages(buf))


def test_schema_version_is_one():
    assert SCHEMA_VERSION == 1


import subprocess
import sys
from pathlib import Path


FIXTURES = Path(__file__).parent / "fixtures"


def test_run_handles_hello_and_one_decision():
    bot = FIXTURES / "minimal_bot.py"
    proc = subprocess.Popen(
        [sys.executable, str(bot)],
        stdin=subprocess.PIPE,
        stdout=subprocess.PIPE,
        stderr=subprocess.PIPE,
    )

    proc.stdin.write(encode_message({
        "type": HELLO, "scenario": "x", "decision_period": 1, "schema_version": 1,
    }))
    proc.stdin.flush()

    msgs = iter_messages(proc.stdout)
    ready = next(msgs)
    assert ready["type"] == "ready"
    assert ready["name"] == "press-a"

    proc.stdin.write(encode_message({"type": OBS, "frame": 0, "data": {}}))
    proc.stdin.flush()
    act = next(msgs)
    assert act == {"type": "act", "buttons": ["a"]}

    proc.stdin.write(encode_message({
        "type": DONE, "result": {"score": 0.0}, "reason": "scored",
    }))
    proc.stdin.close()
    proc.wait(timeout=5)
    assert proc.returncode == 0
