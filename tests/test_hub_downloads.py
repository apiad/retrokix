"""DownloadManager tests.

Real archive.org download is mocked at the RomLibrary boundary: we
inject a stub RomLibrary that synthesises an entry and writes a fake
ROM to the configured roms_dir, calling the progress callback with
chunked totals along the way.
"""

from __future__ import annotations

from pathlib import Path

import pytest

from retrokix.hub.downloads import DownloadManager
from retrokix.hub.state import HubState
from retrokix.library import RomEntry


class StubRomLibrary:
    """RomLibrary look-alike. Returns one synthetic entry and "downloads"
    by writing bytes to roms_dir + invoking progress_cb."""

    def __init__(self, console: str, roms_dir: Path, *, entry_size: int = 1024):
        self.console = console
        self.roms_dir = roms_dir
        self._entry = RomEntry(
            name=f"Stub - Game ({console.upper()}).zip",
            size=entry_size,
            sha1=None,
            console=console,
        )

    def entries(self) -> list[RomEntry]:
        return [self._entry]

    def download(self, entry: RomEntry, progress: bool = True, progress_cb=None) -> Path:
        # Emit progress in 4 chunks
        for step in (256, 512, 768, entry.size):
            if progress_cb is not None:
                progress_cb(step, entry.size)
        self.roms_dir.mkdir(parents=True, exist_ok=True)
        out = self.roms_dir / f"stub-{entry.console}.gba"
        out.write_bytes(b"\x00" * entry.size)
        return out


@pytest.fixture
def stub_library_factory(tmp_path):
    def make(console: str) -> StubRomLibrary:
        return StubRomLibrary(console, tmp_path)
    return make


@pytest.fixture
def hub_state(fake_process_cls) -> HubState:
    def spawner(cmd):
        return fake_process_cls()
    return HubState(host="127.0.0.1", spawner=spawner)


def _sync_runner(target):
    """Run the worker synchronously — keeps tests deterministic."""
    target()


def test_start_runs_full_pipeline_and_emits_ready(tmp_path, hub_state, stub_library_factory):
    dm = DownloadManager(
        hub=hub_state,
        roms_dir=tmp_path,
        library_factory=stub_library_factory,
        runner=_sync_runner,
    )
    job = dm.start("Stub - Game (GBA).zip", "gba")

    assert job.status == "ready"
    assert job.rom_path is not None
    assert job.rom_path.exists()
    assert job.launch_url.startswith("/play/")
    # Hub state has the spawned child registered
    assert len(hub_state.list()) == 1


def test_events_replays_terminal_state(tmp_path, hub_state, stub_library_factory):
    dm = DownloadManager(
        hub=hub_state,
        roms_dir=tmp_path,
        library_factory=stub_library_factory,
        runner=_sync_runner,
    )
    job = dm.start("Stub - Game (GBA).zip", "gba")
    # Job already finished; the replay yields just the terminal event.
    evs = list(dm.events(job.job_id))
    assert len(evs) == 1
    assert evs[0]["type"] == "ready"
    assert evs[0]["url"] == job.launch_url


def test_events_streams_progress_during_run(tmp_path, hub_state, stub_library_factory):
    """When run in-thread (real runner), events() yields progress then ready."""
    def runner(target):
        # Run synchronously so the events queue is fully populated.
        target()

    dm = DownloadManager(
        hub=hub_state,
        roms_dir=tmp_path,
        library_factory=stub_library_factory,
        runner=runner,
    )
    job = dm.start("Stub - Game (GBA).zip", "gba")
    # With synchronous runner, job has completed by the time start returns.
    assert job.status == "ready"
    # Snapshot of all emitted events from the queue replay path:
    evs = list(dm.events(job.job_id))
    assert evs[-1]["type"] == "ready"


def test_unknown_archive_entry_fails(tmp_path, hub_state, stub_library_factory):
    dm = DownloadManager(
        hub=hub_state,
        roms_dir=tmp_path,
        library_factory=stub_library_factory,
        runner=_sync_runner,
    )
    job = dm.start("does-not-exist.zip", "gba")
    assert job.status == "failed"
    assert job.error is not None
    assert "no archive entry" in job.error.lower()
    evs = list(dm.events(job.job_id))
    assert evs[0]["type"] == "failed"


def test_get_returns_none_for_unknown(tmp_path, hub_state):
    dm = DownloadManager(hub=hub_state, roms_dir=tmp_path)
    assert dm.get("nope") is None
    # events() on unknown id is just an empty generator
    assert list(dm.events("nope")) == []
