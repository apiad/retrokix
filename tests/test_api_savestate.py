"""Tests for /savestate/* — list, save, load, load_latest."""

from __future__ import annotations

from pathlib import Path

import pytest
from fastapi.testclient import TestClient

from retrokix.api.server import create_app


_FAKE_PNG = (
    b"\x89PNG\r\n\x1a\n"
    b"\x00\x00\x00\rIHDR\x00\x00\x00\x01\x00\x00\x00\x01"
    b"\x08\x02\x00\x00\x00\x90wS\xde"
    b"\x00\x00\x00\x0cIDATx\x9cc\xf8\xcf\xc0\xc0\xc0\x00\x00\x00\x05\x00\x01"
    b"^\xf3*:"
    b"\x00\x00\x00\x00IEND\xaeB`\x82"
)


class _StubRuntime:
    """Minimal runtime: pretends to have a real ROM by exposing a fake
    sha1 + the two private-ish methods the savestate routes call
    (_running_dir, _slot_path). save/load operate on bytes in memory.

    Stays in lockstep with EmulatorRuntime's surface but never touches
    the libretro core, so it runs without the mGBA shared object."""

    def __init__(self, save_dir: Path) -> None:
        self.rom_sha1 = "deadbeef"
        self._save_dir = save_dir
        self._slots: dict[int, bytes] = {}
        self._frame_count = 0
        self._loaded: tuple[str, bytes] | None = None

    def _slot_path(self, slot: int) -> Path:
        return self._save_dir / self.rom_sha1 / f"slot-{slot}.state"

    def _running_dir(self) -> Path:
        return self._save_dir / self.rom_sha1 / "running"

    def save_state_to_slot(self, slot: int) -> bytes:
        blob = b"slot-%d" % slot
        path = self._slot_path(slot)
        path.parent.mkdir(parents=True, exist_ok=True)
        path.write_bytes(blob)
        path.with_suffix(".png").write_bytes(_FAKE_PNG)
        self._slots[slot] = blob
        return blob

    def load_state_from_slot(self, slot: int) -> None:
        if slot not in self._slots:
            raise KeyError(f"slot {slot} is empty")
        self._loaded = ("slot", self._slots[slot])

    def save_state_running(self):
        from datetime import datetime, timezone
        ts = datetime.now(timezone.utc).strftime("%Y-%m-%dT%H-%M-%S.%f")[:-3] + "Z"
        path = self._running_dir() / f"running-{ts}.state"
        path.parent.mkdir(parents=True, exist_ok=True)
        path.write_bytes(b"running-%s" % ts.encode())
        path.with_suffix(".png").write_bytes(_FAKE_PNG)
        return path

    def latest_running_save(self):
        d = self._running_dir()
        if not d.exists():
            return None
        files = sorted(d.glob("running-*.state"))
        return files[-1] if files else None

    def load_state_from_file(self, path: Path) -> None:
        self._loaded = ("file", path.read_bytes())


@pytest.fixture
def rt(tmp_path: Path) -> _StubRuntime:
    return _StubRuntime(tmp_path / "saves")


@pytest.fixture
def client(rt: _StubRuntime) -> TestClient:
    return TestClient(create_app(rt))


def test_list_returns_empty_when_no_saves(client: TestClient) -> None:
    body = client.get("/savestate/list").json()
    assert body == {"slots": [], "running": []}


def test_save_then_list_shows_running(client: TestClient, rt: _StubRuntime) -> None:
    r = client.post("/savestate/save")
    assert r.status_code == 200
    saved = r.json()
    assert saved["name"].startswith("running-")
    body = client.get("/savestate/list").json()
    assert len(body["running"]) == 1
    assert body["running"][0]["name"] == saved["name"]
    assert body["running"][0]["size"] > 0


def test_list_includes_slot_saves(client: TestClient, rt: _StubRuntime) -> None:
    rt.save_state_to_slot(3)
    rt.save_state_to_slot(7)
    body = client.get("/savestate/list").json()
    slot_nums = sorted(s["slot"] for s in body["slots"])
    assert slot_nums == [3, 7]


def test_load_latest_404_when_empty(client: TestClient) -> None:
    r = client.post("/savestate/load_latest")
    assert r.status_code == 404


