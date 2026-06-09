"""End-to-end tests for the FastAPI server."""

from __future__ import annotations

import base64
from io import BytesIO

import pytest
from fastapi.testclient import TestClient
from PIL import Image

from gbax.api.server import create_app
from gbax.runtime import EmulatorRuntime, Mode


@pytest.fixture
def client(test_rom, mgba_core):
    rt = EmulatorRuntime(test_rom, core_path=mgba_core, mode=Mode.STEP)
    yield TestClient(create_app(rt)), rt
    rt.close()


# --- control ---


def test_get_mode_is_step_by_default(client):
    c, _ = client
    r = c.get("/mode")
    assert r.status_code == 200
    assert r.json() == {"mode": "step"}


def test_post_mode_to_free_starts_ticker(client):
    import time
    c, rt = client
    r = c.post("/mode", json={"mode": "free"})
    assert r.status_code == 200
    time.sleep(0.3)
    fc = rt.frame_count
    # Switch back to step to stop the ticker before client teardown
    c.post("/mode", json={"mode": "step"})
    assert fc > 0


def test_post_mode_unknown_rejected(client):
    c, _ = client
    r = c.post("/mode", json={"mode": "wat"})
    assert r.status_code == 422


def test_post_step_advances(client):
    c, rt = client
    assert rt.frame_count == 0
    r = c.post("/step?frames=5")
    assert r.status_code == 200
    assert r.json() == {"frame_count": 5}
    assert rt.frame_count == 5


def test_post_step_rejected_in_free_mode(client):
    c, rt = client
    c.post("/mode", json={"mode": "free"})
    r = c.post("/step?frames=1")
    assert r.status_code == 409
    c.post("/mode", json={"mode": "step"})


def test_get_frame_count_after_step(client):
    c, rt = client
    rt.step(frames=7)
    r = c.get("/frame_count")
    assert r.json() == {"frame_count": 7}


# --- speed ---


def test_post_speed_sets_multiplier(client):
    c, rt = client
    r = c.post("/speed", json={"multiplier": 4.0})
    assert r.status_code == 200
    assert r.json() == {"multiplier": 4.0}
    assert rt.speed_multiplier == 4.0


def test_post_speed_rejects_nonpositive(client):
    c, _ = client
    r = c.post("/speed", json={"multiplier": 0.0})
    assert r.status_code in (400, 422)
    r = c.post("/speed", json={"multiplier": -1.0})
    assert r.status_code in (400, 422)


def test_get_speed(client):
    c, rt = client
    rt.speed_multiplier = 2.5
    r = c.get("/speed")
    assert r.json() == {"multiplier": 2.5}


# --- frame ---


def test_get_frame_png(client):
    c, rt = client
    rt.step(frames=1)
    r = c.get("/frame")
    assert r.status_code == 200
    assert r.headers["content-type"] == "image/png"
    img = Image.open(BytesIO(r.content))
    assert img.size == (240, 160)
    assert img.mode == "RGB"


def test_get_frame_raw(client):
    c, rt = client
    rt.step(frames=1)
    r = c.get("/frame?fmt=raw")
    assert r.status_code == 200
    assert r.headers["content-type"] == "application/octet-stream"
    assert len(r.content) == 240 * 160 * 3


def test_get_frame_unknown_fmt(client):
    c, _ = client
    r = c.get("/frame?fmt=jpeg")
    assert r.status_code == 400


# --- buttons ---


def test_get_buttons_empty(client):
    c, _ = client
    r = c.get("/buttons")
    assert r.json() == {"buttons": []}


def test_post_buttons_sets_held(client):
    c, rt = client
    r = c.post("/buttons", json={"buttons": ["a", "right"]})
    assert r.status_code == 200
    assert set(r.json()["buttons"]) == {"a", "right"}
    from gbax.input import Button
    assert rt.buttons_held() == {Button.A, Button.RIGHT}


def test_post_buttons_empty_releases_all(client):
    c, rt = client
    c.post("/buttons", json={"buttons": ["a", "b"]})
    c.post("/buttons", json={"buttons": []})
    assert rt.buttons_held() == set()


def test_post_buttons_rejects_unknown(client):
    c, _ = client
    r = c.post("/buttons", json={"buttons": ["turbo"]})
    assert r.status_code == 400


# --- memory ---


def test_get_memory_hex(client):
    c, rt = client
    rt.write_memory(0x02000000, b"\xDE\xAD\xBE\xEF")
    r = c.get("/memory?addr=33554432&len=4&fmt=hex")  # 0x02000000
    assert r.status_code == 200
    assert r.json() == {"addr": 0x02000000, "len": 4, "data": "deadbeef"}


def test_get_memory_base64(client):
    c, rt = client
    rt.write_memory(0x02000000, b"abcd")
    r = c.get("/memory?addr=33554432&len=4&fmt=base64")
    assert r.status_code == 200
    assert base64.b64decode(r.json()["data"]) == b"abcd"


def test_post_memory_write_then_read(client):
    c, rt = client
    # /memory writes raw bytes in order. Little-endian u32 reads back reversed.
    r = c.post("/memory", json={"addr": 0x02000010, "data": "cafebabe", "width": 4})
    assert r.status_code == 200
    assert rt.read_memory(0x02000010, 4) == b"\xCA\xFE\xBA\xBE"
    assert rt.read_u32(0x02000010) == 0xBEBAFECA  # bytes 0xCA,0xFE,0xBA,0xBE as LE u32


def test_post_memory_bad_width(client):
    c, _ = client
    r = c.post("/memory", json={"addr": 0x02000000, "data": "00", "width": 3})
    assert r.status_code == 400


def test_get_memory_too_large(client):
    c, _ = client
    r = c.get("/memory?addr=0&len=999999")
    assert r.status_code == 400
