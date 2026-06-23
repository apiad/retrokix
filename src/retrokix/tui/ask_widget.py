"""AskPane — a free-form question box for the LLM. Each question is stateless:
the model receives only the current game state + relevant Pokédex data + the
question (no conversation history).
"""
from __future__ import annotations

from textual.app import ComposeResult
from textual.containers import Horizontal, VerticalScroll
from textual.widgets import Button, Input, Static

from retrokix.plugins.pokemon.shared.context import build_ask_prompt, build_context
from retrokix.tui.llm import ASK_SYSTEM_PROMPT, generate_hint, load_config


class AskPane(Static):
    """Ask the LLM anything, grounded in the current game + Pokédex."""

    DEFAULT_CSS = """
    AskPane { height: 1fr; }
    AskPane #ask-bar { height: auto; dock: top; padding: 0 1; }
    AskPane #ask-input { width: 1fr; }
    AskPane #ask-btn { margin-left: 1; }
    AskPane #ask-answer { padding: 1 1; }
    """

    def __init__(self, ctx: object | None = None) -> None:
        super().__init__()
        self._ctx = ctx
        self._busy = False
        self._question = ""

    def compose(self) -> ComposeResult:
        with Horizontal(id="ask-bar"):
            yield Input(placeholder="Ask anything about your game…", id="ask-input")
            yield Button("Ask", id="ask-btn", variant="primary")
        with VerticalScroll():
            yield Static("Type a question and press Enter.", id="ask-answer")

    def on_button_pressed(self, event: Button.Pressed) -> None:
        if event.button.id == "ask-btn":
            self.ask()

    def on_input_submitted(self, event: Input.Submitted) -> None:
        if event.input.id == "ask-input":
            self.ask()

    def ask(self) -> None:
        runtime = getattr(self._ctx, "runtime", None)
        answer = self.query_one("#ask-answer", Static)
        question = self.query_one("#ask-input", Input).value.strip()
        if not question:
            return
        if runtime is None:
            answer.update("No save loaded.")
            return
        if self._busy:
            return
        self._busy = True
        self._question = question
        answer.update(f"[b]Q:[/b] {question}\n\n[dim]Thinking…[/dim]")
        self.run_worker(self._ask_blocking, thread=True, exclusive=True, group="ask")

    def _ask_blocking(self) -> None:
        runtime = getattr(self._ctx, "runtime", None)
        try:
            cfg = load_config()
            if not cfg.get("api_key") and "openrouter" in cfg["base_url"]:
                answer = "Set OPENROUTER_API_KEY or ~/.retrokix/llm.json to enable the assistant."
            else:
                prompt = build_ask_prompt(build_context(runtime), self._question)
                answer = generate_hint(prompt, cfg, system=ASK_SYSTEM_PROMPT)
        except Exception as exc:
            answer = f"[red]{type(exc).__name__}: {exc}[/red]"
        self.app.call_from_thread(self._show, answer)

    def _show(self, answer: str) -> None:
        self._busy = False
        self.query_one("#ask-answer", Static).update(f"[b]Q:[/b] {self._question}\n\n{answer}")
