"""Reusable TUI input primitive — a modal that collects one or more text fields,
plus a cross-thread bridge so worker-thread code can request input from the
main-thread Textual app and block until the user responds.

This is general-purpose (title + field names → values); the emulator hotkey
flows are its first consumers, and later in-TUI flows (e.g. an AI-assistant
prompt) reuse the same `prompt(title, fields)` shape.
"""
from __future__ import annotations

import threading
from typing import Callable, cast

from textual.app import ComposeResult
from textual.containers import Horizontal, Vertical
from textual.screen import ModalScreen
from textual.widgets import Button, Input, Label


class PromptModal(ModalScreen):
    """Modal with one labeled Input per field. Dismisses with a
    ``{field: value}`` dict on OK/Enter, or ``None`` on Cancel/Escape."""

    BINDINGS = [("escape", "cancel", "Cancel")]

    DEFAULT_CSS = """
    PromptModal { align: center middle; }
    PromptModal > #prompt-box {
        width: 60; height: auto; padding: 1 2;
        border: round $accent; background: $panel;
    }
    PromptModal #prompt-buttons { height: auto; align-horizontal: right; }
    PromptModal Button { margin-left: 1; }
    """

    def __init__(self, title: str, fields: list[str]) -> None:
        super().__init__()
        self._title = title
        self._fields = fields

    def compose(self) -> ComposeResult:
        with Vertical(id="prompt-box"):
            yield Label(self._title)
            for name in self._fields:
                yield Label(name)
                yield Input(id=f"field-{name}")
            with Horizontal(id="prompt-buttons"):
                yield Button("OK", variant="primary", id="prompt-ok")
                yield Button("Cancel", id="prompt-cancel")

    def on_mount(self) -> None:
        if self._fields:
            self.query_one(f"#field-{self._fields[0]}", Input).focus()

    def _submit(self) -> None:
        values = {
            name: self.query_one(f"#field-{name}", Input).value for name in self._fields
        }
        self.dismiss(values)

    def action_cancel(self) -> None:
        self.dismiss(None)

    def on_button_pressed(self, event: Button.Pressed) -> None:
        if event.button.id == "prompt-ok":
            self._submit()
        else:
            self.dismiss(None)

    def on_input_submitted(self, event: Input.Submitted) -> None:
        self._submit()


def prompt_via_app(
    app, title: str, fields: list[str], modal_factory: Callable | None = None
) -> dict[str, str] | None:
    """From any thread, pop a PromptModal on ``app`` and block until the user
    responds. Returns the field values, or ``None`` on cancel / if the app
    can't accept the screen (e.g. not running yet)."""
    done = threading.Event()
    box: dict[str, object] = {}

    def _callback(value) -> None:
        box["result"] = value
        done.set()

    make = modal_factory or PromptModal
    try:
        app.call_from_thread(app.push_screen, make(title, fields), _callback)
    except Exception:
        return None
    done.wait()
    result = box.get("result")
    if result is None:
        return None
    return cast("dict[str, str]", result)
