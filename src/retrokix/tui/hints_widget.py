"""HintsPane — an LLM-powered contextual guide. Gathers the live game state,
sends it to an OpenAI-style chat endpoint (OpenRouter or local), and shows a
short "what to do next" hint. On-demand by default; Auto regenerates on salient
state changes (location / battle / badge / new key item).
"""
from __future__ import annotations

from textual.app import ComposeResult
from textual.containers import Horizontal, VerticalScroll
from textual.widgets import Button, Checkbox, Static

from retrokix.plugins.pokemon.shared.context import (
    build_context,
    context_prompt,
    salient_signature,
)
from retrokix.tui.llm import generate_hint, load_config


class HintsPane(Static):
    """LLM hint panel with on-demand + Auto-on-change generation."""

    BINDINGS = [("g", "generate", "Generate hint")]

    DEFAULT_CSS = """
    HintsPane { height: 1fr; }
    HintsPane #hints-bar { height: auto; dock: top; padding: 0 1; }
    HintsPane #hints-bar Checkbox { margin-left: 2; }
    HintsPane #hints-text { padding: 1 1; }
    """

    def __init__(self, ctx: object | None = None) -> None:
        super().__init__()
        self._ctx = ctx
        self._auto = False
        self._last_sig: tuple | None = None
        self._busy = False

    def compose(self) -> ComposeResult:
        with Horizontal(id="hints-bar"):
            yield Button("Generate hint (g)", id="hints-gen", variant="primary")
            yield Checkbox("Auto", id="hints-auto")
        with VerticalScroll():
            yield Static("Press [b]Generate[/b] (or g) for a contextual hint.", id="hints-text")

    def on_mount(self) -> None:
        self.set_interval(2.0, self._watch)

    # ---- triggers ----

    def action_generate(self) -> None:
        self.generate()

    def on_button_pressed(self, event: Button.Pressed) -> None:
        if event.button.id == "hints-gen":
            self.generate()

    def on_checkbox_changed(self, event: Checkbox.Changed) -> None:
        if event.checkbox.id == "hints-auto":
            self._auto = event.value
            self._last_sig = None  # fire once when turned on

    def _watch(self) -> None:
        runtime = getattr(self._ctx, "runtime", None)
        if not self._auto or runtime is None or self._busy:
            return
        try:
            sig = salient_signature(build_context(runtime))
        except Exception:
            return
        if sig != self._last_sig:
            self._last_sig = sig
            self.generate()

    # ---- generation (threaded) ----

    def generate(self) -> None:
        runtime = getattr(self._ctx, "runtime", None)
        text = self.query_one("#hints-text", Static)
        if runtime is None:
            text.update("No save loaded.")
            return
        if self._busy:
            return
        self._busy = True
        text.update("[dim]Thinking…[/dim]")
        self.run_worker(self._generate_blocking, thread=True, exclusive=True, group="hint")

    def _generate_blocking(self) -> None:
        runtime = getattr(self._ctx, "runtime", None)
        try:
            cfg = load_config()
            if not cfg.get("api_key") and "openrouter" in cfg["base_url"]:
                kind, text = "error", "Set OPENROUTER_API_KEY or ~/.retrokix/llm.json to enable hints."
            else:
                hint = generate_hint(context_prompt(build_context(runtime)), cfg)
                kind, text = "hint", hint
        except Exception as exc:
            kind, text = "error", f"{type(exc).__name__}: {exc}"
        self.app.call_from_thread(self._show, kind, text)

    def _show(self, kind: str, text: str) -> None:
        self._busy = False
        widget = self.query_one("#hints-text", Static)
        widget.update(text if kind == "hint" else f"[red]{text}[/red]")