def test_load_latest_after_save_loads_newest(client: TestClient, rt: _StubRuntime) -> None:
    client.post("/savestate/save")
    second = client.post("/savestate/save").json()
    r = client.post("/savestate/load_latest")
    assert r.status_code == 200
    assert r.json()["loaded"] == second["name"]
    assert rt._loaded is not None
    assert rt._loaded[0] == "file"


def test_load_by_slot(client: TestClient, rt: _StubRuntime) -> None:
    rt.save_state_to_slot(5)
    r = client.post("/savestate/load", json={"slot": 5})
    assert r.status_code == 200
    assert r.json()["loaded"] == "slot-5"


def test_load_by_slot_empty_returns_404(client: TestClient, rt: _StubRuntime) -> None:
    r = client.post("/savestate/load", json={"slot": 2})
    assert r.status_code == 404


def test_load_running_by_name(client: TestClient, rt: _StubRuntime) -> None:
    saved = client.post("/savestate/save").json()
    r = client.post("/savestate/load", json={"running": saved["name"]})
    assert r.status_code == 200
    assert r.json()["loaded"] == saved["name"]


def test_load_rejects_path_traversal(client: TestClient) -> None:
    r = client.post("/savestate/load", json={"running": "../escape.state"})
    assert r.status_code == 400


def test_load_rejects_slash_in_name(client: TestClient) -> None:
    r = client.post("/savestate/load", json={"running": "nested/file.state"})
    assert r.status_code == 400


def test_load_without_slot_or_running_400(client: TestClient) -> None:
    r = client.post("/savestate/load", json={})
    assert r.status_code == 400


def test_load_with_invalid_slot_number_400(client: TestClient) -> None:
    r = client.post("/savestate/load", json={"slot": 11})
    assert r.status_code == 400


def test_list_running_includes_thumb_url_when_png_exists(client: TestClient) -> None:
    saved = client.post("/savestate/save").json()
    body = client.get("/savestate/list").json()
    assert body["running"][0]["thumb"] == f"/savestate/thumb?running={saved['name']}"


def test_list_slot_includes_thumb_url_when_png_exists(
    client: TestClient, rt: _StubRuntime
) -> None:
    rt.save_state_to_slot(4)
    body = client.get("/savestate/list").json()
    entry = next(s for s in body["slots"] if s["slot"] == 4)
    assert entry["thumb"] == "/savestate/thumb?slot=4"


def test_list_omits_thumb_when_png_missing(
    client: TestClient, rt: _StubRuntime
) -> None:
    # Lay down a state with no PNG sidecar.
    path = rt._slot_path(6)
    path.parent.mkdir(parents=True, exist_ok=True)
    path.write_bytes(b"slot-6")
    body = client.get("/savestate/list").json()
    entry = next(s for s in body["slots"] if s["slot"] == 6)
    assert "thumb" not in entry


def test_thumb_returns_png_for_slot(client: TestClient, rt: _StubRuntime) -> None:
    rt.save_state_to_slot(2)
    r = client.get("/savestate/thumb?slot=2")
    assert r.status_code == 200
    assert r.headers["content-type"] == "image/png"
    assert r.content.startswith(b"\x89PNG\r\n\x1a\n")


def test_thumb_returns_png_for_running(client: TestClient) -> None:
    saved = client.post("/savestate/save").json()
    r = client.get(f"/savestate/thumb?running={saved['name']}")
    assert r.status_code == 200
    assert r.headers["content-type"] == "image/png"


def test_thumb_404_when_missing(client: TestClient) -> None:
    r = client.get("/savestate/thumb?slot=8")
    assert r.status_code == 404


def test_thumb_400_when_no_args(client: TestClient) -> None:
    r = client.get("/savestate/thumb")
    assert r.status_code == 400


def test_thumb_400_when_slot_out_of_range(client: TestClient) -> None:
    r = client.get("/savestate/thumb?slot=99")
    assert r.status_code == 400


def test_thumb_rejects_path_traversal(client: TestClient) -> None:
    r = client.get("/savestate/thumb?running=../escape.state")
    assert r.status_code == 400


def test_viewer_html_includes_saves_and_cheats_buttons() -> None:
    """The stream viewer page advertises the new header buttons + panels."""
    rt = _StubRuntime(Path("/tmp/_unused"))
    client = TestClient(create_app(rt))
    body = client.get("/stream").text
    assert 'id="saves-toggle"' in body
    assert 'id="cheats-toggle"' in body
    assert 'id="saves-panel"' in body
    assert 'id="cheats-panel"' in body
