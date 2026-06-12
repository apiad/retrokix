"""gbax couch — peer-to-peer plugin events over a tiny pub/sub bus.

A 'couch' is a set of gbax instances connected to one broker — locally
via a Unix socket (couch on the same machine) or eventually via a
WebSocket relay (couch across the internet). The wire is the same;
the plugin API is the same. Identity, rooms, mailbox, and the HTTP
relay come later.

This package ships the minimum: a dumb-fanout broker + a client with
client-side capability filtering, framed JSON messages, and async
glue. Enough to prove the round-trip and validate the ontology
abstraction before we wire it into the SDL play loop.
"""

from gbax.couch.session import Broker, Client, Event, PeerInfo
from gbax.couch.wire import read_frame, write_frame

__all__ = [
    "Broker",
    "Client",
    "Event",
    "PeerInfo",
    "read_frame",
    "write_frame",
]
