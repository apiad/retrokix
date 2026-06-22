"""Pokédex model — pure search / filter / detail-assembly over bundled data.

No ROM, no save, no network, no Textual. Everything here reads only the
bundled ``emerald_*.json`` tables via ``retrokix.plugins.pokemon.shared.data``
and the type-matchup helpers in ``.formulas``. The Textual ``PokedexPane``
widget is a thin presentation layer over these functions.

Species are keyed and ordered by their internal Emerald species id. For
Kanto/Johto (1–251) that equals the national dex number; Hoenn species sit at
higher internal ids (277+), so the displayed ``#`` is the species id, not the
national dex number — there is no national-dex mapping in the bundled data.
"""

from __future__ import annotations

from functools import cache

from retrokix.plugins.pokemon.shared import formulas as _F
from retrokix.plugins.pokemon.shared.data import (
    load_evolutions,
    load_levelup,
    load_moves,
    load_species_info,
    load_types,
)

# Display columns for the six base stats, in canonical order.
STAT_COLUMNS: list[tuple[str, str]] = [
    ("HP", "baseHP"),
    ("Atk", "baseAttack"),
    ("Def", "baseDefense"),
    ("SpA", "baseSpAttack"),
    ("SpD", "baseSpDefense"),
    ("Spe", "baseSpeed"),
]

_GROWTH_NAMES = {
    0: "Medium Fast",
    1: "Erratic",
    2: "Fluctuating",
    3: "Medium Slow",
    4: "Fast",
    5: "Slow",
}


def _pretty(token: str) -> str:
    """Constant-style name → display: ``"SHELL_ARMOR"`` → ``"Shell Armor"``."""
    return token.replace("_", " ").title()


@cache
def species_ids() -> list[int]:
    """All species ids with base-stat data, ascending (386 species)."""
    return sorted(int(k) for k in load_species_info())


@cache
def _names() -> dict[int, str]:
    from retrokix.plugins.pokemon.shared.party import SPECIES_NAMES

    return {int(k): str(v) for k, v in SPECIES_NAMES.items()}


def species_name(species_id: int) -> str:
    return _names().get(species_id, f"#{species_id}")


@cache
def _type_names() -> dict[int, str]:
    return {int(k): v for k, v in load_types().items()}


@cache
def _evolves_from_index() -> dict[int, dict]:
    """target species id → {id, name, method} of what it evolves from."""
    index: dict[int, dict] = {}
    for from_id_str, evos in load_evolutions().items():
        from_id = int(from_id_str)
        for evo in evos:
            target = evo.get("target_species")
            if target is None:
                continue
            index[int(target)] = {
                "id": from_id,
                "name": species_name(from_id),
                "method": _method_str(evo),
            }
    return index


def _method_str(evo: dict) -> str:
    trigger = (evo.get("trigger") or "").upper()
    param = evo.get("param")
    if trigger == "LEVEL":
        return f"Level {param}"
    if trigger in ("ITEM", "STONE"):
        return f"Use {_pretty(str(param))}" if param else "Use item"
    if trigger == "FRIENDSHIP":
        return "High friendship"
    if trigger == "TRADE":
        return "Trade"
    pretty = _pretty(trigger) if trigger else "Special"
    return f"{pretty} {param}".strip() if param else pretty


def search(query: str) -> list[int]:
    """Species ids matching ``query``, in species-id order.

    Grammar: whitespace-separated tokens, AND-combined.
    - ``type:<name>`` filters to species of that type (case-insensitive).
    - a ``#NNN`` or bare-numeric token matches the species with that id.
    - any other token is a case-insensitive substring match on the name.
    Empty query returns all species.
    """
    tokens = (query or "").split()
    if not tokens:
        return species_ids()

    result = species_ids()
    for token in tokens:
        lower = token.lower()
        if lower.startswith("type:"):
            wanted = lower[len("type:") :]
            result = [i for i in result if wanted in _types_lower(i)]
        elif _as_number(token) is not None:
            n = _as_number(token)
            result = [i for i in result if i == n]
        else:
            result = [i for i in result if lower in species_name(i).lower()]
    return result


def _as_number(token: str) -> int | None:
    raw = token[1:] if token.startswith("#") else token
    return int(raw) if raw.isdigit() else None


def _types_lower(species_id: int) -> list[str]:
    info = load_species_info().get(str(species_id), {})
    return [t.lower() for t in info.get("types", [])]


