"""Thread-safe PCM byte distribution from libretro audio callbacks to
any number of WebSocket subscribers.

The libretro core fires `_on_audio(bytes)` on whichever thread is
currently stepping the runtime — the SDL main thread when SDL is
running, a daemon play-loop thread when --no-sdl is on. WebSocket
handlers live on the asyncio loop. Crossing that thread boundary is
the only thing this module does.

Design:
- Each subscriber gets its own bounded queue.Queue (thread-safe).
- Producer calls `publish(buf)` and walks the subscriber list under
  a lock; per-subscriber put_nowait drops the chunk if the consumer
  is slow.
- Consumers call `subscribe()` to get a queue and `await
  asyncio.to_thread(q.get, timeout=...)` to read. Unsubscribe in
  the WS handler's finally block.
"""

from __future__ import annotations

import queue
import threading


class AudioBus:
    """Many-producer many-consumer PCM byte fan-out."""

    def __init__(self, max_queue: int = 64) -> None:
        # ~64 chunks ≈ ~50–100 ms of buffered audio at our 32 kHz s16 stereo
        # rate (depends on libretro chunk size). Plenty of headroom for a
        # slow consumer to catch up; aggressive enough to bound memory.
        self._max_queue = max_queue
        self._subs: list[queue.Queue[bytes]] = []
        self._lock = threading.Lock()

    def subscribe(self) -> queue.Queue[bytes]:
        q: queue.Queue[bytes] = queue.Queue(maxsize=self._max_queue)
        with self._lock:
            self._subs.append(q)
        return q

    def unsubscribe(self, q: queue.Queue[bytes]) -> None:
        with self._lock:
            try:
                self._subs.remove(q)
            except ValueError:
                pass

    def publish(self, data: bytes) -> None:
        """Called from any thread. Each subscriber gets the chunk;
        slow subscribers silently drop, never block the producer."""
        if not data:
            return
        with self._lock:
            subs = list(self._subs)
        for q in subs:
            try:
                q.put_nowait(data)
            except queue.Full:
                pass

    @property
    def subscriber_count(self) -> int:
        with self._lock:
            return len(self._subs)
