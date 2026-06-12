"""Smoke test for the couch bus.

Spins up an in-process broker over a tmp Unix socket, connects two
clients with different declared capabilities, and verifies:

1. Hello → peer_list bootstraps the peer directory on both sides.
2. peer_joined / peer_left land on the existing peer.
3. send(to=X, event, payload) round-trips and fires the receiver's
   handler with the right sender, event, and payload.
4. Capability filtering: a client without the event in `receives`
   does NOT see the event, even if the broker forwarded it.
5. Broadcast (to=None) reaches every subscribed peer except the sender.
"""

from __future__ import annotations

import asyncio
from pathlib import Path

import pytest

from gbax.couch import Broker, Client, Event


@pytest.fixture
def sock_path(tmp_path: Path) -> str:
    # Keep the path short — Linux caps Unix-socket paths at ~108 chars.
    return str(tmp_path / "couch.sock")


async def _wait_for(predicate, *, timeout: float = 2.0, step: float = 0.01) -> None:
    """Spin until predicate() returns truthy or we time out."""
    async def _loop() -> None:
        while not predicate():
            await asyncio.sleep(step)
    await asyncio.wait_for(_loop(), timeout=timeout)


# ---------- ----------

async def test_two_clients_can_round_trip_one_event(sock_path):
    broker = Broker()
    await broker.serve_unix(sock_path)

    alice = Client(
        peer_id="alice", name="Alice",
        emits=["couch.gift.consumable.tool"],
        receives=[],
    )
    bob = Client(
        peer_id="bob", name="Bob",
        emits=[],
        receives=["couch.gift.consumable.tool"],
    )

    received: list[Event] = []
    bob.on("couch.gift.consumable.tool", lambda _c, e: received.append(e))

    try:
        await alice.connect_unix(sock_path)
        await bob.connect_unix(sock_path)

        # Alice connected first — when bob joins, alice's peer list updates.
        await _wait_for(lambda: bob.peer("alice") is not None)
        await _wait_for(lambda: alice.peer("bob") is not None)

        await alice.send(
            to="bob",
            event="couch.gift.consumable.tool",
            payload={"tier": 3, "count": 1},
        )

        await _wait_for(lambda: len(received) == 1)
        assert received[0].sender == "alice"
        assert received[0].event == "couch.gift.consumable.tool"
        assert received[0].payload == {"tier": 3, "count": 1}
    finally:
        await alice.close()
        await bob.close()
        await broker.close()


async def test_capability_filter_drops_unsubscribed_events(sock_path):
    """Bob doesn't list the event in `receives`; the broker still
    forwards (dumb broker), but the client's filter drops it before
    any handler fires."""
    broker = Broker()
    await broker.serve_unix(sock_path)

    alice = Client(
        peer_id="alice", name="Alice",
        emits=["pokemon.battle.invite"],
        receives=[],
    )
    bob = Client(
        peer_id="bob", name="Bob",
        emits=[],
        receives=["couch.gift.consumable.tool"],  # not the battle invite
    )

    fired: list[Event] = []
    # Subscribe to the event Bob isn't listed as receiving — should still
    # be inert because the dispatch filter checks `receives`, not the
    # handler table.
    bob.on("pokemon.battle.invite", lambda _c, e: fired.append(e))

    try:
        await alice.connect_unix(sock_path)
        await bob.connect_unix(sock_path)
        await _wait_for(lambda: alice.peer("bob") is not None)

        await alice.send("bob", "pokemon.battle.invite", {"format": "doubles"})
        # Give the broker + reader loop time to actually forward + drop.
        await asyncio.sleep(0.1)
        assert fired == []
    finally:
        await alice.close()
        await bob.close()
        await broker.close()


async def test_broadcast_reaches_all_subscribed_peers_not_sender(sock_path):
    broker = Broker()
    await broker.serve_unix(sock_path)

    alice = Client(
        peer_id="alice", name="Alice",
        emits=["couch.presence.lead"],
        receives=["couch.presence.lead"],
    )
    bob = Client(
        peer_id="bob", name="Bob",
        emits=[],
        receives=["couch.presence.lead"],
    )
    carol = Client(
        peer_id="carol", name="Carol",
        emits=[],
        receives=[],  # opted out — should not receive
    )

    bob_got: list[Event] = []
    alice_got: list[Event] = []
    carol_got: list[Event] = []
    bob.on("couch.presence.lead", lambda _c, e: bob_got.append(e))
    alice.on("couch.presence.lead", lambda _c, e: alice_got.append(e))
    carol.on("couch.presence.lead", lambda _c, e: carol_got.append(e))

    try:
        await alice.connect_unix(sock_path)
        await bob.connect_unix(sock_path)
        await carol.connect_unix(sock_path)
        await _wait_for(lambda: len(alice.peers) == 2)
        await _wait_for(lambda: len(bob.peers) == 2)
        await _wait_for(lambda: len(carol.peers) == 2)

        await alice.send(None, "couch.presence.lead", {"name": "Combusken", "level": 12})

        await _wait_for(lambda: len(bob_got) == 1)
        await asyncio.sleep(0.05)
        # Bob received; Alice (sender) did NOT echo; Carol opted out.
        assert len(bob_got) == 1
        assert alice_got == []
        assert carol_got == []
        assert bob_got[0].payload == {"name": "Combusken", "level": 12}
    finally:
        await alice.close()
        await bob.close()
        await carol.close()
        await broker.close()


async def test_peer_joined_and_left_update_directory(sock_path):
    broker = Broker()
    await broker.serve_unix(sock_path)

    alice = Client(peer_id="alice", name="Alice")

    try:
        await alice.connect_unix(sock_path)
        assert alice.peers == []

        bob = Client(peer_id="bob", name="Bob")
        await bob.connect_unix(sock_path)
        await _wait_for(lambda: alice.peer("bob") is not None)
        assert alice.peer("bob").name == "Bob"

        await bob.close()
        await _wait_for(lambda: alice.peer("bob") is None)
    finally:
        await alice.close()
        await broker.close()


async def test_send_for_event_not_in_emits_raises(sock_path):
    broker = Broker()
    await broker.serve_unix(sock_path)

    alice = Client(
        peer_id="alice", name="Alice",
        emits=["couch.presence.lead"],
        receives=[],
    )

    try:
        await alice.connect_unix(sock_path)
        with pytest.raises(ValueError, match="not in this client's emits"):
            await alice.send("bob", "couch.gift.consumable.tool", {})
    finally:
        await alice.close()
        await broker.close()
