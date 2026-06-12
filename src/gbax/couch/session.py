"""Broker + Client for the couch bus.

The broker is a dumb fanout: it forwards every event from every peer
to every other peer, attaching the sender's id. Capability filtering
runs on the **client** — receivers drop events they don't subscribe
to. Dumb-broker keeps the cross-peer schema decisions in plugin code,
which is the only place that has the typed knowledge anyway.

Protocol (length-prefixed JSON frames over a stream):

  client → broker (once at connect):
    {"type": "hello", "peer_id": str, "name": str,
     "emits": [str], "receives": [str]}

  broker → client (right after hello):
    {"type": "peer_list", "peers": [PeerInfo, …]}

  broker → client (whenever roster changes):
    {"type": "peer_joined", "peer": PeerInfo}
    {"type": "peer_left",   "peer_id": str}

  client → broker (whenever the plugin emits):
    {"type": "event",
     "event": str,                # e.g. "couch.gift.consumable.tool"
     "to": str | null,            # peer_id, or null for broadcast
     "payload": object}

  broker → client (forward):
    {"type": "event", "from": str, "event": str, "payload": object}

  PeerInfo = {"id": str, "name": str, "emits": [str], "receives": [str]}

That's it. No retries, no acks, no encryption. Smoke-test grade.
"""

from __future__ import annotations

import asyncio
from collections.abc import Awaitable, Callable
from dataclasses import dataclass, field
from typing import Any

from gbax.couch.wire import read_frame, write_frame


@dataclass
class PeerInfo:
    id: str
    name: str
    emits: list[str] = field(default_factory=list)
    receives: list[str] = field(default_factory=list)

    @classmethod
    def from_dict(cls, d: dict[str, Any]) -> "PeerInfo":
        return cls(
            id=d["id"],
            name=d.get("name", d["id"]),
            emits=list(d.get("emits", [])),
            receives=list(d.get("receives", [])),
        )

    def to_dict(self) -> dict[str, Any]:
        return {"id": self.id, "name": self.name, "emits": self.emits, "receives": self.receives}


@dataclass
class Event:
    sender: str
    event: str
    payload: dict[str, Any]


# Handler signature: (event, peer_id_of_sender, payload) → optional coroutine.
EventHandler = Callable[["Client", Event], Awaitable[None] | None]


# ---------------------------------------------------------------- Broker

class Broker:
    """Dumb fanout broker. One per couch (one Unix socket / WS relay)."""

    def __init__(self) -> None:
        self._peers: dict[str, tuple[PeerInfo, asyncio.StreamWriter]] = {}
        self._lock = asyncio.Lock()
        self.server: asyncio.base_events.Server | None = None

    async def serve_unix(self, path: str) -> asyncio.base_events.Server:
        self.server = await asyncio.start_unix_server(self._handle, path=path)
        return self.server

    async def close(self) -> None:
        if self.server is not None:
            self.server.close()
            await self.server.wait_closed()
        async with self._lock:
            for _info, w in self._peers.values():
                w.close()
            self._peers.clear()

    async def _handle(
        self, reader: asyncio.StreamReader, writer: asyncio.StreamWriter
    ) -> None:
        peer_id: str | None = None
        try:
            hello = await read_frame(reader)
            if hello.get("type") != "hello" or "peer_id" not in hello:
                writer.close()
                return
            info = PeerInfo(
                id=hello["peer_id"],
                name=hello.get("name", hello["peer_id"]),
                emits=list(hello.get("emits", [])),
                receives=list(hello.get("receives", [])),
            )
            peer_id = info.id

            async with self._lock:
                # Reject duplicate peer_id — only one connection per identity.
                if peer_id in self._peers:
                    await write_frame(writer, {"type": "error", "reason": "duplicate_peer_id"})
                    writer.close()
                    return
                existing = [p.to_dict() for p, _ in self._peers.values()]
                self._peers[peer_id] = (info, writer)
                others = [w for pid, (_, w) in self._peers.items() if pid != peer_id]

            await write_frame(writer, {"type": "peer_list", "peers": existing})
            for w in others:
                await write_frame(w, {"type": "peer_joined", "peer": info.to_dict()})

            while True:
                msg = await read_frame(reader)
                if msg.get("type") != "event":
                    continue
                await self._fanout(peer_id, msg)

        except (asyncio.IncompleteReadError, ConnectionResetError, ValueError):
            pass
        finally:
            if peer_id is not None:
                async with self._lock:
                    self._peers.pop(peer_id, None)
                    remaining = list(self._peers.values())
                for _info, w in remaining:
                    try:
                        await write_frame(w, {"type": "peer_left", "peer_id": peer_id})
                    except (ConnectionResetError, BrokenPipeError):
                        pass
            try:
                writer.close()
            except Exception:
                pass

    async def _fanout(self, sender_id: str, msg: dict[str, Any]) -> None:
        forward = {
            "type": "event",
            "from": sender_id,
            "event": msg.get("event"),
            "payload": msg.get("payload", {}),
        }
        target = msg.get("to")
        async with self._lock:
            if target is None:
                writers = [w for pid, (_, w) in self._peers.items() if pid != sender_id]
            else:
                entry = self._peers.get(target)
                writers = [entry[1]] if entry else []
        for w in writers:
            try:
                await write_frame(w, forward)
            except (ConnectionResetError, BrokenPipeError):
                pass


