"""Tests for /stream (HTML viewer) + /stream/ws (WebSocket JPEG push)."""

from __future__ import annotations

import io

import numpy as np
import pytest
from fastapi.testclient import TestClient
from PIL import Image

from gbax.api.server import create_app


class _StubRuntime:
    """Minimal runtime stub — owns a 240x160 RGB framebuffer and bumps a
    pixel between reads so subsequent JPEGs differ enough to tell apart.
    Also records every set_buttons call so we can assert input flow."""

    def __init__(self) -> None:
        self._fb = np.zeros((160, 240, 3), dtype=np.uint8)
        self._tick = 0
        self.set_buttons_calls: list[set] = []

    def framebuffer(self) -> np.ndarray:
        self._tick = (self._tick + 1) % 200
        self._fb[10, 10] = (self._tick, 0, 0)
        return self._fb

    def set_buttons(self, buttons) -> None:
        self.set_buttons_calls.append(set(buttons))


@pytest.fixture
def client() -> TestClient:
    return TestClient(create_app(_StubRuntime()))


def test_viewer_html_served(client: TestClient) -> None:
    resp = client.get("/stream")
    assert resp.status_code == 200
    assert resp.headers["content-type"].startswith("text/html")
    body = resp.text
    # Sanity: page contains the canvas + the WS URL builder.
    assert '<canvas id="screen"' in body
    assert "/stream/ws" in body


def test_websocket_pushes_decodable_jpeg_frames(client: TestClient) -> None:
    with client.websocket_connect("/stream/ws?fps=60&quality=80") as ws:
        for _ in range(3):
            data = ws.receive_bytes()
            assert data[:2] == b"\xff\xd8"  # JPEG SOI marker
            img = Image.open(io.BytesIO(data))
            img.load()
            assert img.size == (240, 160)


def test_fps_param_is_clamped(client: TestClient) -> None:
    """fps=99999 is clamped to the max — we still get frames, not a 500."""
    with client.websocket_connect("/stream/ws?fps=99999") as ws:
        data = ws.receive_bytes()
        assert data[:2] == b"\xff\xd8"


def test_quality_param_is_clamped(client: TestClient) -> None:
    with client.websocket_connect("/stream/ws?quality=200") as ws:
        data = ws.receive_bytes()
        assert data[:2] == b"\xff\xd8"


# ---------- controller input over WS ----------

def test_ws_button_message_calls_set_buttons() -> None:
    """Client sends `{type:buttons, buttons:["A","UP"]}` and the runtime
    sees the corresponding Button set."""
    from gbax.input import Button

    rt = _StubRuntime()
    client = TestClient(create_app(rt))

    with client.websocket_connect("/stream/ws?fps=60") as ws:
        ws.receive_bytes()  # one frame, confirms we're connected
        ws.send_text('{"type":"buttons","buttons":["A","UP"]}')
        # Receive a frame to give the server a chance to drain the WS recv queue.
        for _ in range(6):
            ws.receive_bytes()
            if rt.set_buttons_calls:
                break

    assert rt.set_buttons_calls, "set_buttons was never called"
    assert rt.set_buttons_calls[-1] == {Button.A, Button.UP}


def test_ws_button_release_sends_empty_set() -> None:
    """An empty buttons array (release) is honored — runtime sees {}."""
    rt = _StubRuntime()
    client = TestClient(create_app(rt))

    with client.websocket_connect("/stream/ws?fps=60") as ws:
        ws.receive_bytes()
        ws.send_text('{"type":"buttons","buttons":["A"]}')
        ws.send_text('{"type":"buttons","buttons":[]}')
        for _ in range(8):
            ws.receive_bytes()
            if len(rt.set_buttons_calls) >= 2:
                break

    assert len(rt.set_buttons_calls) >= 2
    assert rt.set_buttons_calls[-1] == set()


def test_ws_invalid_button_message_does_not_crash() -> None:
    """Bad JSON, wrong shape, and unknown button names are silently
    dropped — never escalated to a 500/disconnect."""
    rt = _StubRuntime()
    client = TestClient(create_app(rt))

    with client.websocket_connect("/stream/ws?fps=60") as ws:
        ws.receive_bytes()
        ws.send_text("not json at all")
        ws.send_text('{"type":"nope"}')
        ws.send_text('{"type":"buttons","buttons":["X","NOSEPASS"]}')
        # Connection should still be alive and still pushing frames.
        for _ in range(4):
            ws.receive_bytes()

    assert rt.set_buttons_calls == [], "invalid messages must not call set_buttons"


def test_viewer_html_mentions_both_modes(client: TestClient) -> None:
    """The viewer page advertises both mode links so a user can
    switch without editing the URL by hand."""
    body = client.get("/stream").text
    assert "mode=viewer" in body
    assert "mode=controller" in body
    # The on-screen controller widgets are in the DOM (CSS hides them
    # in viewer mode), so the buttons exist regardless of mode.
    assert 'data-button="A"' in body
    assert 'data-button="UP"' in body
    assert 'data-button="START"' in body
