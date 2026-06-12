"""Sync-facing wrapper around the async Broker / Client.

The gbax play loop is synchronous (one big `while SDL_PollEvent` loop
on the main thread), but the couch transport is asyncio. Bridging them
the obvious way — running asyncio on a background thread, talking to
it via `asyncio.run_coroutine_threadsafe` — keeps both sides clean.

CouchHandle wraps a Client + its private asyncio loop in a background
thread. Plugin code calls `handle.send(...)` and `handle.on(...)` from
the SDL thread; the handle does the threadsafe scheduling.

BrokerHandle is the same pattern around Broker — used by
`gbax couch broker` to run the broker until SIGINT without exposing
an asyncio surface to the caller.

Handler invocation: registered handlers run on the asyncio thread, NOT
the SDL thread. That's intentional — plugin code that needs to do real
work (e.g. write to the runtime) should bounce back to the main thread
via a queue. For the early demo plugin we'll just enqueue an action and
process it in the next play-loop tick.
"""

from __future__ import annotations

import asyncio
import os
import socket
import threading
from collections.abc import Callable
from pathlib import Path
from typing import Any

from gbax.couch.session import Broker, Client, Event, PeerInfo


DEFAULT_SOCK = Path.home() / ".gbax" / "couch" / "default.sock"


def is_broker_alive(sock_path: str | Path) -> bool:
    """True iff a Unix socket at `sock_path` accepts a connection right now."""
    p = str(sock_path)
    s = socket.socket(socket.AF_UNIX, socket.SOCK_STREAM)
    s.settimeout(0.25)
    try:
        s.connect(p)
        s.close()
        return True
    except (FileNotFoundError, ConnectionRefusedError, OSError):
        try:
            s.close()
        except Exception:
            pass
        return False


def ensure_local_broker(sock_path: str | Path = DEFAULT_SOCK) -> "BrokerHandle | None":
    """If no broker is alive at `sock_path`, spawn one in-process and
    return its handle (caller must close on shutdown). If an external
    broker is already serving the socket, return None — caller just
    connects to it."""
    p = Path(sock_path)
    if is_broker_alive(p):
        return None
    p.parent.mkdir(parents=True, exist_ok=True)
    # Clean up a stale socket file if the previous broker died ungracefully.
    if p.exists() and p.is_socket():
        try:
            os.unlink(p)
        except OSError:
            pass
    handle = BrokerHandle()
    handle.serve_unix(str(p))
    return handle


class CouchHandle:
    """Sync façade around an asyncio Client + its background loop."""

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
        self._loop: asyncio.AbstractEventLoop | None = None
        self._thread: threading.Thread | None = None
        self._client: Client | None = None
        self._ready = threading.Event()

    # ----- lifecycle ------------------------------------------------

    def connect_unix(self, sock_path: str, timeout: float = 5.0) -> None:
        """Spin up the loop thread, connect the client, wait for the
        initial peer_list to land. Blocks until connected or raises."""
        if self._thread is not None:
            raise RuntimeError("already connected")

        connect_err: list[BaseException] = []

        def _run() -> None:
            self._loop = asyncio.new_event_loop()
            asyncio.set_event_loop(self._loop)
            self._client = Client(
                peer_id=self.peer_id,
                name=self.name,
                emits=self.emits,
                receives=self.receives,
            )
            try:
                self._loop.run_until_complete(self._client.connect_unix(sock_path))
            except BaseException as exc:
                connect_err.append(exc)
                self._ready.set()
                self._loop.close()
                return
            self._ready.set()
            self._loop.run_forever()

        self._thread = threading.Thread(target=_run, name="couch-loop", daemon=True)
        self._thread.start()

        if not self._ready.wait(timeout=timeout):
            raise TimeoutError(f"couch: connect to {sock_path!r} timed out")
        if connect_err:
            self._thread = None
            raise connect_err[0]

    def close(self, timeout: float = 2.0) -> None:
        if self._loop is None or self._client is None:
            return
        loop, client = self._loop, self._client

        async def _shutdown() -> None:
            await client.close()
            loop.stop()

        try:
            asyncio.run_coroutine_threadsafe(_shutdown(), loop).result(timeout=timeout)
        except (TimeoutError, asyncio.TimeoutError, RuntimeError):
            pass
        if self._thread is not None:
            self._thread.join(timeout=timeout)
        self._thread = None
        self._loop = None
        self._client = None

    # ----- plugin-facing API ---------------------------------------

    def on(
        self, event: str, handler: Callable[["CouchHandle", Event], None]
    ) -> None:
        """Subscribe a sync handler. Handler runs on the asyncio thread."""
        if self._client is None:
            raise RuntimeError("not connected")

        def _wrap(_client: Client, evt: Event) -> None:
            handler(self, evt)
        self._client.on(event, _wrap)

    def send(self, to: str | None, event: str, payload: dict[str, Any]) -> None:
        """Schedule a send onto the asyncio loop and wait briefly for it."""
        if self._loop is None or self._client is None:
            raise RuntimeError("not connected")
        fut = asyncio.run_coroutine_threadsafe(
            self._client.send(to, event, payload), self._loop,
        )
        fut.result(timeout=2.0)

    def peers(self) -> list[PeerInfo]:
        if self._client is None:
            return []
        return self._client.peers

    def peer(self, peer_id: str) -> PeerInfo | None:
        if self._client is None:
            return None
        return self._client.peer(peer_id)


class BrokerHandle:
    """Run a Broker on a background asyncio loop. Used by
    `gbax couch broker` and by the auto-spawn helper."""

    def __init__(self) -> None:
        self._loop: asyncio.AbstractEventLoop | None = None
        self._thread: threading.Thread | None = None
        self._broker: Broker | None = None
        self._ready = threading.Event()

    def serve_unix(self, sock_path: str, timeout: float = 5.0) -> None:
        bind_err: list[BaseException] = []

        def _run() -> None:
            self._loop = asyncio.new_event_loop()
            asyncio.set_event_loop(self._loop)
            self._broker = Broker()
            try:
                self._loop.run_until_complete(self._broker.serve_unix(sock_path))
            except BaseException as exc:
                bind_err.append(exc)
                self._ready.set()
                self._loop.close()
                return
            self._ready.set()
            self._loop.run_forever()

        self._thread = threading.Thread(target=_run, name="couch-broker", daemon=True)
        self._thread.start()
        if not self._ready.wait(timeout=timeout):
            raise TimeoutError("couch broker bind timed out")
        if bind_err:
            self._thread = None
            raise bind_err[0]

    def close(self, timeout: float = 2.0) -> None:
        if self._loop is None or self._broker is None:
            return
        loop, broker = self._loop, self._broker

        async def _shutdown() -> None:
            await broker.close()
            loop.stop()

        try:
            asyncio.run_coroutine_threadsafe(_shutdown(), loop).result(timeout=timeout)
        except (TimeoutError, asyncio.TimeoutError, RuntimeError):
            pass
        if self._thread is not None:
            self._thread.join(timeout=timeout)
        self._thread = None
        self._loop = None
        self._broker = None
