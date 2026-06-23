"""PartyPane — the live Pokémon Emerald party tab.

Reads the six party slots from the running game via ``read_slot`` and renders a
table (the TUI counterpart of the emerald plugin's Rich party panel). The row
formatting lives in the pure ``format_party_row`` so it's unit-testable without
Textual or a runtime.
"""
from __future__ import annotations

from textual.app import ComposeResult
from textual.widgets import DataTable, Static

from retrokix.plugins.pokemon.shared.party import SLOT_COUNT, read_slot

_HEALTHY = {"", "ok", "none", "healthy"}

_COLUMNS = ("#", "species", "Lv", "HP", "XP", "status", "next move", "next evo")


def format_party_row(slot: dict) -> dict:
    """A party slot dict → display strings for one table row."""
    hp, max_hp = slot.get("hp", 0), slot.get("max_hp", 0) or 0
    ratio = hp / max_hp if max_hp else 0
    color = "green" if ratio >= 0.5 else "yellow" if ratio >= 0.25 else "red"

    span = slot.get("exp_level_span") or 0
    into = slot.get("exp_into_level") or 0
    xp = f"{int(100 * into / span) if span else 0}%"

    status = str(slot.get("status") or "").strip()
    status_str = "—" if status.lower() in _HEALTHY else status

    nm = slot.get("next_move")
    next_move = f"{nm['move_name']} @L{nm['level']} (+{nm['in']})" if nm else "—"

    ev = slot.get("next_evolution")
    if ev and ev.get("trigger") == "LEVEL":
        next_evo = f"{ev['target_name']} @L{ev['at_level']} (+{ev['in']})"
    elif ev:
        next_evo = f"{ev['target_name']} ({ev['trigger'].lower()})"
    else:
        next_evo = "—"

    return {
        "slot": str(slot.get("slot", "")),
        "species": str(slot.get("species_name", "")),
        "level": str(slot.get("level", "")),
        "hp": f"{hp}/{max_hp}",
        "hp_color": color,
        "xp": xp,
        "status": status_str,
        "next_move": next_move,
        "next_evo": next_evo,
    }


class PartyPane(Static):
    """Live six-slot party table for Pokémon Emerald."""

    DEFAULT_CSS = """
    PartyPane { height: 1fr; }
    PartyPane #party-empty { padding: 1 2; color: $text-muted; }
    """

    def __init__(self, ctx: object | None = None) -> None:
        super().__init__()
        self._ctx = ctx

    def compose(self) -> ComposeResult:
        table: DataTable[str] = DataTable(
            id="party-table", zebra_stripes=True, cursor_type="row"
        )
        for col in _COLUMNS:
            table.add_column(col, key=col)
        yield table
        yield Static("No party loaded.", id="party-empty")

    def on_mount(self) -> None:
        self.refresh_party()
        self.set_interval(1.0, self.refresh_party)

    def refresh_party(self) -> None:
        runtime = getattr(self._ctx, "runtime", None)
        rows = []
        if runtime is not None:
            for i in range(SLOT_COUNT):
                try:
                    slot = read_slot(runtime, i)
                except Exception:
                    slot = None
                if slot and slot.get("species"):
                    rows.append(format_party_row(slot))

        table = self.query_one("#party-table", DataTable)
        empty = self.query_one("#party-empty", Static)
        table.clear()
        for r in rows:
            table.add_row(
                r["slot"],
                r["species"],
                r["level"],
                f"[{r['hp_color']}]{r['hp']}[/{r['hp_color']}]",
                r["xp"],
                r["status"],
                r["next_move"],
                r["next_evo"],
            )
        table.display = bool(rows)
        empty.display = not rows
