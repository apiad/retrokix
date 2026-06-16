"""AudioBus — multi-producer multi-consumer PCM byte fan-out tests."""

from __future__ import annotations

import queue
import threading

from retrokix.api.audio_bus import AudioBus


def test_subscribe_returns_independent_queues() -> None:
    bus = AudioBus()
    a = bus.subscribe()
    b = bus.subscribe()
    assert a is not b
    assert bus.subscriber_count == 2


def test_publish_fans_out_to_every_subscriber() -> None:
    bus = AudioBus()
    a = bus.subscribe()
    b = bus.subscribe()
    bus.publish(b"hello")
    assert a.get_nowait() == b"hello"
    assert b.get_nowait() == b"hello"


def test_unsubscribe_stops_delivery() -> None:
    bus = AudioBus()
    a = bus.subscribe()
    b = bus.subscribe()
    bus.unsubscribe(a)
    bus.publish(b"x")
    assert b.get_nowait() == b"x"
    with_a_was_empty = True
    try:
        a.get_nowait()
        with_a_was_empty = False
    except queue.Empty:
        pass
    assert with_a_was_empty


def test_publish_empty_is_noop() -> None:
    bus = AudioBus()
    a = bus.subscribe()
    bus.publish(b"")
    # Nothing delivered, queue stays empty.
    assert a.empty()


def test_slow_subscriber_drops_instead_of_blocking() -> None:
    """Subscriber queue is bounded; once full, publish() must drop the
    chunk rather than block the producer thread."""
    bus = AudioBus(max_queue=4)
    a = bus.subscribe()
    for _ in range(100):
        bus.publish(b"x")
    # Queue holds at most 4; never blocked the producer; no exception.
    drained = []
    while not a.empty():
        drained.append(a.get_nowait())
    assert len(drained) == 4


def test_publish_is_thread_safe() -> None:
    """Many concurrent producers + a consumer that drains in the main
    thread — no crash, all bytes accounted for."""
    bus = AudioBus(max_queue=10_000)
    sub = bus.subscribe()

    def _producer(label: bytes) -> None:
        for i in range(200):
            bus.publish(label + bytes([i & 0xFF]))

    threads = [
        threading.Thread(target=_producer, args=(bytes([i]),))
        for i in range(4)
    ]
    for t in threads:
        t.start()
    for t in threads:
        t.join()

    drained = []
    while not sub.empty():
        drained.append(sub.get_nowait())
    assert len(drained) == 4 * 200
