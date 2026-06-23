"""Tests for the Pokédex model — pure search/filter/detail over bundled data.

Grounded in verified Emerald data: Charizard is species #6 (Fire/Flying,
base-stat total 534, ability Blaze, weak ×4 to Rock, immune to Ground),
Bulbasaur is #1 and evolves into Ivysaur at level 16.
"""
from __future__ import annotations

from retrokix.plugins.pokemon.shared import pokedex_model as M


# ---- species set ----


def test_species_ids_covers_all_386_in_national_order():
    ids = M.species_ids()
    assert len(ids) == 386
    # Ordered by national dex number, not internal species id.
    assert ids == sorted(ids, key=M.national_of)
    assert ids[0] == 1  # Bulbasaur (national 1)
    assert 6 in ids


def test_national_of_and_reverse():
    assert M.national_of(277) == 252  # Treecko: internal 277 → national 252
    assert M.national_of(1) == 1  # Bulbasaur: national == internal
    assert M.species_of_national(252) == 277
    assert M.species_of_national(1) == 1


def test_search_by_national_number():
    # "#252" is Treecko's national number → its internal species id 277.
    assert M.search("#252") == [277]
    assert M.search("252") == [277]


def test_detail_exposes_national_number():
    assert M.assemble_detail(277)["national"] == 252
    assert M.assemble_detail(6)["national"] == 6


def test_species_name_lookup():
    assert M.species_name(6) == "Charizard"
    assert M.species_name(1) == "Bulbasaur"


# ---- search ----


def test_search_empty_returns_all():
    assert M.search("") == M.species_ids()
    assert M.search("   ") == M.species_ids()


def test_search_name_substring():
    result = M.search("char")
    assert 4 in result and 5 in result and 6 in result  # Charmander line
    assert all("char" in M.species_name(i).lower() for i in result)


def test_search_is_case_insensitive():
    assert M.search("CHAR") == M.search("char")


def test_search_by_number_with_hash():
    assert M.search("#6") == [6]


def test_search_by_bare_number():
    assert M.search("6") == [6]


def test_search_by_type():
    result = M.search("type:fire")
    assert 6 in result
    assert 1 not in result  # Bulbasaur is Grass/Poison
    assert all("Fire" in M.assemble_detail(i)["types"] for i in result)


def test_search_tokens_and_combine():
    # Of the "char" line, only Charizard is also Flying.
    assert M.search("char type:flying") == [6]


# ---- detail ----


def test_detail_header_and_stats():
    d = M.assemble_detail(6)
    assert d["id"] == 6
    assert d["name"] == "Charizard"
    assert d["types"] == ["Fire", "Flying"]
    assert dict(d["stats"])["SpA"] == 109
    assert d["total"] == 534


def test_detail_abilities_filters_none():
    assert M.assemble_detail(6)["abilities"] == ["Blaze"]


def test_detail_monotype_is_not_duplicated():
    # Charmander is pure Fire; gen-3 stores both type slots as FIRE.
    assert M.assemble_detail(4)["types"] == ["Fire"]


def test_detail_extra_fields():
    d = M.assemble_detail(6)
    assert d["egg_groups"] == ["Monster", "Dragon"]
    assert d["catch_rate"] == 45
    assert d["growth"] == "Medium Slow"


def test_detail_matchups():
    m = M.assemble_detail(6)["matchups"]
    assert "Rock" in m["weak_x4"]
    assert "Water" in m["weak_x2"]
    assert "Ground" in m["immune"]
    assert "Fire" in m["resists"]


def test_detail_evolves_from():
    d = M.assemble_detail(6)
    assert d["evolves_from"]["name"] == "Charmeleon"
    assert "36" in d["evolves_from"]["method"]


def test_detail_evolves_into():
    into = M.assemble_detail(1)["evolves_into"]
    assert into[0]["name"] == "Ivysaur"
    assert "16" in into[0]["method"]


def test_detail_no_evolution_is_empty():
    d = M.assemble_detail(6)  # Charizard is final stage
    assert d["evolves_into"] == []


def test_detail_levelup_moves():
    moves = M.assemble_detail(1)["levelup"]
    first = moves[0]
    assert first["level"] == 1
    assert first["move"] == "Tackle"


def test_detail_unknown_species_returns_none():
    assert M.assemble_detail(9999) is None


# ---- detail formatting (Rich markup, pure) ----


def test_format_detail_includes_key_fields():
    text = M.format_detail(M.assemble_detail(6))
    assert "Charizard" in text
    assert "534" in text       # base-stat total
    assert "Rock" in text      # ×4 weakness
    assert "Blaze" in text     # ability
    assert "Charmeleon" in text  # evolves from


def test_format_detail_handles_final_stage_without_evolution():
    text = M.format_detail(M.assemble_detail(6))
    # Charizard has no evolves_into; must not crash or print a stray arrow line.
    assert "Evolves into" not in text
