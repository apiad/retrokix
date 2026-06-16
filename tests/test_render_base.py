"""Tests for the renderer base layer."""
from __future__ import annotations

from retrokix.render.base import SHADERS, Renderer


def test_shaders_registry_has_core_entries():
    assert "nearest" in SHADERS
    assert "linear" in SHADERS


def test_shaders_returns_wgsl_strings():
    for _name, source in SHADERS.items():
        assert isinstance(source, str)
        assert "fs_main" in source


def test_renderer_protocol_attrs():
    expected = {"init", "present_frame", "set_shader", "cycle_shader", "set_fullscreen", "close"}
    methods = set(dir(Renderer))
    assert expected.issubset(methods)
