"""BattlePane — live battle helper for Pokémon Emerald. Shows the on-field
opponent(s) (single + double) with type weaknesses, plus the opponent's full
team so you can plan ahead. Pure formatters carry the rendering.
"""
from __future__ import annotations

from textual.app import ComposeResult
from textual.containers import VerticalScroll
from textual.widgets import Static

from retrokix.plugins.pokemon.shared.battle import (
    active_opponents,
    enemy_party,
    is_double,
    is_in_battle,
)
from retrokix.plugins.pokemon.shared.data import load_types
from retrokix.plugins.pokemon.shared.matchup import Defender, weakness_report


def _type_name(type_id: int) -> str:
    return load_types().get(str(type_id), f"#{type_id}")


def _type_id(name: str) -> int | None:
    return {v.upper(): int(k) for k, v in load_types().items()}.get((name or "").upper())


def best_counter(party: list[dict], opp_types: list[int]) -> dict | None:
    """Across the party's actual moves, the highest super-effective hit on an
    opponent. Returns {pokemon, move, mul} or None if nothing is super-effective."""
    from retrokix.plugins.pokemon.shared.formulas import type_effectiveness

    best = None
    best_key = (1.0, 0)
    for mon in party:
        for mv in mon.get("moves") or []:
            power = mv.get("power") or 0
            tid = _type_id(mv.get("type"))
            if not power or tid is None:
                continue
            eff = type_effectiveness(tid, opp_types)
            if eff <= 1:
                continue
            if (eff, power) > best_key:
                best_key = (eff, power)
                best = {"pokemon": mon["species_name"], "move": mv["name"], "mul": eff}
    return best


def _dedupe_types(types: list[int]) -> list[int]:
    return list(dict.fromkeys(types))


def format_weaknesses(types: list[int]) -> str:
    """Super-effective (×2+) attacking types against a defender, deduped."""
    deduped = _dedupe_types(types)
    rows = weakness_report(Defender(species=0, level=1, types=deduped))
    parts = [
        f"{r['type_name']} ×{int(r['mul']) if r['mul'] == int(r['mul']) else r['mul']}"
        for r in rows
        if r["mul"] >= 2
    ]
    return ", ".join(parts) if parts else "none"


def _opponent_line(o: dict, party: list[dict]) -> list[str]:
    types = " / ".join(_type_name(t) for t in _dedupe_types(o["types"]))
    lines = [
        f"[b]{o['species_name']}[/b]  L{o['level']}  {o['hp']}/{o['max_hp']}  [cyan]{types}[/cyan]",
        f"  [red]Weak:[/red] {format_weaknesses(o['types'])}",
    ]
    bc = best_counter(party, _dedupe_types(o["types"]))
    if bc:
        lines.append(f"  [green]Best:[/green] {bc['pokemon']} — {bc['move']} (×{bc['mul']:g})")
    lines.append("")
    return lines


def format_battle(
    active: list[dict], team: list[dict], is_double_flag: bool, party: list[dict] | None = None
) -> str:
    kind = "Double" if is_double_flag else "Single"
    lines = [f"[b]Battle[/b] — {kind}", ""]
    for o in active:
        lines.extend(_opponent_line(o, party or []))
    if team:
        lines.append("[b cyan]Opponent team[/b cyan]")
        for s in team:
            types = " / ".join(_type_name(t) for t in _dedupe_types(_species_types(s)))
            suffix = f"  [dim]{types}[/dim]" if types else ""
            lines.append(f"  {s['species_name']} L{s['level']}{suffix}")
    return "\n".join(lines).rstrip()


def _species_types(slot: dict) -> list[int]:
    sp = slot.get("species")
    if not sp:
        return []
    from retrokix.plugins.pokemon.shared.formulas import species_types

    return species_types(sp) or []


class BattlePane(Static):
    """Live opponent + weaknesses + full enemy team for Pokémon Emerald."""

    DEFAULT_CSS = """
    BattlePane { height: 1fr; }
    BattlePane #battle-body { padding: 1 1; }
    BattlePane #battle-empty { padding: 1 2; color: $text-muted; }
    """

    def __init__(self, ctx: object | None = None) -> None:
        super().__init__()
        self._ctx = ctx

    def compose(self) -> ComposeResult:
        with VerticalScroll():
            yield Static(id="battle-body")
        yield Static("Not in battle.", id="battle-empty")

    def on_mount(self) -> None:
        self.refresh_battle()
        self.set_interval(1.0, self.refresh_battle)

    def refresh_battle(self) -> None:
        runtime = getattr(self._ctx, "runtime", None)
        body = self.query_one("#battle-body", Static)
        empty = self.query_one("#battle-empty", Static)

        if runtime is None or not is_in_battle(runtime):
            body.display = False
            empty.display = True
            return
        body.display = True
        empty.display = False
        from retrokix.plugins.pokemon.shared.party import SLOT_COUNT, read_slot

        party = [s for s in (read_slot(runtime, i) for i in range(SLOT_COUNT)) if s]
        body.update(
            format_battle(
                active_opponents(runtime), enemy_party(runtime), is_double(runtime), party
            )
        )
