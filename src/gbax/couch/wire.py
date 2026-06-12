"""Length-prefixed JSON framing for couch messages.

4-byte big-endian length header + UTF-8 JSON body. Same shape works
over Unix sockets and over WebSockets (modulo the framing layer the
WS handshake gives us for free). Keeping it primitive makes the
broker portable to non-Python implementations later if we want.
"""

from __future__ import annotations

import asyncio
import json
import struct
from typing import Any

_LEN_FMT = ">I"
_LEN_SIZE = 4
#: Hard cap on a single message body in bytes. Anything larger is
#: rejected before allocation — this is a friend-zone bus, not a
#: file transfer.
MAX_BODY_BYTES = 256 * 1024


async def read_frame(reader: asyncio.StreamReader) -> dict[str, Any]:
    """Read one length-prefixed JSON message from `reader`.

    Raises asyncio.IncompleteReadError when the peer disconnects.
    """
    header = await reader.readexactly(_LEN_SIZE)
    (length,) = struct.unpack(_LEN_FMT, header)
    if length > MAX_BODY_BYTES:
        raise ValueError(f"frame too large: {length} bytes (max {MAX_BODY_BYTES})")
    body = await reader.readexactly(length)
    return json.loads(body.decode("utf-8"))


async def write_frame(
    writer: asyncio.StreamWriter, payload: dict[str, Any]
) -> None:
    body = json.dumps(payload, separators=(",", ":")).encode("utf-8")
    if len(body) > MAX_BODY_BYTES:
        raise ValueError(f"frame too large: {len(body)} bytes (max {MAX_BODY_BYTES})")
    writer.write(struct.pack(_LEN_FMT, len(body)))
    writer.write(body)
    await writer.drain()
