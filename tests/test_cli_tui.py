"""Tests for the --tui orchestration wiring in retrokix.cli._run_with_tui.

Confirms the threading contract without a display or a real Textual app:
play_loop runs with interactive=False + the shared snapshot/stop_event, and
the TUI is constructed with the plugin's tabs.
"""

from __future__ import annotations

from pathlib import Path

from retrokix.cli import _run_with_tui


class _FakeApp:
    last = None

    def __init__(self, snapshot, tab_specs, tab_context, *a, **k):
        self.snapshot = snapshot
        self.tab_specs = tab_specs
        self.tab_context = tab_context
        self.exited = False
        _FakeApp.last = self

    def run(self):  # returns immediately — stands in for the blocking UI
        self.ran = True

    def call_from_thread(self, fn, *a, **k):
        return fn(*a, **k)

    def exit(self):
        self.exited = True


class _FakeRuntime:
    rom_sha1 = "abc123"
    console = "GBA"


def test_run_with_tui_passes_snapshot_and_disables_interactive(monkeypatch):
    captured = {}

    def fake_play_loop(**kwargs):
        captured.update(kwargs)

    monkeypatch.setattr("retrokix.render.play_loop", fake_play_loop)
    monkeypatch.setattr("retrokix.tui.app.RetrokixTUI", _FakeApp)

    loop_kwargs = {"runtime": _FakeRuntime(), "scale": 3}
    _run_with_tui(loop_kwargs, _FakeRuntime(), None, Path("/roms/game.gba"))

    assert captured["interactive"] is False
    assert captured["status_snapshot"] is not None
    assert captured["stop_event"] is not None
    assert captured["scale"] == 3
    # No plugin → no plugin tabs.
    assert _FakeApp.last.tab_specs == []
    assert _FakeApp.last.tab_context.title == "game.gba"


def test_run_with_tui_loads_plugin_tabs(monkeypatch, tmp_path):
    monkeypatch.setattr("retrokix.render.play_loop", lambda **k: None)
    monkeypatch.setattr("retrokix.tui.app.RetrokixTUI", _FakeApp)

    plugin_file = tmp_path / "myplugin.py"
    plugin_file.write_text(
        "import retrokix\np = retrokix.plugin()\n@p.tab('Demo')\ndef make(ctx):\n    return ctx\n"
    )
    _run_with_tui({"runtime": _FakeRuntime()}, _FakeRuntime(), plugin_file, Path("/roms/g.gba"))

    assert [t[0] for t in _FakeApp.last.tab_specs] == ["Demo"]
