"""Tests for the Ask panel: relevant-species selection, prompt build, pane."""
from __future__ import annotations

from textual.app import App, ComposeResult

from retrokix.plugins.pokemon.shared import context as C
from retrokix.plugins.pokemon.shared.pokedex_model import species_name
from retrokix.tui.ask_widget import AskPane

_CTX = {
    "trainer": {"name": "ALEX", "id": 1, "gender": "M"},
    "money": 100,
    "badges": 1,
    "party": [{"name": "Combusken", "species": 281, "level": 18, "hp": 55, "max_hp": 55}],
}


def test_relevant_species_includes_party():
    assert 281 in C.relevant_species(_CTX, "how is my team?")


def test_relevant_species_includes_question_named():
    # Ralts internal id 392; the question names it.
    ids = C.relevant_species(_CTX, "should I catch a Ralts here?")
    assert any(species_name(i) == "Ralts" for i in ids)


def test_relevant_species_includes_battle_opponents():
    ctx = {**_CTX, "battle": {"opponent_species": [386]}}  # Volbeat
    assert 386 in C.relevant_species(ctx, "what now?")


def test_pokedex_brief_has_name_and_types():
    b = C.pokedex_brief(6)  # Charizard
    assert "Charizard" in b
    assert "Fire" in b and "Flying" in b
    assert "BST" in b


def test_build_ask_prompt_contains_state_pokedex_and_question():
    p = C.build_ask_prompt(_CTX, "is Combusken good?")
    assert "ALEX" in p                  # state
    assert "Combusken" in p             # party + pokedex brief
    assert "Pokédex data" in p          # injected section
    assert "is Combusken good?" in p    # the question


class _Host(App):
    def __init__(self, pane):
        super().__init__()
        self._pane = pane

    def compose(self) -> ComposeResult:
        yield self._pane


class _FakeRuntime:
    rom_path = "/nonexistent.gba"

    def read_memory(self, addr, n):
        return b"\x00" * n


async def test_ask_pane_updates_answer(monkeypatch):
    monkeypatch.setattr("retrokix.tui.ask_widget.generate_hint", lambda prompt, cfg, **k: "Yes, train it.")
    monkeypatch.setattr(
        "retrokix.tui.ask_widget.load_config",
        lambda *a, **k: {"base_url": "http://x/v1", "api_key": "k", "model": "m"},
    )
    ctx = type("C", (), {"runtime": _FakeRuntime()})()
    app = _Host(AskPane(ctx))
    async with app.run_test() as pilot:
        app.query_one("#ask-input").value = "is Combusken good?"
        app.query_one(AskPane).ask()
        await app.workers.wait_for_complete()
        await pilot.pause()
        rendered = str(app.query_one("#ask-answer").render())
        assert "Yes, train it." in rendered
        assert "is Combusken good?" in rendered
