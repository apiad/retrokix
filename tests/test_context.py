"""Tests for the LLM context builder (pure parts)."""
from __future__ import annotations

from retrokix.plugins.pokemon.shared import context as C

_CTX = {
    "trainer": {"name": "ALEX", "id": 31742, "gender": "M"},
    "money": 8920,
    "badges": 1,
    "play_time": {"h": 16, "m": 40, "s": 10},
    "dex": {"caught": 14, "seen": 25, "total": 386},
    "location": (0, 11),
    "wild_land": [],
    "party": [{"name": "Combusken", "level": 18, "hp": 55, "max_hp": 55}],
    "balls": [{"id": 4, "name": "Poke-Ball", "qty": 3}],
    "key_items": [{"id": 263, "name": "Devon-Goods"}, {"id": 264, "name": "Letter"}],
}


def test_context_prompt_includes_key_facts():
    p = C.context_prompt(_CTX)
    assert "ALEX" in p
    assert "8920" in p or "8,920" in p
    assert "Combusken" in p
    assert "1/8" in p
    assert "Devon-Goods" in p


def test_salient_signature_changes_on_location():
    a = C.salient_signature(_CTX)
    b = C.salient_signature({**_CTX, "location": (0, 16)})
    assert a != b


def test_salient_signature_changes_on_badge_and_keyitem_and_battle():
    base = C.salient_signature(_CTX)
    assert base != C.salient_signature({**_CTX, "badges": 2})
    assert base != C.salient_signature(
        {**_CTX, "key_items": _CTX["key_items"] + [{"id": 265, "name": "HM01"}]}
    )
    assert base != C.salient_signature({**_CTX, "battle": {"double": False, "opponents": [], "enemy_team": []}})


def test_salient_signature_stable_on_hp_or_level_change():
    a = C.salient_signature(_CTX)
    b = C.salient_signature({**_CTX, "party": [{"name": "Combusken", "level": 19, "hp": 1, "max_hp": 60}]})
    assert a == b


def test_context_prompt_renders_grounded_gym_facts():
    ctx = {
        **_CTX,
        "location_name": "DEWFORD TOWN",
        "next_gym": {"leader": "Brawly", "town": "Dewford Town", "type": "Fighting", "ace_level": 19},
        "gym_plan": {"se_types": ["Flying", "Psychic"], "resist": ["Abra (×0.5)"], "weak": [], "neutral": []},
    }
    p = C.context_prompt(ctx)
    assert "DEWFORD TOWN" in p
    assert "Brawly" in p and "Fighting" in p
    assert "Flying" in p and "Psychic" in p
    assert "[authoritative]" in p


def test_location_name_live():
    from pathlib import Path

    import pytest

    rom = Path.home() / ".retrokix/roms/Pokemon - Emerald Version (USA, Europe).gba"
    st = Path.home() / ".retrokix/saves/f3ae088181bf583e55daf962a92bb46f4f1d07b7/slot-1.state"
    if not (rom.exists() and st.exists()):
        pytest.skip("Emerald ROM/save not present")
    from retrokix.plugins.pokemon.shared.world import location_name
    from retrokix.runtime import EmulatorRuntime

    rt = EmulatorRuntime(rom)
    try:
        rt.load_state_from_file(st)
        rt.step(2)
        assert location_name(rt) == "DEWFORD TOWN"
    finally:
        rt.close()
