"""Tests for the reusable TUI prompt primitive (PromptModal + prompt_via_app)."""
from __future__ import annotations

from retrokix.tui.prompt import PromptModal, prompt_via_app
from textual.app import App
from textual.widgets import Input


class _Host(App):
    def __init__(self, modal: PromptModal) -> None:
        super().__init__()
        self._modal = modal
        self.result: object = "UNSET"

    def on_mount(self) -> None:
        self.push_screen(self._modal, self._got)

    def _got(self, value) -> None:
        self.result = value


# ---- PromptModal (run_test) ----


async def test_modal_submit_returns_field_values():
    app = _Host(PromptModal("Capture labels", ["labels"]))
    async with app.run_test() as pilot:
        await pilot.pause()
        app._modal.query_one("#field-labels", Input).value = "area=town"
        await pilot.pause()
        await pilot.click("#prompt-ok")
        await pilot.pause()
    assert app.result == {"labels": "area=town"}


async def test_modal_cancel_returns_none():
    app = _Host(PromptModal("Bind macro", ["slot", "name"]))
    async with app.run_test() as pilot:
        await pilot.pause()
        await pilot.click("#prompt-cancel")
        await pilot.pause()
    assert app.result is None


async def test_modal_multiple_fields():
    app = _Host(PromptModal("Bind macro", ["slot", "name"]))
    async with app.run_test() as pilot:
        await pilot.pause()
        app._modal.query_one("#field-slot", Input).value = "B"
        app._modal.query_one("#field-name", Input).value = "heal"
        await pilot.pause()
        await pilot.click("#prompt-ok")
        await pilot.pause()
    assert app.result == {"slot": "B", "name": "heal"}


# ---- prompt_via_app bridge (fake app, no real event loop) ----


class _FakeApp:
    def __init__(self, canned) -> None:
        self._canned = canned

    def call_from_thread(self, fn, *args, **kwargs):
        return fn(*args, **kwargs)

    def push_screen(self, screen, callback):
        callback(self._canned)


def test_prompt_via_app_returns_submitted_values():
    res = prompt_via_app(_FakeApp({"labels": "x"}), "T", ["labels"])
    assert res == {"labels": "x"}


def test_prompt_via_app_cancel_returns_none():
    assert prompt_via_app(_FakeApp(None), "T", ["x"]) is None


def test_prompt_via_app_handles_dead_app():
    class Dead:
        def call_from_thread(self, *a, **k):
            raise RuntimeError("app not running")

    assert prompt_via_app(Dead(), "T", ["x"]) is None
