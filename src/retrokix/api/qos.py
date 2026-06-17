"""QosState — adaptive JPEG quality for the /stream WebSocket loop.

Tracks an EWMA of `send_duration / target_interval`. When that ratio
runs high, we're spending most of the frame interval pushing bytes
through the WS — drop quality. When it runs low, we have headroom —
claw quality back up toward the user-configured ceiling.

This module is pure state — no asyncio, no I/O. The send loop drives
it. Tested in isolation in test_api_qos.py.
"""

from __future__ import annotations

# When the EWMA ratio crosses these thresholds, step the JPEG quality
# down or up by `step` units (clamped to [floor, ceiling]).
DEFAULT_DROP_THRESHOLD = 0.8
DEFAULT_RECOVER_THRESHOLD = 0.4
DEFAULT_ALPHA = 0.2
DEFAULT_STEP = 5

# Absolute JPEG quality bounds — the configured floor/ceiling are
# clamped to this. Anything below ~25 is visibly mush, anything above
# 95 isn't perceptibly better and bloats payload.
QUALITY_HARD_MIN = 10
QUALITY_HARD_MAX = 95


class QosState:
    """Single-WS QoS bookkeeping. Not thread-safe (lives inside a
    single asyncio task)."""

    def __init__(
        self,
        *,
        initial_quality: int,
        quality_floor: int = 30,
        quality_ceiling: int | None = None,
        alpha: float = DEFAULT_ALPHA,
        drop_threshold: float = DEFAULT_DROP_THRESHOLD,
        recover_threshold: float = DEFAULT_RECOVER_THRESHOLD,
        step: int = DEFAULT_STEP,
    ) -> None:
        if quality_ceiling is None:
            quality_ceiling = initial_quality
        floor = max(QUALITY_HARD_MIN, min(quality_floor, QUALITY_HARD_MAX))
        ceiling = max(QUALITY_HARD_MIN, min(quality_ceiling, QUALITY_HARD_MAX))
        if floor > ceiling:
            # Defensive: collapse onto the ceiling rather than reject.
            floor = ceiling
        self.floor = floor
        self.ceiling = ceiling
        self.quality = max(floor, min(initial_quality, ceiling))
        self._alpha = alpha
        self._drop_t = drop_threshold
        self._recover_t = recover_threshold
        self._step = step
        self.ratio_ewma: float = 0.0
        self.sent: int = 0
        self.dropped: int = 0
        self.last_send_ms: float = 0.0

    def record_send(self, send_seconds: float, interval_seconds: float) -> None:
        """A successful send finished. Update EWMA + adapt quality."""
        denom = interval_seconds if interval_seconds > 1e-6 else 1e-6
        ratio = send_seconds / denom
        self.ratio_ewma = (
            self._alpha * ratio + (1.0 - self._alpha) * self.ratio_ewma
        )
        self.last_send_ms = send_seconds * 1000.0
        if self.ratio_ewma > self._drop_t and self.quality > self.floor:
            self.quality = max(self.floor, self.quality - self._step)
        elif self.ratio_ewma < self._recover_t and self.quality < self.ceiling:
            self.quality = min(self.ceiling, self.quality + self._step)
        self.sent += 1

    def record_drop(self) -> None:
        """A frame was skipped because the previous send was still in
        flight. Sampling-fresh-on-next-tick means we stay in sync."""
        self.dropped += 1

    def snapshot(self) -> dict:
        """Reportable state — surfaced via /healthz for the hub reaper
        and any external observer."""
        return {
            "sent": self.sent,
            "dropped": self.dropped,
            "quality": self.quality,
            "ratio_ewma": round(self.ratio_ewma, 3),
            "last_send_ms": round(self.last_send_ms, 1),
        }
