"""Smoke tests for HintsPane (stubbed LLM, fake runtime — no network)."""
from __future__ import annotations

from textual.app import App, ComposeResult

from retrokix.tui.hints_widget import HintsPane


class _FakeRuntime:
    rom_path = "/nonexistent.gba"

    def read_memory(self, addr: int, n: int) -> bytes:
        return b"\x00" * n


class _Host(App):
    def __init__(self, pane):
        super().__init__()
        self._pane = pane

    def compose(self) -> ComposeResult:
        yield self._pane


async def test_generate_updates_hint_text(monkeypatch):
    monkeypatch.setattr(
        "retrokix.tui.hints_widget.generate_hint", lambda prompt, cfg, **k: "Head to Slateport!"
    )
    monkeypatch.setattr(
        "retrokix.tui.hints_widget.load_config",
        lambda *a, **k: {"base_url": "http://x/v1", "api_key": "k", "model": "m"},
    )
    ctx = type("C", (), {"runtime": _FakeRuntime()})()
    app = _Host(HintsPane(ctx))
    async with app.run_test() as pilot:
        app.query_one(HintsPane).generate()
        await app.workers.wait_for_complete()
        await pilot.pause()
        assert "Head to Slateport!" in str(app.query_one("#hints-text").render())


async def test_generate_without_runtime_says_no_save():
    app = _Host(HintsPane(ctx=None))
    async with app.run_test():
        app.query_one(HintsPane).generate()
        assert "No save loaded." in str(app.query_one("#hints-text").render())
