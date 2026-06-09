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
