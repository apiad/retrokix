"""Tests for the pure party-row formatter (tui/party_widget.format_party_row)."""
from __future__ import annotations

from retrokix.tui.party_widget import format_party_row

_SLOT = {
    "slot": 0,
    "species_name": "Combusken",
    "level": 18,
    "hp": 20,
    "max_hp": 50,
    "exp_into_level": 50,
    "exp_level_span": 100,
    "exp_to_next_level": 200,
    "status": "OK",
    "next_move": {"move_name": "Double Kick", "level": 26, "in": 8},
    "next_evolution": {"trigger": "LEVEL", "target_name": "Blaziken", "at_level": 36, "in": 18},
}


def test_basic_fields():
    r = format_party_row(_SLOT)
    assert r["slot"] == "0"
    assert r["species"] == "Combusken"
    assert r["level"] == "18"
    assert r["hp"] == "20/50"
    assert r["xp"] == "50%"


def test_hp_color_bands():
    assert format_party_row({**_SLOT, "hp": 45, "max_hp": 50})["hp_color"] == "green"   # 0.90
    assert format_party_row({**_SLOT, "hp": 20, "max_hp": 50})["hp_color"] == "yellow"  # 0.40
    assert format_party_row({**_SLOT, "hp": 5, "max_hp": 50})["hp_color"] == "red"      # 0.10


def test_status_healthy_is_dash():
    assert format_party_row({**_SLOT, "status": "OK"})["status"] == "—"
    assert format_party_row({**_SLOT, "status": "PSN"})["status"] == "PSN"


def test_next_move_and_evo_strings():
    r = format_party_row(_SLOT)
    assert r["next_move"] == "Double Kick @L26 (+8)"
    assert r["next_evo"] == "Blaziken @L36 (+18)"


def test_no_next_move_or_evo_is_dash():
    r = format_party_row({**_SLOT, "next_move": None, "next_evolution": None})
    assert r["next_move"] == "—"
    assert r["next_evo"] == "—"


def test_non_level_evolution_shows_trigger():
    r = format_party_row(
        {**_SLOT, "next_evolution": {"trigger": "STONE", "target_name": "Vaporeon"}}
    )
    assert r["next_evo"] == "Vaporeon (stone)"
