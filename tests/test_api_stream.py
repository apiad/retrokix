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
    pixel between reads so subsequent JPEGs differ enough to tell apart."""

    def __init__(self) -> None:
        self._fb = np.zeros((160, 240, 3), dtype=np.uint8)
        self._tick = 0

    def framebuffer(self) -> np.ndarray:
        self._tick = (self._tick + 1) % 200
        self._fb[10, 10] = (self._tick, 0, 0)
        return self._fb


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
