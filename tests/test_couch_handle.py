"""Tests for the sync façade — same round-trip we tested async, but
driven from a non-async caller via CouchHandle / BrokerHandle."""

from __future__ import annotations

import threading
import time
from pathlib import Path

import pytest

from retrokix.couch.handle import BrokerHandle, CouchHandle


@pytest.fixture
def sock_path(tmp_path: Path) -> str:
    return str(tmp_path / "couch.sock")


def _wait(predicate, *, timeout: float = 3.0, step: float = 0.01) -> None:
    deadline = time.monotonic() + timeout
    while time.monotonic() < deadline:
        if predicate():
            return
        time.sleep(step)
    raise AssertionError("predicate never became true within timeout")


def test_broker_handle_serves_and_two_clients_round_trip(sock_path):
    """Boots a broker + two clients all via the sync wrappers, sends one
    event, asserts the handler ran with the right payload."""
    broker = BrokerHandle()
    broker.serve_unix(sock_path)

    alice = CouchHandle(
        peer_id="alice", name="Alice",
        emits=["couch.gift.consumable.tool"],
        receives=[],
    )
    bob = CouchHandle(
        peer_id="bob", name="Bob",
        emits=[],
        receives=["couch.gift.consumable.tool"],
    )

    received: list[dict] = []
    lock = threading.Lock()

    try:
        alice.connect_unix(sock_path)
        bob.connect_unix(sock_path)

        def _handler(_h, evt):
            with lock:
                received.append({"from": evt.sender, "event": evt.event, "payload": evt.payload})

        bob.on("couch.gift.consumable.tool", _handler)

        _wait(lambda: alice.peer("bob") is not None)
        _wait(lambda: bob.peer("alice") is not None)

        alice.send(to="bob", event="couch.gift.consumable.tool",
                   payload={"tier": 3, "count": 1})

        _wait(lambda: len(received) == 1)
        assert received[0] == {
            "from": "alice",
            "event": "couch.gift.consumable.tool",
            "payload": {"tier": 3, "count": 1},
        }
    finally:
        alice.close()
        bob.close()
        broker.close()


def test_handle_send_with_unauthorized_event_raises(sock_path):
    """Sync facade must propagate the underlying ValueError when the
    event isn't in `emits` — same contract as the async Client."""
    broker = BrokerHandle()
    broker.serve_unix(sock_path)
    alice = CouchHandle(
        peer_id="alice", name="Alice",
        emits=["couch.presence.lead"], receives=[],
    )
    try:
        alice.connect_unix(sock_path)
        with pytest.raises(ValueError, match="not in this client's emits"):
            alice.send(to=None, event="couch.gift.consumable.tool", payload={})
    finally:
        alice.close()
        broker.close()


def test_handle_connect_to_missing_socket_raises(tmp_path: Path):
    """No broker = clear failure mode, not a hang."""
    alice = CouchHandle(peer_id="alice", name="Alice", emits=[], receives=[])
    with pytest.raises(FileNotFoundError):
        alice.connect_unix(str(tmp_path / "nope.sock"))


def test_broker_handle_close_releases_socket(sock_path):
    """After close, another broker can bind the same path. This is what
    the CLI relies on across restarts."""
    b1 = BrokerHandle()
    b1.serve_unix(sock_path)
    b1.close()
    # Remove the dangling node — same as the CLI does before binding.
    Path(sock_path).unlink(missing_ok=True)
    b2 = BrokerHandle()
    b2.serve_unix(sock_path)
    b2.close()
