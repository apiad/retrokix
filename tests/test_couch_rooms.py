"""Verify rooms partition fan-out — a peer in room A neither sees nor
is seen by a peer in room B, even on the same broker socket."""

from __future__ import annotations

import asyncio
from pathlib import Path

import pytest

from retrokix.couch import Broker, Client


async def _wait_for(predicate, *, timeout: float = 2.0, step: float = 0.01) -> None:
    async def _loop() -> None:
        while not predicate():
            await asyncio.sleep(step)
    await asyncio.wait_for(_loop(), timeout=timeout)


@pytest.fixture
def sock_path(tmp_path: Path) -> str:
    return str(tmp_path / "couch.sock")


async def test_two_rooms_dont_see_each_other(sock_path):
    broker = Broker()
    await broker.serve_unix(sock_path)

    alice = Client(
        peer_id="alice", name="A", room="amber",
        emits=["couch.cheer"], receives=["couch.cheer"],
    )
    bob = Client(
        peer_id="bob", name="B", room="amber",
        emits=[], receives=["couch.cheer"],
    )
    cathy = Client(
        peer_id="cathy", name="C", room="cobalt",
        emits=[], receives=["couch.cheer"],
    )

    bob_got: list = []
    cathy_got: list = []
    bob.on("couch.cheer", lambda _c, e: bob_got.append(e))
    cathy.on("couch.cheer", lambda _c, e: cathy_got.append(e))

    try:
        await alice.connect_unix(sock_path)
        await bob.connect_unix(sock_path)
        await cathy.connect_unix(sock_path)

        # Alice + Bob see each other (same room); neither sees Cathy.
        await _wait_for(lambda: alice.peer("bob") is not None)
        assert alice.peer("cathy") is None
        assert bob.peer("cathy") is None
        assert cathy.peer("alice") is None

        await alice.send(None, "couch.cheer", {"kind": "clap"})
        await _wait_for(lambda: len(bob_got) == 1)
        await asyncio.sleep(0.05)
        assert len(bob_got) == 1
        assert cathy_got == []
    finally:
        await alice.close()
        await bob.close()
        await cathy.close()
        await broker.close()


async def test_targeted_send_across_rooms_is_dropped(sock_path):
    """Even with an explicit `to=peer_id`, a cross-room send doesn't
    deliver. Rooms aren't a soft filter; they're a hard boundary."""
    broker = Broker()
    await broker.serve_unix(sock_path)

    alice = Client(
        peer_id="alice", name="A", room="amber",
        emits=["couch.cheer"], receives=[],
    )
    cathy = Client(
        peer_id="cathy", name="C", room="cobalt",
        emits=[], receives=["couch.cheer"],
    )

    cathy_got: list = []
    cathy.on("couch.cheer", lambda _c, e: cathy_got.append(e))

    try:
        await alice.connect_unix(sock_path)
        await cathy.connect_unix(sock_path)

        # Neither peer is in the other's directory.
        await asyncio.sleep(0.05)
        assert alice.peer("cathy") is None
        assert cathy.peer("alice") is None

        # Cross-room targeted send — broker drops it.
        await alice.send("cathy", "couch.cheer", {"kind": "fire"})
        await asyncio.sleep(0.1)
        assert cathy_got == []
    finally:
        await alice.close()
        await cathy.close()
        await broker.close()


async def test_default_room_is_default_when_unspecified(sock_path):
    """Existing behavior: no room argument == 'default' room."""
    broker = Broker()
    await broker.serve_unix(sock_path)

    alice = Client(
        peer_id="alice", name="A",
        emits=["couch.cheer"], receives=[],
    )
    bob = Client(
        peer_id="bob", name="B",
        emits=[], receives=["couch.cheer"],
    )

    bob_got: list = []
    bob.on("couch.cheer", lambda _c, e: bob_got.append(e))

    try:
        await alice.connect_unix(sock_path)
        await bob.connect_unix(sock_path)
        assert alice.room == "default"
        assert bob.room == "default"
        await _wait_for(lambda: alice.peer("bob") is not None)
        await alice.send(None, "couch.cheer", {"kind": "clap"})
        await _wait_for(lambda: len(bob_got) == 1)
    finally:
        await alice.close()
        await bob.close()
        await broker.close()
