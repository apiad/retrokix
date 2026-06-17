"""QosState — adaptive JPEG quality + send-duration tracking.

Pure state machine; no asyncio or websockets involved. The stream WS
loop drives it with:
  qos.record_send(send_dur_sec, interval_sec)   # after each successful send
  qos.record_drop()                             # when we skip a frame
"""

from __future__ import annotations

from retrokix.api.qos import QosState


def test_starts_at_initial_quality_clamped_to_ceiling():
    q = QosState(initial_quality=92, quality_floor=30, quality_ceiling=80)
    assert q.quality == 80
    assert q.floor == 30
    assert q.ceiling == 80


def test_floor_above_ceiling_is_collapsed():
    """Defensive: if caller passes nonsense, prefer the ceiling."""
    q = QosState(initial_quality=70, quality_floor=90, quality_ceiling=80)
    assert q.floor == 80
    assert q.ceiling == 80
    assert q.quality == 80


def test_steady_fast_sends_keep_quality_at_ceiling():
    q = QosState(initial_quality=92, quality_floor=30, quality_ceiling=92)
    # Sends take 5% of the interval — well under the recover threshold
    for _ in range(20):
        q.record_send(send_seconds=0.005, interval_seconds=1.0 / 30)
    assert q.quality == 92


def test_slow_sends_ratchet_quality_down_to_floor():
    q = QosState(
        initial_quality=92,
        quality_floor=30,
        quality_ceiling=92,
        step=5,
    )
    # 95% of interval consumed by send — well over the drop threshold
    interval = 1.0 / 30
    for _ in range(100):
        q.record_send(send_seconds=interval * 0.95, interval_seconds=interval)
    assert q.quality == 30


def test_recovery_after_link_clears():
    q = QosState(
        initial_quality=92,
        quality_floor=30,
        quality_ceiling=92,
        step=5,
    )
    interval = 1.0 / 30
    # First: hammer it down to the floor
    for _ in range(100):
        q.record_send(send_seconds=interval * 0.95, interval_seconds=interval)
    assert q.quality == 30
    # Then: link clears, sends become fast — quality climbs back up
    for _ in range(100):
        q.record_send(send_seconds=interval * 0.05, interval_seconds=interval)
    assert q.quality == 92


def test_quality_never_exceeds_ceiling_or_drops_below_floor():
    q = QosState(initial_quality=70, quality_floor=40, quality_ceiling=80)
    for _ in range(50):
        q.record_send(send_seconds=0.001, interval_seconds=1.0 / 30)
    assert q.quality == 80  # not above ceiling
    for _ in range(200):
        q.record_send(send_seconds=1.0, interval_seconds=1.0 / 30)
    assert q.quality == 40  # not below floor


def test_record_drop_increments_counter():
    q = QosState(initial_quality=80)
    q.record_drop()
    q.record_drop()
    assert q.dropped == 2
    assert q.sent == 0


def test_record_send_increments_sent():
    q = QosState(initial_quality=80)
    q.record_send(0.001, 1.0 / 30)
    q.record_send(0.001, 1.0 / 30)
    assert q.sent == 2


def test_snapshot_shape():
    q = QosState(initial_quality=80, quality_floor=80, quality_ceiling=80)
    q.record_send(send_seconds=0.01, interval_seconds=1.0 / 30)
    q.record_drop()
    snap = q.snapshot()
    assert snap["sent"] == 1
    assert snap["dropped"] == 1
    assert snap["quality"] == 80  # pinned because floor==ceiling
    assert "ratio_ewma" in snap
    assert "last_send_ms" in snap


def test_no_adaptation_when_floor_equals_ceiling():
    """No room to move — quality is pinned."""
    q = QosState(initial_quality=70, quality_floor=70, quality_ceiling=70)
    interval = 1.0 / 30
    for _ in range(100):
        q.record_send(send_seconds=interval * 0.95, interval_seconds=interval)
    assert q.quality == 70


def test_zero_interval_does_not_divide_by_zero():
    """Guard against degenerate intervals (shouldn't happen but stay safe)."""
    q = QosState(initial_quality=80)
    q.record_send(send_seconds=0.01, interval_seconds=0.0)
    # Should not raise; ratio_ewma reflects the high value
    assert q.ratio_ewma > 0