def assemble_detail(species_id: int) -> dict | None:
    """Everything the detail pane renders, or ``None`` if unknown."""
    info = load_species_info().get(str(species_id))
    if not info:
        return None

    stats = [(label, int(info.get(field, 0))) for label, field in STAT_COLUMNS]
    total = sum(v for _, v in stats)

    type_ids = _F.species_types(species_id) or []
    tnames = _type_names()
    weak = _F.weaknesses(type_ids)
    resist = _F.resistances(type_ids)
    matchups = {
        "weak_x4": [tnames.get(t, str(t)) for t, m in weak if m >= 4],
        "weak_x2": [tnames.get(t, str(t)) for t, m in weak if 1 < m < 4],
        "resists": [tnames.get(t, str(t)) for t, m in resist if 0 < m < 1],
        "immune": [tnames.get(t, str(t)) for t, m in resist if m == 0],
    }

    evos_into = [
        {
            "id": int(evo["target_species"]),
            "name": species_name(int(evo["target_species"])),
            "method": _method_str(evo),
        }
        for evo in load_evolutions().get(str(species_id), [])
        if evo.get("target_species") is not None
    ]

    return {
        "id": species_id,
        "name": species_name(species_id),
        "types": [_pretty(t) for t in dict.fromkeys(info.get("types", []))],
        "stats": stats,
        "total": total,
        "abilities": [_pretty(a) for a in info.get("abilities", []) if a != "NONE"],
        "matchups": matchups,
        "evolves_from": _evolves_from_index().get(species_id),
        "evolves_into": evos_into,
        "egg_groups": [_pretty(g) for g in info.get("eggGroups", [])],
        "catch_rate": int(info.get("catchRate", 0)),
        "exp_yield": int(info.get("expYield", 0)),
        "growth": _GROWTH_NAMES.get(int(info.get("growthRate", 0)), "—"),
        "levelup": _levelup(species_id),
    }


def _stat_bar(value: int, width: int = 10, cap: int = 200) -> str:
    filled = max(0, min(width, round(value / cap * width)))
    return "█" * filled + "░" * (width - filled)


def format_detail(detail: dict | None) -> str:
    """Render a detail dict (from :func:`assemble_detail`) as Rich markup."""
    if not detail:
        return "[dim]No data.[/dim]"

    d = detail
    types = " / ".join(d["types"])
    lines = [f"[b]#{d['id']:03d}  {d['name']}[/b]   [cyan]{types}[/cyan]", ""]

    for label, value in d["stats"]:
        lines.append(f"{label:>3} {value:>3}  {_stat_bar(value)}")
    lines.append(f"[dim]Total[/dim] {d['total']}")
    lines.append("")

    if d["abilities"]:
        lines.append(f"Ability: {', '.join(d['abilities'])}")
    lines.append(f"Catch rate: {d['catch_rate']}   Exp: {d['exp_yield']}   Growth: {d['growth']}")

    m = d["matchups"]
    weak = m["weak_x4"] + m["weak_x2"]
    if weak:
        x4 = [f"{t} ×4" for t in m["weak_x4"]]
        lines.append("[red]Weak:[/red] " + ", ".join(x4 + m["weak_x2"]))
    if m["resists"]:
        lines.append("[green]Resists:[/green] " + ", ".join(m["resists"]))
    if m["immune"]:
        lines.append("[green]Immune:[/green] " + ", ".join(m["immune"]))

    if d["evolves_from"]:
        ef = d["evolves_from"]
        lines.append(f"Evolves from {ef['name']} ({ef['method']})")
    for ev in d["evolves_into"]:
        lines.append(f"Evolves into {ev['name']} ({ev['method']})")

    if d["egg_groups"]:
        lines.append(f"Egg groups: {' / '.join(d['egg_groups'])}")

    if d["levelup"]:
        lines.append("")
        lines.append("[u]Level-up moves[/u]")
        for mv in d["levelup"]:
            power = f"  pow {mv['power']}" if mv.get("power") else ""
            mtype = f"  {mv['type']}" if mv.get("type") else ""
            lines.append(f"  L{mv['level']:>2}  {mv['move']}{mtype}{power}")

    return "\n".join(lines)


def _levelup(species_id: int) -> list[dict]:
    moves_table = load_moves()
    out = []
    for entry in load_levelup().get(str(species_id), []):
        move_info = moves_table.get(str(entry.get("move_id"))) or {}
        out.append(
            {
                "level": entry.get("level"),
                "move": entry.get("move_name"),
                "type": _pretty(move_info.get("type", "")) if move_info.get("type") else "",
                "power": move_info.get("power"),
            }
        )
    return out
