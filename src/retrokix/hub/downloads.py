"""DownloadManager — drives RomLibrary.download() on a worker thread
and fans progress + completion events out as SSE for the hub frontend.

Lifecycle of a job:

  queued → downloading → ready    (sse: progress*, ready)
                       ↘ failed   (sse: failed)

On `ready`, the manager also asks the HubState to spawn a child play
process for the freshly-downloaded ROM, so the SSE `ready` event can
include the play URL — one round-trip from the client's POV.
"""

from __future__ import annotations

import queue
import threading
import time
from dataclasses import dataclass, field
from pathlib import Path
from typing import Callable, Iterator

from retrokix.hub.state import HubState
from retrokix.library import RomEntry, RomLibrary


# Sentinel for the per-job event queue; tells `events()` the stream is over.
_END = object()


@dataclass
class DownloadJob:
    job_id: str
    rom_name: str
    console: str
    status: str = "queued"
    percent: float = 0.0
    rom_path: Path | None = None
    launch_url: str | None = None
    error: str | None = None
    started_at: float = field(default_factory=time.time)
    _events: "queue.Queue[dict | object]" = field(default_factory=queue.Queue)

    def emit(self, ev: dict) -> None:
        self._events.put(ev)

    def close(self) -> None:
        self._events.put(_END)


LibraryFactory = Callable[[str], RomLibrary]


def _default_library_factory(roms_dir: Path) -> LibraryFactory:
    def make(console: str) -> RomLibrary:
        return RomLibrary(console=console, roms_dir=roms_dir)
    return make


class DownloadManager:
    """Tracks active downloads and ties each to a spawned child on success."""

    def __init__(
        self,
        *,
        hub: HubState,
        roms_dir: Path,
        library_factory: LibraryFactory | None = None,
        runner: Callable[[Callable[[], None]], None] | None = None,
    ) -> None:
        self._hub = hub
        self._roms_dir = roms_dir
        self._library_factory = library_factory or _default_library_factory(roms_dir)
        self._runner = runner or self._default_runner
        self._jobs: dict[str, DownloadJob] = {}
        self._counter = 0
        self._lock = threading.Lock()

    @staticmethod
    def _default_runner(target: Callable[[], None]) -> None:
        threading.Thread(target=target, daemon=True).start()

    def _next_id(self) -> str:
        self._counter += 1
        return f"dl{self._counter:04d}"

    def start(self, rom_name: str, console: str) -> DownloadJob:
        with self._lock:
            job_id = self._next_id()
            job = DownloadJob(job_id=job_id, rom_name=rom_name, console=console)
            self._jobs[job_id] = job
        self._runner(lambda: self._run(job))
        return job

    def get(self, job_id: str) -> DownloadJob | None:
        with self._lock:
            return self._jobs.get(job_id)

    def events(self, job_id: str) -> Iterator[dict]:
        """Generator: yield every event for `job_id` until the job ends.

        Safe to call after the job has already finished — replays the
        terminal event (ready/failed) once and stops."""
        job = self.get(job_id)
        if job is None:
            return
        # Replay terminal state if we missed the live stream.
        if job.status == "ready":
            yield {"type": "ready", "url": job.launch_url, "rom": (
                job.rom_path.name if job.rom_path else job.rom_name
            )}
            return
        if job.status == "failed":
            yield {"type": "failed", "error": job.error or "unknown"}
            return
        while True:
            ev = job._events.get()
            if ev is _END:
                return
            yield ev  # type: ignore[misc]

    def _run(self, job: DownloadJob) -> None:
        try:
            lib = self._library_factory(job.console)
            match = self._find_entry(lib, job.rom_name)
            if match is None:
                raise RuntimeError(f"no archive entry named {job.rom_name!r}")

            total = max(1, match.size)

            def on_progress(downloaded: int, total_bytes: int) -> None:
                # total_bytes is what _stream_download was told; fall
                # back to entry.size when the server didn't say.
                t = total_bytes or total
                pct = min(100.0, 100.0 * downloaded / max(1, t))
                # Coarsen progress to ~1% steps to keep the SSE quiet.
                step = round(pct, 0)
                if step > job.percent:
                    job.percent = step
                    job.emit({"type": "progress", "percent": step})

            job.status = "downloading"
            job.emit({"type": "progress", "percent": 0.0})
            final_path = lib.download(match, progress=False, progress_cb=on_progress)

            gp = self._hub.spawn(final_path, console=job.console)
            job.rom_path = final_path
            job.launch_url = f"/play/{gp.game_id}"
            job.status = "ready"
            job.emit({
                "type": "ready",
                "url": job.launch_url,
                "rom": final_path.name,
            })
        except Exception as exc:
            job.status = "failed"
            job.error = str(exc)
            job.emit({"type": "failed", "error": str(exc)})
        finally:
            job.close()

    @staticmethod
    def _find_entry(lib: RomLibrary, rom_name: str) -> RomEntry | None:
        for e in lib.entries():
            if e.name == rom_name:
                return e
        return None
