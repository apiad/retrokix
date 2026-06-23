"""Tests for the play_loop prompt-driven helpers (_ask_one, _bind_macro)."""
from __future__ import annotations

import types

from retrokix.render.sdl import _ask_one, _bind_macro, default_keymap


# ---- _ask_one: prompt vs terminal selection ----


def test_ask_one_uses_prompt_when_given():
    prompt = lambda title, fields: {"labels": "area=town  "}  # noqa: E731
    assert _ask_one(prompt, "T", "labels", "term: ") == "area=town"


def test_ask_one_cancel_returns_empty():
    prompt = lambda title, fields: None  # noqa: E731
    assert _ask_one(prompt, "T", "labels", "term: ") == ""


def test_ask_one_falls_back_to_input(monkeypatch):
    monkeypatch.setattr("builtins.input", lambda _p: "  typed  ")
    assert _ask_one(None, "T", "x", "term: ") == "typed"


# ---- _bind_macro: validation + save ----


def _macro():
    return types.SimpleNamespace(slot="", name="", total_frames=5)


def test_bind_macro_saves_valid_slot(monkeypatch):
    saved = []
    monkeypatch.setattr("retrokix.macros.save", lambda m: saved.append(m))
    macro = _macro()
    # "B" is the letter-B key — not a GBA-mapped slot (GBA B = the 'z' key).
    _bind_macro(macro, default_keymap(), lambda t, f: {"slot": "B", "name": "heal"})
    assert macro.slot == "B"
    assert macro.name == "heal"
    assert saved == [macro]


def test_bind_macro_rejects_gba_mapped_slot(monkeypatch):
    saved = []
    monkeypatch.setattr("retrokix.macros.save", lambda m: saved.append(m))
    # 'z' is mapped to the GBA B button → must be refused.
    _bind_macro(_macro(), default_keymap(), lambda t, f: {"slot": "Z", "name": ""})
    assert saved == []


def test_bind_macro_cancel_discards(monkeypatch):
    saved = []
    monkeypatch.setattr("retrokix.macros.save", lambda m: saved.append(m))
    _bind_macro(_macro(), default_keymap(), lambda t, f: None)
    assert saved == []
