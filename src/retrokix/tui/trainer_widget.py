"""TrainerPane — live Emerald trainer panel: identity, money, badges, play
time, and the bag. Pure formatters carry the display logic; the pane reads the
live save via world.read_world / bag.read_bag and polls.
"""
from __future__ import annotations

from textual.app import ComposeResult
from textual.containers import VerticalScroll
from textual.widgets import Static

from retrokix.plugins.pokemon.shared.bag import read_bag
from retrokix.plugins.pokemon.shared.world import read_world

_POCKET_ORDER = ("Balls", "Items", "Key", "TMs", "Berries")


def format_trainer_header(world: dict) -> str:
    t = world["trainer"]
    gender = "♂" if t["gender"] == "M" else "♀"
    pt = world["play_time"]
    return (
        f"[b]{t['name']}[/b]  {gender}  ID {t['id']:05d}    "
        f"[yellow]₽{world['money']:,}[/yellow]    "
        f"🏅 {world['badges']['count']}/8    "
        f"⏱ {pt['h']}h{pt['m']:02d}m"
    )


def format_bag(bag: dict) -> str:
    lines = []
    for pocket in _POCKET_ORDER:
        items = bag.get(pocket) or []
        if not items:
            continue
        entries = ", ".join(f"{i['name']} ×{i['qty']}" for i in items)
        lines.append(f"[b cyan]{pocket}[/b cyan]  {entries}")
    return "\n".join(lines) if lines else "[dim]Bag empty.[/dim]"


class TrainerPane(Static):
    """Live trainer + bag view for Pokémon Emerald."""

    DEFAULT_CSS = """
    TrainerPane { height: 1fr; }
    TrainerPane #trainer-header { dock: top; padding: 1 1; }
    TrainerPane #trainer-bag { padding: 0 1; }
    TrainerPane #trainer-empty { padding: 1 2; color: $text-muted; }
    """

    def __init__(self, ctx: object | None = None) -> None:
        super().__init__()
        self._ctx = ctx

    def compose(self) -> ComposeResult:
        yield Static(id="trainer-header")
        with VerticalScroll():
            yield Static(id="trainer-bag")
        yield Static("No save loaded.", id="trainer-empty")

    def on_mount(self) -> None:
        self.refresh_trainer()
        self.set_interval(2.0, self.refresh_trainer)

    def refresh_trainer(self) -> None:
        runtime = getattr(self._ctx, "runtime", None)
        world = read_world(runtime) if runtime is not None else None
        bag = read_bag(runtime) if runtime is not None else None

        header = self.query_one("#trainer-header", Static)
        bag_w = self.query_one("#trainer-bag", Static)
        empty = self.query_one("#trainer-empty", Static)

        if world is None:
            header.display = bag_w.display = False
            empty.display = True
            return
        header.display = bag_w.display = True
        empty.display = False
        header.update(format_trainer_header(world))
        bag_w.update(format_bag(bag or {}))
