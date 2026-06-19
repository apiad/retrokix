"""Tests for /settings — GET + PATCH."""

from __future__ import annotations

from pathlib import Path

import pytest
from fastapi.testclient import TestClient

from retrokix import settings as settings_mod
from retrokix.api.server import create_app
from retrokix.runtime import Mode


class _StubRuntime:
    """Stub matching the surface /settings touches:
    - .settings: live RomSettings snapshot
    - ._persist_setting(**kw): updates settings + writes
    - .speed_multiplier setter: validates + persists
    """
    def __init__(self, root: Path) -> None:
        self.rom_sha1 = "settingstest"
        self._settings_root = root
        self._settings_mod = settings_mod
        self._settings = settings_mod.load(self.rom_sha1, root=self._settings_root)
        self._speed = float(self._settings.speed_multiplier)
        self.mode = Mode.FREE
        self.frame_count = 0

    @property
    def settings(self):
        return self._settings

    def _persist_setting(self, **changes) -> None:
        self._settings = self._settings_mod.update(
            self.rom_sha1, root=self._settings_root, **changes
        )

    @property
    def speed_multiplier(self) -> float:
        return self._speed

    @speed_multiplier.setter
    def speed_multiplier(self, value: float) -> None:
        v = float(value)
        if v <= 0:
            raise ValueError(f"speed_multiplier must be > 0, got {v}")
        self._speed = v
        self._persist_setting(speed_multiplier=v)


@pytest.fixture
def rt(tmp_path: Path) -> _StubRuntime:
    return _StubRuntime(tmp_path / "settings")


@pytest.fixture
def client(rt: _StubRuntime) -> TestClient:
    return TestClient(create_app(rt))


def test_get_settings_returns_defaults(client: TestClient) -> None:
    r = client.get("/settings")
    assert r.status_code == 200
    body = r.json()
    assert body["speed_multiplier"] == 1.0
    assert body["fullscreen"] is False
    assert body["window_scale"] == 3
    assert body["last_slot"] is None


def test_patch_settings_partial_update_persists(client: TestClient, rt: _StubRuntime) -> None:
    r = client.patch("/settings", json={"fullscreen": True, "window_scale": 5})
    assert r.status_code == 200
    body = r.json()
    assert body["fullscreen"] is True
    assert body["window_scale"] == 5
    # Untouched fields keep defaults.
    assert body["speed_multiplier"] == 1.0
    # Reloading from disk shows the same.
    persisted = settings_mod.load(rt.rom_sha1, root=rt._settings_root)
    assert persisted.fullscreen is True
    assert persisted.window_scale == 5


def test_patch_speed_multiplier_routes_through_runtime(client: TestClient, rt: _StubRuntime) -> None:
    """speed_multiplier in PATCH must hit the runtime setter so the
    ticker picks up the new pace, not just persist quietly."""
    r = client.patch("/settings", json={"speed_multiplier": 2.5})
    assert r.status_code == 200
    assert rt._speed == 2.5
    assert r.json()["speed_multiplier"] == 2.5


def test_patch_invalid_speed_multiplier_400(client: TestClient) -> None:
    r = client.patch("/settings", json={"speed_multiplier": 0.0})
    # pydantic rejects with 422; -1.0 would also 422.
    assert r.status_code == 422


def test_patch_invalid_slot_422(client: TestClient) -> None:
    r = client.patch("/settings", json={"last_slot": 99})
    assert r.status_code == 422


def test_patch_invalid_scale_422(client: TestClient) -> None:
    r = client.patch("/settings", json={"window_scale": 0})
    assert r.status_code == 422


def test_patch_empty_body_returns_current(client: TestClient) -> None:
    r = client.patch("/settings", json={})
    assert r.status_code == 200
    body = r.json()
    assert body == {
        "speed_multiplier": 1.0,
        "fullscreen": False,
        "window_scale": 3,
        "last_slot": None,
    }


def test_patch_unknown_key_ignored_422(client: TestClient) -> None:
    """pydantic by default ignores unknown keys for a permissive model
    — confirm the documented behavior so callers can rely on it."""
    r = client.patch("/settings", json={"some_future_field": "x"})
    # The PATCH succeeds and the unknown key is dropped.
    assert r.status_code == 200
