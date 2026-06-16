"""IdleReaper tests.

We drive the reaper synchronously via `tick()` and inject:
- a `probe` that returns the canned ws_clients we want
- a `clock` that returns a known "now"

Tests mutate `gp.started_at` after `hub.spawn(...)` to anchor each
process's age relative to the injected clock.
"""

from __future__ import annotations

import pytest

from retrokix.hub.reaper import IdleReaper
from retrokix.hub.state import HubState


@pytest.fixture
def hub_state(fake_process_cls) -> HubState:
    def spawner(cmd):
        return fake_process_cls()
    return HubState(host="127.0.0.1", spawner=spawner)


@pytest.fixture
def rom(tmp_path):
    p = tmp_path / "x.gba"
    p.write_bytes(b"\x00")
    return p


def _build_reaper(hub, *, probe, now, idle_threshold=60.0, grace_period=20.0):
    """Reaper with controllable clock + probe and zero poll interval."""
    return IdleReaper(
        hub,
        probe=probe,
        clock=lambda: now[0],
        poll_interval=0.0,
        idle_threshold=idle_threshold,
        grace_period=grace_period,
    )


def test_does_not_reap_during_grace_period(hub_state, rom):
    now = [1000.0]
    gp = hub_state.spawn(rom)
    gp.started_at = 990.0  # 10s old; grace = 20
    reaper = _build_reaper(hub_state, probe=lambda h, p: 0, now=now)
    assert reaper.tick() == []
    assert hub_state.get(gp.game_id) is not None


def test_does_not_reap_when_someone_watching(hub_state, rom):
    now = [1000.0]
    gp = hub_state.spawn(rom)
    gp.started_at = 800.0  # 200s old, well past grace
    reaper = _build_reaper(hub_state, probe=lambda h, p: 3, now=now)
    assert reaper.tick() == []
    assert hub_state.get(gp.game_id) is not None


def test_first_idle_tick_records_timestamp_but_does_not_reap(hub_state, rom):
    now = [1000.0]
    gp = hub_state.spawn(rom)
    gp.started_at = 800.0
    reaper = _build_reaper(hub_state, probe=lambda h, p: 0, now=now)
    # First idle observation — just records timestamp
    assert reaper.tick() == []
    assert hub_state.get(gp.game_id) is not None


def test_reaps_after_idle_threshold(hub_state, rom):
    now = [1000.0]
    gp = hub_state.spawn(rom)
    gp.started_at = 800.0
    reaper = _build_reaper(hub_state, probe=lambda h, p: 0, now=now, idle_threshold=60.0)

    # T0: first idle observation
    reaper.tick()
    # T0 + 30s: still idle, still under threshold
    now[0] = 1030.0
    assert reaper.tick() == []
    assert hub_state.get(gp.game_id) is not None
    # T0 + 70s: past threshold → reaped
    now[0] = 1070.0
    assert reaper.tick() == [gp.game_id]
    assert hub_state.get(gp.game_id) is None


def test_resume_resets_idle_clock(hub_state, rom):
    now = [1000.0]
    gp = hub_state.spawn(rom)
    gp.started_at = 800.0
    # Probe state controlled by closure so we can flip it mid-test
    ws = [0]
    reaper = _build_reaper(hub_state, probe=lambda h, p: ws[0], now=now)

    reaper.tick()  # records idle at 1000
    now[0] = 1030.0
    ws[0] = 1  # tab reopened
    reaper.tick()  # clears the idle timestamp
    now[0] = 1080.0  # would have been past 60s threshold from 1000
    ws[0] = 0
    reaper.tick()  # records idle fresh at 1080
    now[0] = 1100.0  # only 20s of new idle
    assert reaper.tick() == []
    assert hub_state.get(gp.game_id) is not None


def test_probe_failure_does_not_reap(hub_state, rom):
    now = [1000.0]
    gp = hub_state.spawn(rom)
    gp.started_at = 800.0
    reaper = _build_reaper(hub_state, probe=lambda h, p: None, now=now)
    # Probe returns None — child treated as unknown, not reaped
    reaper.tick()
    now[0] = 1100.0
    assert reaper.tick() == []
    assert hub_state.get(gp.game_id) is not None


def test_reaps_multiple_children_independently(hub_state, rom):
    now = [1000.0]
    g1 = hub_state.spawn(rom)
    g2 = hub_state.spawn(rom)
    g1.started_at = 800.0
    g2.started_at = 800.0

    ws_by_port = {g1.port: 0, g2.port: 2}  # g2 is being watched
    reaper = _build_reaper(
        hub_state,
        probe=lambda h, p: ws_by_port[p],
        now=now,
    )
    reaper.tick()
    now[0] = 1100.0
    reaped = reaper.tick()
    assert reaped == [g1.game_id]
    assert hub_state.get(g1.game_id) is None
    assert hub_state.get(g2.game_id) is not None


def test_start_and_stop_idempotent(hub_state):
    reaper = IdleReaper(hub_state, poll_interval=10.0)
    reaper.start()
    reaper.start()  # no-op
    reaper.stop()
    reaper.stop()  # no-op
