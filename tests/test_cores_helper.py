"""Tests for the retrokix.cores helper module."""
from __future__ import annotations

from pathlib import Path

from retrokix import cores


def test_mgba_version_is_a_string():
    assert isinstance(cores.MGBA_VERSION, str)
    assert cores.MGBA_VERSION  # non-empty


def test_bundled_core_path_returns_none_when_absent(monkeypatch, tmp_path):
    # When the bundled .so doesn't exist in the installed package, the
    # helper must return None so the caller can fall back.
    fake_pkg = tmp_path / "gbax_cores_fake"
    fake_pkg.mkdir()
    (fake_pkg / "__init__.py").write_text("")

    def fake_files(pkg: str) -> Path:
        assert pkg == "retrokix.cores"
        return fake_pkg

    monkeypatch.setattr(cores, "_files", fake_files)
    assert cores.bundled_core_path() is None


def test_bundled_core_path_returns_path_when_present(monkeypatch, tmp_path):
    fake_pkg = tmp_path / "gbax_cores_fake"
    fake_pkg.mkdir()
    so = fake_pkg / "mgba_libretro.so"
    so.write_bytes(b"\x7fELF")

    def fake_files(pkg: str) -> Path:
        return fake_pkg

    monkeypatch.setattr(cores, "_files", fake_files)
    assert cores.bundled_core_path() == so
