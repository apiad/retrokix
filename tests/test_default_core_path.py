"""Tests for the _default_core_path() precedence in gbax.runtime."""
from __future__ import annotations

from gbax.runtime import _default_core_path


def test_env_var_wins_over_bundled(monkeypatch, tmp_path):
    env_path = tmp_path / "env-core.so"
    env_path.write_bytes(b"\x7fELF")
    bundled = tmp_path / "bundled-core.so"
    bundled.write_bytes(b"\x7fELF")

    monkeypatch.setenv("GBAX_CORE_PATH", str(env_path))
    monkeypatch.setattr("gbax.cores.bundled_core_path", lambda *_: bundled)

    assert _default_core_path() == env_path


def test_bundled_wins_over_dev_fixture_when_no_env(monkeypatch, tmp_path):
    bundled = tmp_path / "bundled-core.so"
    bundled.write_bytes(b"\x7fELF")

    monkeypatch.delenv("GBAX_CORE_PATH", raising=False)
    monkeypatch.setattr("gbax.cores.bundled_core_path", lambda *_: bundled)

    assert _default_core_path() == bundled


def test_dev_fixture_is_last_resort(monkeypatch):
    monkeypatch.delenv("GBAX_CORE_PATH", raising=False)
    monkeypatch.setattr("gbax.cores.bundled_core_path", lambda *_: None)

    result = _default_core_path()
    # Returns the dev fixture path even if the file doesn't exist —
    # EmulatorRuntime raises the "not found" error downstream.
    assert result.name == "mgba_libretro.so"
    assert "tests" in result.parts and "cores" in result.parts
