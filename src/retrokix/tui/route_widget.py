"""RoutePane — live wild-encounter panel for the current map, with catch odds
vs the player's best ball. Pure `format_encounters` carries the rendering.
"""
from __future__ import annotations

from textual.app import ComposeResult
from textual.containers import VerticalScroll
from textual.widgets import Static

from retrokix.plugins.pokemon.shared.bag import read_bag
from retrokix.plugins.pokemon.shared.catch import best_ball, catch_chance
from retrokix.plugins.pokemon.shared.data import load_species_info
from retrokix.plugins.pokemon.shared.encounters import read_encounters

_METHODS = (("land", "Land"), ("water", "Surf"), ("fishing", "Fish"))


def _catch_rate(species: int) -> int:
    return int((load_species_info().get(str(species)) or {}).get("catchRate", 0))


def format_encounters(enc: dict, ball: tuple[str, float]) -> str:
    name, bonus = ball
    has_any = any(enc.get(m) for m, _ in _METHODS)
    if not has_any:
        return "[dim]No wild encounters here.[/dim]"

    lines = [f"[dim]catch % shown for your best ball:[/dim] {name}", ""]
    for method, label in _METHODS:
        rows = enc.get(method) or []
        if not rows:
            continue
        lines.append(f"[b cyan]{label}[/b cyan]")
        for r in rows:
            lvl = f"L{r['min']}" if r["min"] == r["max"] else f"L{r['min']}-{r['max']}"
            pct = catch_chance(_catch_rate(r["species"]), bonus) * 100
            # Fishing spans three rods — a summed rate is meaningless, so omit it.
            rate = "    " if method == "fishing" else f"{r['rate']:>2}%"
            lines.append(f"  {r['name']:<12} {lvl:<8} {rate}   catch {pct:>3.0f}%")
        lines.append("")
    return "\n".join(lines).rstrip()


class RoutePane(Static):
    """Live wild-encounter + catch-odds view for the current map."""

    DEFAULT_CSS = """
    RoutePane { height: 1fr; }
    RoutePane #route-header { dock: top; padding: 1 1; }
    RoutePane #route-body { padding: 0 1; }
    RoutePane #route-empty { padding: 1 2; color: $text-muted; }
    """

    def __init__(self, ctx: object | None = None) -> None:
        super().__init__()
        self._ctx = ctx

    def compose(self) -> ComposeResult:
        yield Static(id="route-header")
        with VerticalScroll():
            yield Static(id="route-body")
        yield Static("No save loaded.", id="route-empty")

    def on_mount(self) -> None:
        self.refresh_route()
        self.set_interval(2.0, self.refresh_route)

    def refresh_route(self) -> None:
        runtime = getattr(self._ctx, "runtime", None)
        enc = read_encounters(runtime) if runtime is not None else None

        header = self.query_one("#route-header", Static)
        body = self.query_one("#route-body", Static)
        empty = self.query_one("#route-empty", Static)

        if enc is None:
            header.display = body.display = False
            empty.display = True
            return
        header.display = body.display = True
        empty.display = False
        g, n = enc["location"]
        header.update(f"[b]Current map[/b]  ({g}, {n})")
        ball = best_ball(read_bag(runtime) or {})
        body.update(format_encounters(enc, ball))