# ---------------------------------------------------------------- Client

class Client:
    """One gbax instance's view of the couch. Owns the socket, the
    handler table, and the per-peer directory the plugin queries
    via `peers` / `peer(id)`."""

    def __init__(
        self,
        peer_id: str,
        name: str,
        emits: list[str] | None = None,
        receives: list[str] | None = None,
    ) -> None:
        self.peer_id = peer_id
        self.name = name
        self.emits = list(emits or [])
        self.receives = list(receives or [])

        self._reader: asyncio.StreamReader | None = None
        self._writer: asyncio.StreamWriter | None = None
        self._reader_task: asyncio.Task | None = None
        self._handlers: dict[str, list[EventHandler]] = {}
        self._peers: dict[str, PeerInfo] = {}
        self.connected = asyncio.Event()

    # ----- lifecycle -----

    async def connect_unix(self, path: str) -> None:
        self._reader, self._writer = await asyncio.open_unix_connection(path=path)
        await write_frame(self._writer, {
            "type": "hello",
            "peer_id": self.peer_id,
            "name": self.name,
            "emits": self.emits,
            "receives": self.receives,
        })
        self._reader_task = asyncio.create_task(self._read_loop())
        # Wait for the initial peer_list to land so callers can rely on
        # self.peers being populated before they start sending.
        await self.connected.wait()

    async def close(self) -> None:
        if self._reader_task is not None:
            self._reader_task.cancel()
            try:
                await self._reader_task
            except (asyncio.CancelledError, Exception):
                pass
        if self._writer is not None:
            try:
                self._writer.close()
                await self._writer.wait_closed()
            except Exception:
                pass

    # ----- public API the plugin uses -----

    def on(self, event: str, handler: EventHandler) -> None:
        """Subscribe to a specific event type. Handlers fire in the
        order they were registered. Client-side filtering: events not
        in `receives` are dropped before reaching any handler."""
        self._handlers.setdefault(event, []).append(handler)

    @property
    def peers(self) -> list[PeerInfo]:
        return list(self._peers.values())

    def peer(self, peer_id: str) -> PeerInfo | None:
        return self._peers.get(peer_id)

    async def send(
        self, to: str | None, event: str, payload: dict[str, Any]
    ) -> None:
        """Emit an event. `to=None` broadcasts to every connected peer
        whose `receives` includes the event type (filtered receive-side
        by the recipient, not the broker)."""
        if event not in self.emits:
            raise ValueError(f"can't send {event!r}: not in this client's emits")
        if self._writer is None:
            raise RuntimeError("not connected")
        await write_frame(self._writer, {
            "type": "event",
            "to": to,
            "event": event,
            "payload": payload,
        })

    # ----- internal -----

    async def _read_loop(self) -> None:
        assert self._reader is not None
        try:
            while True:
                msg = await read_frame(self._reader)
                t = msg.get("type")
                if t == "peer_list":
                    self._peers = {
                        p["id"]: PeerInfo.from_dict(p) for p in msg.get("peers", [])
                    }
                    self.connected.set()
                elif t == "peer_joined":
                    p = PeerInfo.from_dict(msg["peer"])
                    self._peers[p.id] = p
                elif t == "peer_left":
                    self._peers.pop(msg["peer_id"], None)
                elif t == "event":
                    await self._dispatch(msg)
        except (asyncio.IncompleteReadError, ConnectionResetError):
            pass

    async def _dispatch(self, msg: dict[str, Any]) -> None:
        event = msg.get("event", "")
        # Client-side capability filter: silently drop unsubscribed events.
        if event not in self.receives:
            return
        evt = Event(
            sender=msg.get("from", ""),
            event=event,
            payload=msg.get("payload") or {},
        )
        for h in self._handlers.get(event, ()):
            res = h(self, evt)
            if asyncio.iscoroutine(res):
                await res
