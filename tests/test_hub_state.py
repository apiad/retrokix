"""HubState tracks spawned child play --headless processes.

We avoid touching real subprocesses by injecting a fake spawner — that
keeps these tests fast and deterministic. Real-subprocess coverage lives
in test_cli_serve.py (the smoke layer)."""

from __future__ import annotations

import threading

import pytest

from retrokix.hub.state import HubState


@pytest.fixture
def fake_spawner_factory(fake_process_cls):
    def make():
        calls: list[list[str]] = []

        def spawner(cmd: list[str]):
            calls.append(cmd)
            return fake_process_cls()

        return spawner, calls
    return make


def test_allocate_port_returns_free_port():
    hub = HubState(host="127.0.0.1")
    p1 = hub._allocate_port()
    assert isinstance(p1, int)
    assert 1024 < p1 < 65536


def test_spawn_records_process(tmp_path, fake_spawner_factory):
    spawner, calls = fake_spawner_factory()
    hub = HubState(host="127.0.0.1", spawner=spawner)

    rom = tmp_path / "fake.gba"
    rom.write_bytes(b"\x00")
    gp = hub.spawn(rom, console="gba")

    assert gp.game_id.startswith("g")
    assert gp.rom_path == rom
    assert gp.console == "gba"
    assert gp.port > 0
    assert gp.pid >= 9000
    assert hub.get(gp.game_id) is gp
    assert hub.list() == [gp]

    # Spawned with the right CLI shape
    assert len(calls) == 1
    cmd = calls[0]
    assert "play" in cmd
    assert "--headless" in cmd
    assert "--no-open-browser" in cmd
    assert "--listen-port" in cmd
    assert str(gp.port) in cmd
    assert str(rom) in cmd


def test_spawn_allocates_distinct_ports(tmp_path, fake_spawner_factory):
    spawner, _ = fake_spawner_factory()
    hub = HubState(host="127.0.0.1", spawner=spawner)

    rom = tmp_path / "a.gba"
    rom.write_bytes(b"\x00")
    g1 = hub.spawn(rom)
    g2 = hub.spawn(rom)
    assert g1.port != g2.port
    assert g1.game_id != g2.game_id


def test_reap_terminates_process(tmp_path, fake_spawner_factory):
    spawner, _ = fake_spawner_factory()
    hub = HubState(host="127.0.0.1", spawner=spawner)

    rom = tmp_path / "a.gba"
    rom.write_bytes(b"\x00")
    gp = hub.spawn(rom)
    assert hub.reap(gp.game_id) is True
    assert hub.get(gp.game_id) is None
    assert hub.list() == []
    assert gp.process.terminate_calls == 1


def test_reap_unknown_id_returns_false(fake_spawner_factory):
    hub = HubState(host="127.0.0.1", spawner=fake_spawner_factory()[0])
    assert hub.reap("nope") is False


def test_shutdown_all_reaps_every_child(tmp_path, fake_spawner_factory):
    spawner, _ = fake_spawner_factory()
    hub = HubState(host="127.0.0.1", spawner=spawner)

    rom = tmp_path / "a.gba"
    rom.write_bytes(b"\x00")
    g1 = hub.spawn(rom)
    g2 = hub.spawn(rom)

    hub.shutdown_all()
    assert hub.list() == []
    assert g1.process.terminate_calls == 1
    assert g2.process.terminate_calls == 1


def test_spawn_is_thread_safe(tmp_path, fake_spawner_factory):
    spawner, _ = fake_spawner_factory()
    hub = HubState(host="127.0.0.1", spawner=spawner)

    rom = tmp_path / "a.gba"
    rom.write_bytes(b"\x00")

    spawned: list = []

    def worker():
        spawned.append(hub.spawn(rom))

    threads = [threading.Thread(target=worker) for _ in range(20)]
    for t in threads:
        t.start()
    for t in threads:
        t.join()

    assert len(spawned) == 20
    ids = {g.game_id for g in spawned}
    assert len(ids) == 20  # distinct
    assert len(hub.list()) == 20


def test_play_url_uses_child_port(tmp_path, fake_spawner_factory):
    spawner, _ = fake_spawner_factory()
    hub = HubState(host="127.0.0.1", spawner=spawner)

    rom = tmp_path / "a.gba"
    rom.write_bytes(b"\x00")
    gp = hub.spawn(rom)

    url = hub.play_url(gp.game_id)
    assert url == f"http://127.0.0.1:{gp.port}/stream?mode=controller"


def test_play_url_returns_none_for_unknown_id(fake_spawner_factory):
    hub = HubState(host="127.0.0.1", spawner=fake_spawner_factory()[0])
    assert hub.play_url("nope") is None
